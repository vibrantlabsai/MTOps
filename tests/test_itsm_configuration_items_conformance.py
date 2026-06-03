"""Differential conformance: our in-memory configuration-item tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_configuration_items_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.configuration_items import ConfigurationItemToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(ConfigurationItemToolsMixin):
    """Standalone toolkit exposing only the configuration-item tools under test."""


# WRITE calls exercising register (defaults, FKs, id/org), update (mutate, idempotency guard,
# status-always-applies, serial-uniqueness, location FK). Order matters (sequential id gen).
WRITE_SCENARIO = [
    ("register_configuration_item", {"name": "Probe Laptop", "owner_id": "USER_002",
                                     "location_id": "LOC_001", "serial_number": "PROBE-001",
                                     "status": "in_use", "cost": 999.5}),
    ("register_configuration_item", {"name": "Probe Server", "owner_id": "USER_007",
                                     "location_id": "LOC_003", "serial_number": "PROBE-002",
                                     "status": "in_stock", "cost": 4200}),
    ("update_configuration_item", {"configuration_item_id": "CI_002", "cost": 850,
                                   "status": "maintenance"}),
    ("update_configuration_item", {"configuration_item_id": "CI_001", "owner_id": "USER_005",
                                   "location_id": "LOC_002"}),
    ("update_configuration_item", {"configuration_item_id": "CI_003", "status": "retired"}),
    ("update_configuration_item", {"configuration_item_id": "CI_004",
                                   "serial_number": "SERVER-SF-NEW"}),
]


def _read_ids(result):
    if isinstance(result, dict) and "configuration_items" in result:
        return [c["configuration_item_id"] for c in result["configuration_items"]]
    return None


READ_SCENARIO = [
    ("find_configuration_item_by_serial_number", {"serial_number": "WS-SF-001"}),
    ("find_configuration_items", {}),
    ("find_configuration_items", {"status": "in_use"}),
    ("find_configuration_items", {"owner_id": "USER_003"}),
    ("find_configuration_items", {"cost": 1200}),
    ("find_configuration_items", {"created_after": "2024-01-10T11:00:00"}),
    ("find_configuration_items", {"created_before": "2024-01-10T12:00:00"}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    returns = []
    for tool, args in scenario:
        returns.append(tools.use_tool(tool, **args))
    return db.model_dump(), returns


def _normalize_return(val):
    """Make a tool return comparable: pydantic -> dict, dict/list -> recursively normalized."""
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_return(v) for k, v in val.items()}
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out some columns)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        # The find_configuration_items list payload: compare ordering + shared keys per row.
        if "configuration_items" in oracle and "configuration_items" in ours:
            o_list, u_list = oracle["configuration_items"], ours["configuration_items"]
            if [r["configuration_item_id"] for r in o_list] != \
                    [r["configuration_item_id"] for r in u_list]:
                diffs.append(f"order/contents ours={_read_ids(ours)} oracle={_read_ids(oracle)}")
            if oracle.get("total_count") != ours.get("total_count"):
                diffs.append(
                    f"total_count ours={ours.get('total_count')} "
                    f"oracle={oracle.get('total_count')}"
                )
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
    o = MCPOracle("conf_ci_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_ci_reads")
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
def test_configuration_item_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_configuration_item_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
