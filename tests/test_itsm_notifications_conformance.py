"""Differential conformance: our in-memory notification tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_notifications_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.notifications import NotificationToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(NotificationToolsMixin):
    """Standalone notification toolkit (the metaclass collects the mixin's @is_tool methods)."""


# WRITE calls exercising send (defaults + full + cross-org incident/email), update (partial,
# multi-field, cross-org notif), and delete (the unwired no-op error). Order matters because ids
# are generated sequentially. The acting user is USER_001 (marcus.thompson@techcorp.com); never
# send to that email (the oracle rejects self-sends).
WRITE_SCENARIO = [
    # send: minimal -> type='other', status='queued', subject/message NULL, NOTIF_008
    ("send_notification", {"incident_id": "INC_001", "email": "benjamin.chen@techcorp.com"}),
    # send: every field supplied -> NOTIF_009
    ("send_notification", {"incident_id": "INC_002", "email": "priya.sharma@techcorp.com",
                           "type": "update", "status": "sent", "subject": "Subj here",
                           "message": "Body here"}),
    # send: cross-org incident (INC_013 is ORG_002) + cross-org recipient email -> NOTIF_010,
    # org_id stays the acting user's ORG_001
    ("send_notification", {"incident_id": "INC_013", "email": "isabella.rossi@acme.com",
                           "type": "alert"}),
    # update: partial (status + subject), keeps other fields
    ("update_notification", {"notification_id": "NOTIF_001", "status": "opened",
                             "subject": "New subject"}),
    # update: many fields incl. incident reassignment + recipient change
    ("update_notification", {"notification_id": "NOTIF_002", "incident_id": "INC_003",
                             "email": "carlos.rodriguez@techcorp.com", "type": "alert",
                             "message": "changed msg"}),
    # update: a notification owned by another org (NOTIF_005 is ORG_002); allowed, org_id unchanged
    ("update_notification", {"notification_id": "NOTIF_005", "status": "failed"}),
    # delete: unwired on the server -> error, no mutation
    ("delete_notifications", {"notification_id": "NOTIF_003"}),
]

# Read calls compared on return value (the oracle wraps lists as {'notifications', 'count'}).
READ_SCENARIO = [
    ("find_notifications", {}),
    ("find_notifications", {"incident_id": "INC_001"}),
    ("find_notifications", {"email": "benjamin.chen@techcorp.com"}),
    ("find_notifications", {"type": "alert"}),
    ("find_notifications", {"status": "delivered"}),
    ("find_notifications", {"notification_id": "NOTIF_003"}),
    ("find_notifications", {"created_after": "2024-02-18T00:00:00",
                            "created_before": "2024-02-19T00:00:00"}),
    ("find_notifications_for_email", {"email": "benjamin.chen@techcorp.com"}),
    ("find_notifications_sent_for_incident", {"incident_id": "INC_013"}),
]


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    returns = []
    for tool, args in scenario:
        try:
            returns.append(tools.use_tool(tool, **args))
        except Exception as exc:  # mirror the oracle: error tools don't mutate or abort
            returns.append({"error": str(exc)})
    return db.model_dump(), returns


def _normalize_return(val):
    """Make a tool return comparable: pydantic -> dict, wrap collections, recurse."""
    if hasattr(val, "model_dump"):
        return val.model_dump()
    if isinstance(val, list):
        return [_normalize_return(v) for v in val]
    if isinstance(val, dict):
        return {k: _normalize_return(v) for k, v in val.items()}
    return val


def _compare_return(ours, oracle) -> list[str]:
    """Compare returns on keys the oracle provides (it projects out some fields)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        # The notification finders return {'notifications': [...], 'count': N}; compare count
        # and the set of returned notification ids (order differs by oracle code path).
        if "count" in oracle:
            if oracle.get("count") != ours.get("count"):
                diffs.append(f"count: ours={ours.get('count')} oracle={oracle.get('count')}")
            o_ids = {n["notification_id"] for n in oracle.get("notifications", [])}
            ours_ids = {n["notification_id"] for n in ours.get("notifications", [])}
            if o_ids != ours_ids:
                diffs.append(f"ids: ours={sorted(ours_ids)} oracle={sorted(o_ids)}")
        else:
            for k, ov in oracle.items():
                if k not in ours:
                    diffs.append(f"missing key {k}")
                elif str(ours[k]) != str(ov):
                    diffs.append(f"{k}: ours={ours[k]!r} oracle={ov!r}")
    elif isinstance(oracle, list) and isinstance(ours, list):
        if len(oracle) != len(ours):
            diffs.append(f"length ours={len(ours)} oracle={len(oracle)}")
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_notif_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
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
def test_notification_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_notification_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
