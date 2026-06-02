"""Differential conformance: our in-memory incident-SLA tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_incident_slas_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.incident_slas import IncidentSLAToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / "seed_main.json"


class T(IncidentSLAToolsMixin):
    """Concrete toolkit exposing only the incident-SLA tools for the conformance run."""


# WRITE calls exercising link (defaults + all fields), update (subset of fields), and
# delete (by id and by filter). Order matters: TSLA ids are generated sequentially, so the
# links come first (TSLA_011, TSLA_012), then a delete by filter, then an update.
WRITE_SCENARIO = [
    # link with only the required args -> stage defaults to in_progress, has_breached False.
    ("link_new_incident_sla", {"incident_id": "INC_005", "sla_def_id": "SLA_001",
                               "start_time": "2024-03-01T09:00:00"}),
    # link with every optional field populated.
    ("link_new_incident_sla", {"incident_id": "INC_006", "sla_def_id": "SLA_002",
                               "start_time": "2024-03-02T09:00:00", "stage": "paused",
                               "has_breached": True, "breach_time": "2024-03-02T13:00:00",
                               "completed_time": "2024-03-02T10:00:00"}),
    # update an existing seed record: change stage + breach flag + completion time.
    ("update_incident_sla_details", {"incident_sla_id": "TSLA_002", "stage": "completed",
                                     "has_breached": False,
                                     "completed_time": "2024-03-03T10:00:00"}),
    # update reassigning the incident/definition FKs on another seed record.
    ("update_incident_sla_details", {"incident_sla_id": "TSLA_004", "incident_id": "INC_007",
                                     "sla_def_id": "SLA_004"}),
    # delete a single record by id.
    ("delete_incident_slas", {"incident_sla_id": "TSLA_005"}),
    # delete by filter (stage) -- spans orgs, exercising the not-org-scoped behaviour.
    ("delete_incident_slas", {"stage": "cancelled"}),
]

# Read calls compared on return value (oracle projects shapes; compare shared keys).
READ_SCENARIO = [
    ("find_incident_slas", {}),
    ("find_incident_slas", {"stage": "breached"}),
    ("find_incident_slas", {"has_breached": True}),
    ("find_incident_slas", {"incident_id": "INC_001"}),
    ("find_incident_slas", {"created_before": "2024-02-15T00:00:00"}),
    ("find_stage_wise_breached_incident_sla_counts", {}),
    ("find_stage_wise_breached_incident_sla_counts",
     {"stages": ["in_progress", "completed", "breached"]}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    returns = []
    for tool, args in scenario:
        returns.append(tools.use_tool(tool, **args))
    return db.model_dump(), returns


def _normalize_return(val):
    """Make a tool return comparable: pydantic -> dict, list -> list of dict."""
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_return(v) for k, v in val.items()}
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it may project shapes)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
            elif isinstance(ov, list) and isinstance(ours[k], list):
                if len(ov) != len(ours[k]):
                    diffs.append(f"{k}: length ours={len(ours[k])} oracle={len(ov)}")
            elif isinstance(ov, dict) and isinstance(ours[k], dict):
                if ours[k] != ov:
                    diffs.append(f"{k}: ours={ours[k]!r} oracle={ov!r}")
            elif str(ours[k]) != str(ov) and not (
                isinstance(ov, (int, float)) and isinstance(ours[k], (int, float))
                and float(ov) == float(ours[k])
            ):
                diffs.append(f"{k}: ours={ours[k]!r} oracle={ov!r}")
    elif isinstance(oracle, list) and isinstance(ours, list):
        if len(oracle) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle)}")
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario.
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_isla_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable).
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_isla_reads")
    for tool, args in READ_SCENARIO:
        ours_r = tools.use_tool(tool, **args)
        oracle_r = o2.call(tool, args)
        d = _compare_return(ours_r, oracle_r)
        if d:
            read_diffs.append(f"{tool}{args}: {d}")
    o2._delete()

    if verbose:
        print(f"\n=== DB-state diffs ({len(db_diffs)}) ===")
        for d in db_diffs[:60]:
            print("  ", d)
        print(f"\n=== read-return diffs ({len(read_diffs)}) ===")
        for d in read_diffs[:30]:
            print("  ", d)
    return db_diffs, read_diffs


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_incident_sla_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_incident_sla_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
