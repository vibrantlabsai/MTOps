"""Differential conformance: our in-memory incident-template tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

The MCP nests the scalar template fields inside ``change_request_values`` on its read returns;
our flat ``IncidentTemplate`` model exposes them as top-level attributes. The read comparison
below flattens the oracle's nesting so the two representations are comparable on shared keys.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_incident_templates_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.incident_templates import IncidentTemplateToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / "seed_main.json"


class T(IncidentTemplateToolsMixin):
    """Standalone toolkit exposing only the incident-template tools for conformance."""


# WRITE scenario exercising: create (defaults only, full fields, active=false, ORG_002 caller,
# nullable fields populated) and update (name only, CRV scalar fields, null-clearing nullable
# fields, active toggle, mixed changed/unchanged). Order matters (sequential TMPL_ ids).
WRITE_SCENARIO = [
    # create: defaults only (impact/urgency low, priority planning, active true) -> TMPL_004
    ("create_new_incident_template", {
        "name": "Conf Defaults Only",
        "change_request_values": {"caller_id": "USER_002", "short_description": "defaults only"},
    }),
    # create: full field set + active=false + populated nullable FKs -> TMPL_005
    ("create_new_incident_template", {
        "name": "Conf Full Fields",
        "change_request_values": {
            "caller_id": "USER_003", "short_description": "full fields",
            "channel": "phone", "category": "software", "impact": "high",
            "urgency": "medium", "priority": "critical",
            "configuration_item": "CI_001", "service": "SVC_001",
            "service_offering": "SVCOFF_001",
        },
        "active": False,
    }),
    # create: caller from a different org (org_id still inherits acting user's ORG_001) -> TMPL_006
    ("create_new_incident_template", {
        "name": "Conf Cross Org Caller",
        "change_request_values": {"caller_id": "USER_007", "short_description": "cross org"},
    }),
    # update: top-level name only on a seed template
    ("update_incident_template", {
        "incident_template_id": "TMPL_001", "name": "Conf Renamed Reset",
    }),
    # update: change CRV scalar fields (impact/priority/channel)
    ("update_incident_template", {
        "incident_template_id": "TMPL_002",
        "change_request_values": {"impact": "high", "priority": "critical", "channel": "chat"},
    }),
    # update: clear a nullable field via explicit null
    ("update_incident_template", {
        "incident_template_id": "TMPL_002",
        "change_request_values": {"channel": None},
    }),
    # update: toggle active false
    ("update_incident_template", {
        "incident_template_id": "TMPL_003", "active": False,
    }),
    # update: mixed changed + unchanged (impact unchanged, configuration_item newly set)
    ("update_incident_template", {
        "incident_template_id": "TMPL_004",
        "change_request_values": {"impact": "low", "configuration_item": "CI_002",
                                  "service": "SVC_002", "service_offering": "SVCOFF_002",
                                  "category": "database"},
    }),
    # update: change caller_id + short_description together (both tracked, both changed)
    ("update_incident_template", {
        "incident_template_id": "TMPL_005",
        "change_request_values": {"caller_id": "USER_004",
                                  "short_description": "updated full fields"},
        "active": True,
    }),
]

# READ scenario compared on flattened shared keys (oracle nests scalars in change_request_values).
READ_SCENARIO = [
    ("get_incident_template_by_name", {"name": "Password Reset Template"}),
    ("get_incident_template_by_name", {"name": "Network Connectivity Issue"}),
    ("get_incident_templates", {}),
    ("get_incident_templates", {"active": True}),
    ("get_incident_templates", {"incident_template_id": "TMPL_002"}),
    ("get_incident_templates", {"name": "Software Installation Request"}),
    ("get_incident_templates", {"created_after": "2024-01-05T09:30:00"}),
    ("get_incident_templates", {"created_before": "2024-01-05T10:00:00"}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    returns = []
    for tool, args in scenario:
        returns.append(tools.use_tool(tool, **args))
    return db.model_dump(), returns


# scalar fields the oracle nests under change_request_values on its read returns.
_CRV_KEYS = {
    "caller_id", "short_description", "channel", "category",
    "impact", "urgency", "priority", "configuration_item", "service", "service_offering",
}


def _flatten_oracle(obj):
    """Flatten the oracle's nested change_request_values into a flat dict (our model shape)."""
    if not isinstance(obj, dict):
        return obj
    flat = dict(obj)
    crv = flat.pop("change_request_values", None)
    if isinstance(crv, dict):
        for k, v in crv.items():
            flat[k] = v
    return flat


def _normalize_return(val):
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    return val


def _compare_obj(ours: dict, oracle_flat: dict) -> list[str]:
    diffs: list[str] = []
    for k, ov in oracle_flat.items():
        if k not in ours:
            diffs.append(f"missing key {k}")
        elif str(ours[k]) != str(ov) and not (
            isinstance(ov, (int, float)) and isinstance(ours[k], (int, float))
            and float(ov) == float(ours[k])
        ):
            diffs.append(f"{k}: ours={ours[k]!r} oracle={ov!r}")
    return diffs


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns, accounting for the oracle's nested change_request_values + list wrapper."""
    ours = _normalize_return(ours)
    # list endpoints: oracle wraps in {"incident_templates": [...], "total_count": N}
    if isinstance(oracle, dict) and "incident_templates" in oracle:
        oracle_list = [_flatten_oracle(o) for o in oracle["incident_templates"]]
        if not isinstance(ours, list):
            return [f"shape: ours is not a list"]
        diffs: list[str] = []
        if len(ours) != len(oracle_list):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle_list)}")
            return diffs
        for i, (o_our, o_orc) in enumerate(zip(ours, oracle_list)):
            diffs += [f"[{i}] {d}" for d in _compare_obj(o_our, o_orc)]
        return diffs
    # single-object endpoints
    if isinstance(oracle, dict) and isinstance(ours, dict):
        return _compare_obj(ours, _flatten_oracle(oracle))
    return [f"shape mismatch ours={type(ours).__name__} oracle={type(oracle).__name__}"]


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_tmpl_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_tmpl_reads")
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
def test_incident_template_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_incident_template_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
