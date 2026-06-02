"""Differential conformance: our in-memory problem tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_problems_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.problems import ProblemToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / "seed_main.json"


class T(ProblemToolsMixin):
    """Toolkit exposing only the problem tools for differential testing."""


# WRITE calls exercising create (defaults, id/number generation, FKs, opened_by/org inheritance)
# and update (by id, by number, multi-field). Order matters (sequential id/number generation).
# All enum values must be lowercase (the MCP rejects upper-case enum inputs at validation).
WRITE_SCENARIO = [
    ("create_problem", {"problem_statement": "defaults only required",
                        "status": "new", "impact": "low", "urgency": "low",
                        "priority": "planning"}),
    ("create_problem", {"problem_statement": "full create with refs",
                        "status": "assess", "impact": "high", "urgency": "medium",
                        "priority": "high", "short_description": "sd full",
                        "service": "SVC_001", "service_offering": "SVCOFF_001",
                        "configuration_item": "CI_001", "assigned_to": "USER_003",
                        "assignment_group": "GROUP_001", "original_task": "INC_002",
                        "category": "network", "worknotes": "wn", "workaround": "wa",
                        "fix_notes": "fn"}),
    ("create_problem", {"problem_statement": "third problem",
                        "status": "root_cause", "impact": "medium", "urgency": "high",
                        "priority": "moderate", "category": "software"}),
    ("update_problem", {"problem_id": "PRB_001", "status": "resolved",
                        "fix_notes": "load balancer corrected", "assigned_to": "USER_005"}),
    ("update_problem", {"number": "PRB0000001", "assigned_to": "USER_007",
                        "workaround": "use webmail"}),
    ("update_problem", {"problem_id": "PRB_003", "opened_by": "USER_004",
                        "category": "database", "priority": "high",
                        "assignment_group": "GROUP_002", "configuration_item": "CI_002"}),
]

# Read calls compared on return value (oracle wraps in {problems, total_count} or projects keys).
READ_SCENARIO = [
    ("find_problem_by_number", {"number": "PRB0000001"}),
    ("list_problems", {}),
    ("list_problems", {"status": "root_cause"}),
    ("list_problems", {"status": "ROOT_CAUSE"}),
    ("list_problems", {"problem_statement": "EMAIL"}),
    ("list_problems", {"priority": "moderate", "category": "network"}),
    ("list_problems", {"created_after": "2024-02-15T00:00:00"}),
    ("list_problems", {"created_before": "2024-02-16T13:20:00"}),
    ("get_problems_assigned_to", {"assignment_group": "GROUP_002"}),
    ("get_problems_assigned_to", {"assigned_to": "USER_008"}),
    ("get_problems_assigned_to", {}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    returns = []
    for tool, args in scenario:
        returns.append(tools.use_tool(tool, **args))
    return db.model_dump(), returns


def _normalize_return(val):
    """Make a tool return comparable: pydantic -> dict, list -> list of dict, dict recursively."""
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_return(v) for k, v in val.items()}
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it may project out org_id / wrap lists)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
            elif isinstance(ov, list) and isinstance(ours[k], list):
                if len(ov) != len(ours[k]):
                    diffs.append(f"{k}: length ours={len(ours[k])} oracle={len(ov)}")
                else:
                    for i, (a, b) in enumerate(zip(ours[k], ov)):
                        for d in _compare_return(a, b):
                            diffs.append(f"{k}[{i}].{d}")
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
    o = MCPOracle("conf_prb_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_prb_reads")
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
def test_problem_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_problem_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
