"""Differential conformance: our incident_affected_cis tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_incident_affected_cis_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.incident_affected_cis import IncidentAffectedCIToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(IncidentAffectedCIToolsMixin):
    """Standalone toolkit exposing only the incident_affected_cis tools."""


# A scenario of WRITE calls exercising link (id/seq, org scoping, FK validation paths) and
# remove (by id, by incident, by CI, by date range). Order matters (sequential id generation).
WRITE_SCENARIO = [
    # link continues the seed sequence -> TASKCI_004, TASKCI_005, TASKCI_006
    ("link_affected_ci_to_incident", {"configuration_item": "CI_004", "incident_id": "INC_005"}),
    ("link_affected_ci_to_incident", {"configuration_item": "CI_002", "incident_id": "INC_003"}),
    ("link_affected_ci_to_incident", {"configuration_item": "CI_003", "incident_id": "INC_009"}),
    # remove by specific mapping id
    ("remove_affected_ci_from_incident", {"incident_affected_cis_id": "TASKCI_005"}),
    # remove by incident id (TASKCI_001 -> INC_001)
    ("remove_affected_ci_from_incident", {"incident_id": "INC_001"}),
    # remove by configuration_item (CI_002 -> TASKCI_002)
    ("remove_affected_ci_from_incident", {"configuration_item": "CI_002"}),
    # remove by date range: created_before deletes the old Feb-2024 seed row TASKCI_003 only
    # (the boundary stays below our frozen-clock new-link timestamps so it is unambiguous).
    ("remove_affected_ci_from_incident", {"created_before": "2024-03-01"}),
]

# Read calls compared on return value. Single-item filters keep ordering deterministic; the
# no-filter list validates created_on-desc ordering and total_count.
READ_SCENARIO = [
    ("list_incident_affected_cis", {}),
    ("list_incident_affected_cis", {"incident_id": "INC_001"}),
    ("list_incident_affected_cis", {"configuration_item": "CI_002"}),
    ("list_incident_affected_cis", {"incident_affected_cis_id": "TASKCI_003"}),
    ("list_incident_affected_cis", {"created_after": "2024-02-15"}),
    ("list_incident_affected_cis", {"created_before": "2024-02-15"}),
    ("list_incident_affected_cis", {"incident_id": "INC_999"}),  # empty result
]


def _toolkit():
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    return db, T(db, acting_user_id="USER_001")


def _run_ours(scenario):
    db, tools = _toolkit()
    returns = []
    for tool, args in scenario:
        returns.append(tools.use_tool(tool, **args))
    return db.model_dump(), returns


def _normalize_return(val):
    """Make a tool return comparable: pydantic -> dict, list/dict normalized recursively."""
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_return(v) for k, v in val.items()}
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out some derived fields)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
                continue
            d = _compare_return(ours[k], ov)
            if d:
                diffs.extend(f"{k}.{x}" for x in d)
    elif isinstance(oracle, list) and isinstance(ours, list):
        if len(oracle) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle)}")
        else:
            for i, (o_item, oc_item) in enumerate(zip(ours, oracle)):
                d = _compare_return(o_item, oc_item)
                if d:
                    diffs.extend(f"[{i}].{x}" for x in d)
    else:
        if str(ours) != str(oracle) and not (
            isinstance(oracle, (int, float)) and isinstance(ours, (int, float))
            and float(oracle) == float(ours)
        ):
            diffs.append(f"ours={ours!r} oracle={oracle!r}")
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_aci_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids/timestamps are the seed's)
    read_diffs: list[str] = []
    _, tools = _toolkit()
    o2 = MCPOracle("conf_aci_reads")
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
def test_incident_affected_cis_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_incident_affected_cis_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
