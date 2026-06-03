"""Differential conformance: our in-memory service tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_services_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.services import ServiceToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(ServiceToolsMixin):
    """Standalone toolkit exposing only the service tools for conformance."""


# WRITE scenario exercising add (defaults, full args, cross-org owner -> acting org, id gen) and
# update (single field, multi field). Order matters (sequential SVC id generation).
WRITE_SCENARIO = [
    # defaults only -> used_for=production, status=operational, classification=business,
    # criticality=critical, description=NULL; org_id from acting user (ORG_001).
    ("add_new_service", {"name": "Backup Service", "owned_by": "USER_003"}),
    # full args.
    ("add_new_service", {"name": "QA Sandbox", "owned_by": "USER_004", "used_for": "QA",
                         "status": "ready", "service_classification": "application",
                         "business_criticality": "less-critical", "description": "qa env"}),
    # owner in ORG_002 -> stored org_id must still be the acting user's org (ORG_001).
    ("add_new_service", {"name": "Cross Org Service", "owned_by": "USER_007"}),
    # update a single field.
    ("update_service", {"service_id": "SVC_001", "status": "non-operational"}),
    # update multiple fields incl. owner + a real name change.
    ("update_service", {"service_id": "SVC_002", "name": "Customer Portal v2",
                        "owned_by": "USER_003", "used_for": "QA",
                        "service_classification": "application",
                        "business_criticality": "less-critical", "description": "revised"}),
    # update a freshly-created service (validates ids stayed in lockstep).
    ("update_service", {"service_id": "SVC_005", "status": "retired"}),
]

# Read calls compared on return value (oracle projects out org_id/description).
READ_SCENARIO = [
    ("find_service_by_name", {"name": "Email Service"}),
    ("find_services", {}),
    ("find_services", {"name": "email"}),
    ("find_services", {"used_for": "production"}),
    ("find_services", {"status": "operational", "service_classification": "technology-management"}),
    ("find_services", {"owned_by": "USER_001"}),
    ("find_services", {"service_id": "SVC_002"}),
    ("find_services", {"created_before": "2024-01-08T10:00:00"}),
    ("find_services", {"created_after": "2024-01-08T10:00:00"}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    returns = []
    for tool, args in scenario:
        returns.append(tools.use_tool(tool, **args))
    return db.model_dump(), returns


def _normalize_return(val):
    """Make a tool return comparable: pydantic -> dict; recurse into lists and dicts."""
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_return(v) for k, v in val.items()}
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out org_id/description)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
                continue
            if isinstance(ov, list) and isinstance(ours[k], list):
                if len(ov) != len(ours[k]):
                    diffs.append(f"{k}: length ours={len(ours[k])} oracle={len(ov)}")
                else:
                    for i, (a, b) in enumerate(zip(ours[k], ov)):
                        diffs.extend(f"[{i}].{d}" for d in _compare_return(a, b))
            elif str(ours[k]) != str(ov) and not (
                isinstance(ov, (int, float)) and isinstance(ours[k], (int, float))
                and float(ov) == float(ours[k])
            ):
                diffs.append(f"{k}: ours={ours[k]!r} oracle={ov!r}")
    elif isinstance(oracle, list) and isinstance(ours, list):
        if len(oracle) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle)}")
        else:
            for i, (a, b) in enumerate(zip(ours, oracle)):
                diffs.extend(f"[{i}].{d}" for d in _compare_return(a, b))
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario.
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_svc_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable).
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_svc_reads")
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
def test_service_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_service_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
