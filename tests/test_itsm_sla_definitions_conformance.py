"""Differential conformance: our in-memory SLA-definition tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_sla_definitions_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools._base import ItsmToolsBase
from eops_gym.domains.itsm.tools.sla_definitions import SLADefinitionToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(SLADefinitionToolsMixin, ItsmToolsBase):
    """Standalone toolkit exposing only the SLA-definition tools."""


# WRITE scenario exercising: create (defaults only / all fields), id generation (SLA_011..),
# update (multi-field change, rename to a fresh unique name). Order matters (sequential ids).
WRITE_SCENARIO = [
    ("add_new_sla_definition", {"name": "New Critical Response SLA", "metric": "response",
                                "target_mins": 30, "pause_on_pending": True, "active": True}),
    ("add_new_sla_definition", {"name": "New Resolution SLA", "metric": "resolution",
                                "target_mins": 300, "pause_on_pending": False, "active": False,
                                "applies_to_priority": "high", "schedule": "SCHED_A"}),
    ("add_new_sla_definition", {"name": "New Low Response SLA", "metric": "response",
                                "target_mins": 90, "pause_on_pending": True, "active": True,
                                "applies_to_priority": "low"}),
    ("update_sla_definition", {"sla_def_id": "SLA_001", "target_mins": 25, "active": False}),
    ("update_sla_definition", {"sla_def_id": "SLA_004", "name": "Renamed Moderate SLA",
                               "metric": "resolution", "applies_to_priority": "moderate"}),
    ("update_sla_definition", {"sla_def_id": "SLA_010", "pause_on_pending": False,
                               "schedule": "SCHED_B"}),
]

# Read calls compared on return value (oracle projects out org_id; compare shared keys).
READ_SCENARIO = [
    ("find_sla_definition_by_name", {"name": "Critical Response SLA"}),
    ("find_sla_definition_by_name", {"name": "Database Resolution SLA"}),
    ("find_sla_definitions", {}),
    ("find_sla_definitions", {"metric": "response"}),
    ("find_sla_definitions", {"active": True, "applies_to_priority": "low"}),
    ("find_sla_definitions", {"target_mins": 120}),
    ("find_sla_definitions", {"created_after": "2024-01-05T12:00:00"}),
    ("find_sla_definitions", {"created_before": "2024-01-05T10:00:00"}),
    ("find_sla_definitions", {"sla_def_id": "SLA_007"}),
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
    """Compare returns on keys the oracle provides (it may project out org_id)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        for k, ov in oracle.items():
            if k not in ours:
                diffs.append(f"missing key {k}")
            elif isinstance(ov, list) and isinstance(ours[k], list):
                if len(ov) != len(ours[k]):
                    diffs.append(f"{k}: length ours={len(ours[k])} oracle={len(ov)}")
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
    o = MCPOracle("conf_sla_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_sla_reads")
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
def test_sla_definition_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_sla_definition_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
