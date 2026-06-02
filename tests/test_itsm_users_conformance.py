"""Differential conformance: our in-memory user tools vs the live ITSM MCP oracle.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

NOTE on ``static_token``: ``add_new_user`` mints a random ``token_<urlsafe>`` token in the
oracle (Python ``secrets``), so that single column can never reach byte parity. ``diff_db``
and the harness are left untouched; the strict assertion below verifies that the ONLY
remaining divergence after our scenario is the ``static_token`` of newly-created users — every
other column of every row must match byte-for-byte. Any non-static_token diff fails the test.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_users_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.users import UserToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / "seed_main.json"


class T(UserToolsMixin):
    """Standalone user toolkit for conformance testing."""


# WRITE scenario: exercises add_new_user (defaults, user_name-ignored, location_id, org-scoped
# email, sequential USER_ id) and update_user_details (multi-field, name change without
# user_name regen, location_id-only change). Order matters (sequential id generation).
WRITE_SCENARIO = [
    ("add_new_user", {"first_name": "Gamma", "last_name": "Defaults",
                      "email": "gamma.defaults@techcorp.com", "phone": "+1-415-555-9101",
                      "role": "agent", "active": True}),
    ("add_new_user", {"first_name": "Custom", "last_name": "Login",
                      "email": "custom.login@techcorp.com", "phone": "+1-415-555-9102",
                      "role": "manager", "active": False, "user_name": "should.be.ignored",
                      "location_id": "LOC_002"}),
    ("add_new_user", {"first_name": "Iz", "last_name": "Clone",
                      "email": "isabella.rossi@acme.com", "phone": "+1-415-555-9103",
                      "role": "reporter", "active": True}),
    ("update_user_details", {"user_id": "USER_005", "email": "ben.new@techcorp.com",
                             "role": "manager"}),
    ("update_user_details", {"user_id": "USER_006", "first_name": "Zed", "last_name": "Quux"}),
    ("update_user_details", {"user_id": "USER_004", "active": False, "location_id": "LOC_002"}),
    ("update_user_details", {"user_id": "USER_003", "phone": "+1-415-555-0199"}),
]

# Read calls compared on return value (oracle projects out static_token / extra fields).
READ_SCENARIO = [
    ("get_user", {"user_id": "USER_007"}),
    ("get_user_using_email", {"email": "carlos.rodriguez@techcorp.com"}),
    ("get_user_using_name", {"first_name": "carlos", "last_name": "RODRIGUEZ"}),
    ("list_users", {}),
    ("list_users", {"role": "agent"}),
    ("list_users", {"first_name": "ar"}),
    ("list_users", {"active": "true"}),
    ("list_users", {"created_after": "2024-01-17T11:00:00"}),
    ("list_users", {"created_before": "2024-01-17T11:00:00"}),
    ("list_users", {"phone": "+1-415-555-0103"}),
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
    """Compare returns on keys the oracle provides (it projects out some fields)."""
    ours = _normalize_return(ours)
    diffs: list[str] = []
    if isinstance(oracle, dict) and isinstance(ours, dict):
        # list_users returns {"users": [...], "total_count": N}
        if "users" in oracle and "users" in ours:
            if oracle.get("total_count") != ours.get("total_count"):
                diffs.append(f"total_count: ours={ours.get('total_count')} "
                             f"oracle={oracle.get('total_count')}")
            ou = {u["user_id"]: u for u in oracle["users"]}
            uu = {u["user_id"]: u for u in ours["users"]}
            if set(ou) != set(uu):
                diffs.append(f"user ids: ours={sorted(uu)} oracle={sorted(ou)}")
            for uid in sorted(set(ou) & set(uu)):
                diffs += [f"{uid}.{d}" for d in _compare_return(uu[uid], ou[uid])]
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


# Columns known to be irreducibly non-deterministic in the oracle (random secrets).
_NONDET_COLS = {"static_token"}


def _filter_nondet(diffs: list[str]) -> list[str]:
    """Drop the documented static_token-only divergences for newly-created users.

    diff_db itself is untouched; this only classifies its output. A diff line looks like
    ``users/USER_011.static_token: ours=... oracle=...`` — we keep everything that is not a
    pure static_token column diff so any real divergence still fails the test.
    """
    kept = []
    for d in diffs:
        col = d.split(".", 1)[1].split(":", 1)[0] if "." in d else ""
        if col in _NONDET_COLS:
            continue
        kept.append(d)
    return kept


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_user_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    raw_diffs = diff_db(ours_db, oracle_db)
    db_diffs = _filter_nondet(raw_diffs)
    nondet_diffs = [d for d in raw_diffs if d not in db_diffs]

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_user_reads")
    for tool, args in READ_SCENARIO:
        ours_r = tools.use_tool(tool, **args)
        oracle_r = o2.call(tool, args)
        d = _compare_return(ours_r, oracle_r)
        if d:
            read_diffs.append(f"{tool}{args}: {d}")
    o2._delete()

    if verbose:
        print(f"\n=== DB-state diffs ({len(db_diffs)}) [non-static_token] ===")
        for d in db_diffs[:60]:
            print("  ", d)
        print(f"\n=== known non-deterministic diffs ({len(nondet_diffs)}) [static_token] ===")
        for d in nondet_diffs[:60]:
            print("  ", d)
        print(f"\n=== read-return diffs ({len(read_diffs)}) ===")
        for d in read_diffs[:30]:
            print("  ", d)
    return db_diffs, read_diffs


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_user_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_user_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
