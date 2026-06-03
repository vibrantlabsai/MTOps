"""Differential conformance: our in-memory service-offering tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_service_offerings_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.service_offerings import ServiceOfferingToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(ServiceOfferingToolsMixin):
    """Standalone toolkit exposing only the service-offering tools for conformance."""


# WRITE calls exercising register (defaults, full args, parent->business_service mapping, org
# scoping, id generation) and update (single field, parent+owner remap, short_description).
# Order matters (sequential id generation).
WRITE_SCENARIO = [
    ("register_new_service_offering", {"name": "Conf Offering A", "owned_by": "USER_002",
                                       "parent": "SVC_001", "short_description": "defaults only"}),
    ("register_new_service_offering", {"name": "Conf Offering B", "owned_by": "USER_008",
                                       "parent": "SVC_004", "short_description": "owner in org2",
                                       "used_for": "test", "status": "ready",
                                       "service_classification": "application",
                                       "business_criticality": "less-critical"}),
    ("register_new_service_offering", {"name": "Conf Offering C", "owned_by": "USER_005",
                                       "parent": "SVC_002", "short_description": "qa offering",
                                       "used_for": "QA", "status": "non-operational",
                                       "service_classification": "technology-management",
                                       "business_criticality": "somewhat-critical"}),
    ("update_service_offering", {"service_offering_id": "SVCOFF_001", "status": "ready"}),
    ("update_service_offering", {"service_offering_id": "SVCOFF_002", "parent": "SVC_003",
                                 "owned_by": "USER_006", "short_description": "remapped sd"}),
    ("update_service_offering", {"service_offering_id": "SVCOFF_004", "name": "Dev Server Access v2",
                                 "business_criticality": "critical"}),
]

# Read calls compared on return value (oracle may project/wrap; compare shared keys).
READ_SCENARIO = [
    ("find_service_offering_by_name", {"name": "Outlook Email Access"}),
    ("find_service_offerings", {}),
    ("find_service_offerings", {"status": "operational"}),
    ("find_service_offerings", {"name": "Email"}),
    ("find_service_offerings", {"parent": "SVC_001"}),
    ("find_service_offerings", {"short_description": "email"}),
    ("find_service_offerings", {"used_for": "development"}),
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
    """Compare returns on keys the oracle provides (it projects/wraps the records)."""
    ours = _normalize_return(ours)
    # find_service_offerings wraps the list as {"service_offerings": [...], "total_count": N}
    if isinstance(oracle, dict) and "service_offerings" in oracle and isinstance(ours, list):
        diffs: list[str] = []
        oracle_list = oracle["service_offerings"]
        if len(oracle_list) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle_list)}")
            return diffs
        ours_by_id = {r["service_offering_id"]: r for r in ours}
        for orow in oracle_list:
            sid = orow["service_offering_id"]
            if sid not in ours_by_id:
                diffs.append(f"missing offering {sid}")
                continue
            mine = ours_by_id[sid]
            for k, ov in orow.items():
                mk = "business_service" if k == "parent" else k
                if mk not in mine:
                    diffs.append(f"{sid}: missing key {mk}")
                elif str(mine[mk]) != str(ov):
                    diffs.append(f"{sid}.{k}: ours={mine[mk]!r} oracle={ov!r}")
        return diffs
    diffs = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            mk = "business_service" if k == "parent" else k
            if mk not in ours:
                diffs.append(f"missing key {mk}")
            elif str(ours[mk]) != str(ov) and not (
                isinstance(ov, (int, float)) and isinstance(ours[mk], (int, float))
                and float(ov) == float(ours[mk])
            ):
                diffs.append(f"{k}: ours={ours[mk]!r} oracle={ov!r}")
    elif isinstance(oracle, list) and isinstance(ours, list):
        if len(oracle) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle)}")
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_so_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_so_reads")
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
def test_service_offering_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_service_offering_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
