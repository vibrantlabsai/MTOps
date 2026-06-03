"""Differential conformance: our notification_analysis tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored) and that read returns match on shared keys. This is the primary
correctness gate for the tool port. Skipped automatically when the oracle is not reachable.

All four notification_analysis tools are read-only aggregates, so the WRITE scenario is empty
(DB state must be untouched) and the READ scenario carries the conformance signal.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_notification_analysis_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.notification_analysis import NotificationAnalysisToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(NotificationAnalysisToolsMixin):
    """Concrete toolkit exposing only the notification_analysis tools."""


# No write tools exist in this category; the DB must remain byte-for-byte unchanged.
WRITE_SCENARIO: list = []

# Read calls compared on return value. Cover every tool and every branch:
#   - count_by_incident: no-filter grouping, filter incl. a zero-notification incident.
#   - count_by_status / count_by_type: empty no-filter result, and the upper-cased 0-count
#     mismatch behaviour with a full enum filter.
#   - average: no-filter, filter with a zero-notification incident, single-incident filter.
READ_SCENARIO = [
    ("count_notifications_by_incident", {}),
    ("count_notifications_by_incident", {"incident_id": ["INC_001", "INC_013"]}),
    ("count_notifications_by_incident", {"incident_id": ["INC_001", "INC_005"]}),
    ("count_notifications_by_incident", {"incident_id": ["INC_005"]}),
    ("count_notifications_by_status", {}),
    ("count_notifications_by_status",
     {"status": ["queued", "sent", "delivered", "opened", "failed"]}),
    ("count_notifications_by_status", {"status": ["delivered"]}),
    ("count_notifications_by_type", {}),
    ("count_notifications_by_type",
     {"type": ["report", "update", "alert", "reminder", "solution_proposal", "other"]}),
    ("count_notifications_by_type", {"type": ["alert", "update"]}),
    ("average_notifications_by_incident", {}),
    ("average_notifications_by_incident", {"incident_id": ["INC_001", "INC_002"]}),
    ("average_notifications_by_incident", {"incident_id": ["INC_001", "INC_013"]}),
    ("average_notifications_by_incident", {"incident_id": ["INC_001", "INC_005"]}),
    ("average_notifications_by_incident", {"incident_id": ["INC_013"]}),
    ("average_notifications_by_incident", {"incident_id": ["INC_005"]}),
]


def _new_tools() -> T:
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    return T(db, acting_user_id="USER_001")


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
    # DB-state conformance: no writes here, so the DB must equal the oracle's seeded state.
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_notif_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so state is stable).
    read_diffs: list[str] = []
    tools = _new_tools()
    o2 = MCPOracle("conf_notif_reads")
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
def test_notification_analysis_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_notification_analysis_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
