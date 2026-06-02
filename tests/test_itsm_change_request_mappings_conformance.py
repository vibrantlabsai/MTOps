"""Differential conformance: our change_request_mapping tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_change_request_mappings_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.change_request_mappings import (
    ChangeRequestMappingToolsMixin,
)

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / "seed_main.json"


class T(ChangeRequestMappingToolsMixin):
    """Concrete toolkit exposing only the change_request_mapping category."""

    pass


# WRITE scenario exercising every write tool: map (incident-only, problem-only, both),
# delete (single by mapping id, multiple by change id). Order matters (sequential CRM ids).
WRITE_SCENARIO = [
    ("map_change_request", {"change_id": "CHG_001", "incident_id": "INC_003"}),
    ("map_change_request", {"change_id": "CHG_002", "problem_id": "PRB_002"}),
    ("map_change_request", {"change_id": "CHG_001", "incident_id": "INC_004",
                            "problem_id": "PRB_002"}),
    ("delete_change_request_mappings", {"change_request_mapping_id": "CRM_002"}),
    ("delete_change_request_mappings", {"change_id": "CHG_003"}),
]

# Read calls compared on return value. The oracle wraps results in
# {"change_request_mappings": [...], "total_count": N}.
READ_SCENARIO = [
    ("list_change_request_mappings", {}),
    ("list_change_request_mappings", {"change_id": "CHG_001"}),
    ("list_change_request_mappings", {"created_after": "2024-02-18T00:00:00"}),
    ("find_change_request_mappings_for_incident", {"incident_id": "INC_001"}),
    ("find_change_request_mappings_for_problem", {"problem_id": "PRB_001"}),
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
    """Compare returns on keys the oracle provides (it projects out org_id/_display)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
            elif isinstance(ov, list) and isinstance(ours[k], list):
                if len(ov) != len(ours[k]):
                    diffs.append(f"{k}: length ours={len(ours[k])} oracle={len(ov)}")
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
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_crm_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_crm_reads")
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
def test_crm_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_crm_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
