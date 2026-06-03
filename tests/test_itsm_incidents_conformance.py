"""Differential conformance: our in-memory incident tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_incidents_conformance.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import CANONICAL_SEED, MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools import ItsmTools

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"

# A scenario of WRITE calls exercising create (defaults, channel->contact_type, FKs, id/number),
# update, and the child-incident relationship tools. Order matters (sequential id generation).
WRITE_SCENARIO = [
    ("create_incident", {"caller_id": "USER_002", "short_description": "gamma defaults only"}),
    ("create_incident", {"caller_id": "USER_005", "short_description": "alpha",
                          "impact": "medium", "urgency": "low"}),
    ("create_incident", {"caller_id": "USER_004", "short_description": "beta",
                          "channel": "self-service", "assigned_to": "USER_003",
                          "assignment_group": "GROUP_001", "configuration_item": "CI_001",
                          "status": "in_progress", "priority": "high", "category": "hardware"}),
    ("update_incident", {"incident_id": "INC_003", "priority": "high", "assigned_to": "USER_003",
                         "status": "in_progress"}),
    ("add_child_incident", {"parent_incident": "INC_001", "child_incident": "INC_002"}),
    ("add_child_incidents", {"parent_incident": "INC_003",
                             "child_incidents": ["INC_007", "INC_008"]}),
    ("remove_child_incident", {"parent_incident": "INC_006", "child_incident": "INC_001"}),
    ("update_child_incident", {"child_incident_mapping_id": "CINC_002",
                               "parent_incident": "INC_006", "child_incident": "INC_009"}),
]

# Read calls compared on return value (oracle may project out org_id/_display; compare shared keys).
READ_SCENARIO = [
    ("find_incident_by_id", {"incident_id": "INC_010"}),
    ("find_incident_by_number", {"number": "INC0000003"}),
    ("get_count_of_incident_priority_wise", {"priority_list": ["high", "moderate", "critical"]}),
    ("count_incident_for_assignment_group", {"assignment_group_id": "GROUP_001"}),
    ("get_incidents_assigned_to", {"assigned_to": "USER_003"}),
    ("list_incidents", {"status": "new"}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = ItsmTools(db, acting_user_id="USER_001")
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


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out org_id/_display)."""
    ours = _normalize_return(ours)
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
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_inc_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = ItsmTools(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_inc_reads")
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
def test_incident_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_incident_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
