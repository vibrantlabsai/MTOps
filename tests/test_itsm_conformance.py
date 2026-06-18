"""Differential conformance: the ITSM port vs the live reference MCP (original ServiceNow server).

Each scenario runs an identical sequence of tool calls against BOTH our in-memory port and the
live reference, then asserts they agree. Docker-gated: the whole module is skipped when the
reference oracle is not reachable (see ``tests/itsm_oracle.py`` for connection env vars).

Two check modes:
  - ``outcome`` — the final call's success/error outcome must match (validation / edge paths).
  - ``state``   — the resulting DB state must be identical, volatile timestamps ignored
                  (happy paths; collection names already line up 1:1 between port and reference).

Scenarios marked ``xfail`` encode a CONFIRMED fidelity gap (see ``docs/itsm_fidelity_audit.md``)
that the port does not yet honour. They flip to ``xpass`` as the P1 fixes land, at which point the
marker is removed — so this file doubles as the executable spec / progress tracker for the fixes.

Run locally with the reference container up:
    uv run pytest tests/test_itsm_conformance.py -q -rxX
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
from itsm_oracle import MCPOracle, diff_db, oracle_available  # noqa: E402

from eops_gym.domains.itsm.data_model import ItsmDB  # noqa: E402
from eops_gym.domains.itsm.tools import ItsmTools  # noqa: E402

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"
ACTING_USER = "USER_001"  # marcus / ORG_001 admin — matches the oracle's ADMIN_TOKEN


@dataclass
class Scenario:
    """One differential check: the same ``calls`` run against port and reference."""

    id: str
    calls: list[tuple[str, dict]]
    mode: str = "outcome"  # "outcome" | "state"
    xfail: str | None = None  # confirmed-gap reference; None for scenarios that pass today
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- runners
def _run_port(calls: list[tuple[str, dict]]) -> tuple[list[bool], ItsmDB]:
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = ItsmTools(db, acting_user_id=ACTING_USER)
    outcomes: list[bool] = []
    for tool, args in calls:
        try:
            tools.use_tool(tool, **args)
            outcomes.append(True)
        except Exception:  # noqa: BLE001 - any raise is an error outcome
            outcomes.append(False)
    return outcomes, db


def _oracle_is_error(result: Any) -> bool:
    """The reference surfaces errors as a FastAPI/pydantic envelope; success is the record/list."""
    if isinstance(result, dict):
        if "detail" in result:  # pydantic 422 list or HTTPException dict
            return True
        if result.get("error") is True or "error_code" in result:
            return True
        if "error" in result and isinstance(result.get("error"), dict):  # JSON-RPC error
            return True
    return False


def _run_oracle(calls: list[tuple[str, dict]]) -> tuple[list[bool], MCPOracle]:
    o = MCPOracle("conformance")
    outcomes: list[bool] = []
    for tool, args in calls:
        outcomes.append(not _oracle_is_error(o.call(tool, args)))
    return outcomes, o


# ---------------------------------------------------------------------------- scenarios
SCENARIOS: list[Scenario] = [
    # -- positive: should agree TODAY (guards the harness + the success path) ------------
    Scenario("pos_find_incident", [("find_incident_by_id", {"incident_id": "INC_001"})]),
    Scenario(
        "pos_update_new_to_resolved",  # the calibration case: there is NO status state machine
        [("update_incident", {"incident_id": "INC_016", "status": "resolved"})],
    ),
    Scenario(
        "pos_create_incident_valid",
        [("create_incident", {"caller_id": "USER_002", "short_description": "harness sanity"})],
    ),

    # -- enum_validation (§4.1): FIXED — port now rejects invalid/wrong-case enums (guards regression)
    Scenario("enum_incident_priority",
             [("update_incident", {"incident_id": "INC_001", "priority": "urgent"})], tags=["enum"]),
    Scenario("enum_change_status",
             [("update_change", {"change_id": "CHG_001", "status": "in_progress"})], tags=["enum"]),
    Scenario("enum_notification_status",
             [("update_notification", {"notification_id": "NOTIF_001", "status": "open"})], tags=["enum"]),
    Scenario("enum_problem_status",
             [("update_problem", {"problem_id": "PRB_001", "status": "open"})], tags=["enum"]),
    Scenario("enum_ci_status",
             [("update_configuration_item", {"configuration_item_id": "CI_001", "status": "active"})],
             tags=["enum"]),
    Scenario("enum_user_role",
             [("update_user_details", {"user_id": "USER_003", "role": "superuser"})], tags=["enum"]),
    Scenario("enum_service_classification",
             [("update_service", {"service_id": "SVC_001", "service_classification": "infrastructure"})],
             tags=["enum"]),
    Scenario("enum_knowledge_state",
             [("update_knowledge_article", {"knowledge_id": "KB_001", "state": "active"})], tags=["enum"]),
    Scenario("enum_used_as",
             [("link_knowledge_to_incident",
               {"incident_id": "INC_002", "knowledge_id": "KB_001", "used_as": "primary"})],
             tags=["enum"]),

    # -- destructive-delete guards (§4.3): FIXED — no-filter delete now errors, leaves table intact
    Scenario("delete_slas_no_filter",
             [("delete_incident_slas", {})], tags=["delete"]),
    Scenario("remove_affected_ci_no_filter",
             [("remove_affected_ci_from_incident", {})], tags=["delete"]),

    # -- idempotency (§4.5): FIXED — a no-op update now errors instead of re-stamping updated_on ---
    Scenario("noop_update_notification",
             [("update_notification", {"notification_id": "NOTIF_001", "status": "delivered"})],
             tags=["idempotency"]),
    Scenario("noop_update_incident_sla_only_id",
             [("update_incident_sla_details", {"incident_sla_id": "TSLA_001"})],
             tags=["idempotency"]),

    # -- required-field guards (§4.4): FIXED ------------------------------------------------------
    Scenario("required_empty_start_time",
             [("link_new_incident_sla",
               {"incident_id": "INC_003", "sla_def_id": "SLA_002", "start_time": ""})],
             tags=["required"]),
    Scenario("required_update_kb_only_id",
             [("update_knowledge_article", {"knowledge_id": "KB_001"})], tags=["required"]),

    # -- duplicate detection (§4.2): FIXED -------------------------------------------------------
    Scenario("dup_change_number",
             [("update_change", {"change_id": "CHG_002", "number": "CHG0000001"})], tags=["duplicate"]),

    # -- FK coverage (§4.7): FIXED — update_incident validates all referenced entities ------------
    Scenario("fk_update_incident_service",
             [("update_incident", {"incident_id": "INC_001", "service": "SVC_GHOST"})], tags=["fk"]),

    # -- cross-entity rule (§4.7): FIXED — incident_template offering must belong to service ------
    Scenario("xentity_template_offering_service",
             [("update_incident_template",
               {"incident_template_id": "TMPL_001",
                "change_request_values": {"service": "SVC_001", "service_offering": "SVCOFF_002"}})],
             tags=["fk"]),

    # -- state parity (happy path): a real-change update must produce identical DB state ---------
    Scenario("state_update_incident_fields",
             [("update_incident",
               {"incident_id": "INC_001", "category": "hardware", "impact": "high"})],
             mode="state"),
]


def _param(s: Scenario):
    marks = [pytest.mark.xfail(reason=s.xfail, strict=False)] if s.xfail else []
    return pytest.param(s, id=s.id, marks=marks)


@pytest.mark.skipif(not oracle_available(), reason="reference MCP oracle not reachable")
@pytest.mark.parametrize("s", [_param(s) for s in SCENARIOS])
def test_conformance(s: Scenario):
    port_out, port_db = _run_port(s.calls)
    orc_out, orc = _run_oracle(s.calls)

    if s.mode == "outcome":
        p, o = port_out[-1], orc_out[-1]
        assert p == o, (
            f"outcome mismatch: port={'ok' if p else 'error'} reference={'ok' if o else 'error'}"
        )
    else:  # state
        assert all(port_out) and all(orc_out), (
            f"setup calls errored — port={port_out} reference={orc_out}"
        )
        diffs = diff_db(port_db.model_dump(), orc.dump_db())
        assert not diffs, "DB state diverges:\n" + "\n".join(diffs[:15])
