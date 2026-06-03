"""Differential conformance: our in-memory group tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_groups_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.groups import GroupToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(GroupToolsMixin):
    """Standalone toolkit exposing only the group tools for conformance."""


# WRITE scenario exercising every write tool: group create (defaults + full), update
# (single field + multi field), member add, and the two membership-removal paths
# (by group+user, and by explicit member_id). Order matters (sequential id generation).
WRITE_SCENARIO = [
    ("add_new_user_group", {"name": "Conformance Group A", "type": "IT Support",
                            "manager_id": "USER_002"}),
    ("add_new_user_group", {"name": "Conformance Group B", "type": "Service Desk",
                            "manager_id": "USER_002", "active": False,
                            "email": "confb@techcorp.com", "description": "second group"}),
    ("update_user_group", {"group_id": "GROUP_001", "name": "Level 1 Support (Renamed)"}),
    ("update_user_group", {"group_id": "GROUP_002", "type": "Field Support Technicians",
                           "active": False}),
    ("add_new_group_member", {"group_id": "GROUP_001", "user_id": "USER_005"}),
    ("add_new_group_member", {"group_id": "GROUP_002", "user_id": "USER_003"}),
    ("remove_group_membership", {"group_id": "GROUP_001", "user_id": "USER_004"}),
    ("remove_group_membership", {"group_id": "GROUP_002", "user_id": "USER_006",
                                 "member_id": "MEMBER_003"}),
]

# Read calls compared on return value.
READ_SCENARIO = [
    ("find_group_by_name", {"name": "Level 1 Support Team"}),
    ("list_user_groups", {}),
    ("list_user_groups", {"type": "IT Support"}),
    ("list_user_groups", {"name": "Support"}),
    ("list_user_groups", {"active": True}),
    ("list_user_groups", {"group_id": "GROUP_002"}),
    ("list_group_members", {}),
    ("list_group_members", {"group_id": "GROUP_001"}),
    ("list_group_members", {"user_id": "USER_003"}),
    ("list_group_members", {"member_id": "MEMBER_002"}),
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
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out some fields)."""
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
    o = MCPOracle("conf_grp_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_grp_reads")
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
def test_group_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_group_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
