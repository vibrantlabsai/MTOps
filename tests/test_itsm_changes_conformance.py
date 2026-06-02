"""Differential conformance: our in-memory change tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the change port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_changes_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.changes import ChangeToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / "seed_main.json"


class ChangeTools(ChangeToolsMixin):
    """Standalone toolkit exposing only the change tools for the conformance run."""


# WRITE calls exercising create (defaults/category, cab_required, FKs, id+number sequences) and
# update (real field changes, requested_by, cab toggle). Order matters (sequential id generation).
WRITE_SCENARIO = [
    ("create_change", {"short_description": "minimal defaults only", "status": "new",
                       "impact": "low", "risk": "low", "priority": "low"}),
    ("create_change", {"short_description": "full payload change", "status": "assess",
                       "impact": "high", "risk": "high", "priority": "critical",
                       "service": "SVC_001", "service_offering": "SVCOFF_001",
                       "configuration_item": "CI_001", "category": "hardware",
                       "description": "detailed desc", "implementation_plan": "plan A",
                       "testing_plan": "test plan", "cab_required": True,
                       "assigned_to": "USER_003", "assignment_group": "GROUP_001",
                       "close_code": "successful", "close_notes": "done"}),
    ("create_change", {"short_description": "third change", "status": "scheduled",
                       "impact": "medium", "risk": "medium", "priority": "moderate",
                       "category": "software", "cab_required": False}),
    ("update_change", {"change_id": "CHG_001", "status": "review",
                       "assigned_to": "USER_003", "implementation_plan": "revised plan"}),
    ("update_change", {"change_id": "CHG_002", "requested_by": "USER_005",
                       "cab_required": False, "configuration_item": "CI_002"}),
    ("update_change", {"change_id": "CHG_003", "status": "implement",
                       "close_code": "successful", "close_notes": "wrapped up"}),
]

# Read calls compared on return value (oracle wraps list results in {"changes": [...]}).
READ_SCENARIO = [
    ("find_change_by_number", {"number": "CHG0000002"}),
    ("list_changes", {}),
    ("list_changes", {"status": "closed"}),
    ("list_changes", {"assignment_group": "GROUP_002"}),
    ("list_changes", {"short_description": "server"}),
    ("list_changes", {"priority": "low"}),
    ("list_changes", {"created_after": "2024-02-20T00:00:00"}),
    ("get_changes_assigned_to", {"assignment_group": "GROUP_002"}),
    ("get_changes_assigned_to", {"assigned_to": "USER_002"}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = ChangeTools(db, acting_user_id="USER_001")
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
    return val


def _unwrap_oracle(val):
    """The oracle wraps list endpoints as {'changes': [...], 'total_count': n}; unwrap it."""
    if isinstance(val, dict) and "changes" in val:
        return val["changes"]
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out org_id)."""
    ours = _normalize_return(ours)
    oracle = _unwrap_oracle(oracle)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
            elif str(ours[k]) != str(ov) and not (
                isinstance(ov, (int, float)) and isinstance(ours[k], (int, float))
                and float(ov) == float(ours[k])
            ):
                diffs.append(f"{k}: ours={ours[k]!r} oracle={ov!r}")
    elif isinstance(oracle, list) and isinstance(ours, list):
        if len(oracle) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle)}")
        else:
            ours_ids = sorted(r.get("change_id") for r in ours)
            oracle_ids = sorted(r.get("change_id") for r in oracle)
            if ours_ids != oracle_ids:
                diffs.append(f"ids ours={ours_ids} oracle={oracle_ids}")
    else:
        diffs.append(f"type mismatch ours={type(ours).__name__} oracle={type(oracle).__name__}")
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_chg_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = ChangeTools(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_chg_reads")
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
def test_change_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_change_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
