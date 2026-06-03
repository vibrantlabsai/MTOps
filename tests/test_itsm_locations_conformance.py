"""Differential conformance: our in-memory location tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_locations_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.locations import LocationToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(LocationToolsMixin):
    """Concrete toolkit exposing only the location tools for conformance testing."""


# WRITE calls exercising add (defaults, all-fields, org inheritance, id generation) and
# update (single field, active toggle, multi-field). Order matters (sequential id generation).
WRITE_SCENARIO = [
    ("add_location", {"name": "Austin Field Office", "city": "Austin", "country": "USA"}),
    ("add_location", {"name": "Denver Annex", "city": "Denver", "country": "USA",
                      "active": False, "plot_no": "42", "street": "Main St", "state": "CO"}),
    ("update_location", {"location_id": "LOC_001", "city": "Boston"}),
    ("update_location", {"location_id": "LOC_002", "active": False}),
    ("update_location", {"location_id": "LOC_003", "name": "Acme HQ West",
                         "street": "Mission St", "plot_no": "501"}),
    ("update_location", {"location_id": "LOC_004", "active": False, "state": "TX"}),
]

# Read calls compared on return value (oracle projects out nothing meaningful here).
READ_SCENARIO = [
    ("get_location_by_id", {"location_id": "LOC_002"}),
    ("find_location_by_given_name", {"name": "Acme Corp HQ"}),
    ("find_locations", {}),
    ("find_locations", {"country": "usa"}),
    ("find_locations", {"name": "Corp"}),
    ("find_locations", {"city": "London"}),
    ("find_locations", {"active": True}),
    ("find_locations", {"created_after": "2024-01-01T08:30:00"}),
    ("find_locations", {"created_before": "2024-01-01T09:00:00"}),
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
    """Compare returns on keys the oracle provides (it may project out some keys)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        # 'locations' list payloads: compare element-wise on shared keys.
        if "locations" in oracle and "locations" in ours:
            o_list, u_list = oracle["locations"], ours["locations"]
            if len(o_list) != len(u_list):
                diffs.append(f"locations length ours={len(u_list)} oracle={len(o_list)}")
            else:
                u_by_id = {l["location_id"]: l for l in u_list}
                for ol in o_list:
                    ul = u_by_id.get(ol["location_id"])
                    if ul is None:
                        diffs.append(f"missing location {ol['location_id']}")
                        continue
                    for k, ov in ol.items():
                        if k not in ul:
                            diffs.append(f"{ol['location_id']}: missing key {k}")
                        elif str(ul[k]) != str(ov):
                            diffs.append(f"{ol['location_id']}.{k}: ours={ul[k]!r} oracle={ov!r}")
            if "total_count" in oracle and oracle["total_count"] != ours.get("total_count"):
                diffs.append(f"total_count: ours={ours.get('total_count')} oracle={oracle['total_count']}")
            return diffs
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
    o = MCPOracle("conf_loc_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_loc_reads")
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
def test_location_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_location_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
