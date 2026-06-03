"""Integrated conformance: the REAL combined ItsmTools (all 93 tools) vs the live MCP oracle.

The per-category tests verify each mixin in isolation. This test verifies the COMBINED toolkit
-- catching any bug introduced when mixins share a method namespace (MRO helper collisions).
It replays each category's WRITE_SCENARIO through one ItsmTools and asserts DB parity.

Also asserts cross-category determinism (no random/clock leakage), which gold-action DB-hash
evaluation depends on. This test needs no oracle.
"""

from __future__ import annotations

import glob
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools import ItsmTools

SEED = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"
TESTDIR = Path(__file__).parent
# static_token is randomized by the MCP (Python secrets); we generate it deterministically, so
# it is irreducibly different vs the oracle and excluded from the integrated diff.
_IRREDUCIBLE = {"static_token"}


def _strip(db: dict) -> dict:
    for coll in db.values():
        for row in coll.values():
            for k in _IRREDUCIBLE:
                row.pop(k, None)
    return db


def _category_modules():
    mods = []
    for fp in sorted(glob.glob(str(TESTDIR / "test_itsm_*_conformance.py"))):
        stem = Path(fp).stem
        if stem == Path(__file__).stem or "integrated" in stem:
            continue
        m = importlib.import_module(stem)
        if hasattr(m, "WRITE_SCENARIO"):
            mods.append(stem.replace("test_itsm_", "").replace("_conformance", ""))
    return mods


def _module_for(cat: str):
    return importlib.import_module(f"test_itsm_{cat}_conformance")


def _run_ours(scenario):
    db = ItsmDB.model_validate(json.loads(SEED.read_text()))
    tools = ItsmTools(db, acting_user_id="USER_001")
    for name, args in scenario:
        try:
            tools.use_tool(name, **args)
        except Exception:
            pass  # divergence (if any) surfaces in the DB diff
    return db.model_dump()


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
@pytest.mark.parametrize("cat", _category_modules())
def test_integrated_category_conformance(cat):
    mod = _module_for(cat)
    scenario = list(getattr(mod, "WRITE_SCENARIO", []))
    if not scenario:
        pytest.skip(f"{cat}: no write scenario")
    ours = _run_ours(scenario)
    oracle = MCPOracle("integ_" + cat)
    for name, args in scenario:
        oracle.call(name, args)
    oracle_db = oracle.dump_db()
    diffs = diff_db(_strip(ours), _strip(oracle_db))
    assert not diffs, f"{cat}: {len(diffs)} divergences via combined ItsmTools:\n" + "\n".join(diffs[:25])


# Cross-category creation scenario exercising deterministic id/clock/token generation.
_DET_SCENARIO = [
    ("create_incident", {"caller_id": "USER_005", "short_description": "det"}),
    ("add_new_user", {"first_name": "Det", "last_name": "Erm", "email": "det.erm@techcorp.com",
                      "phone": "+1-415-555-0188", "role": "agent", "active": True}),
    ("add_location", {"name": "Det Site", "city": "Pune", "country": "India"}),
    ("register_configuration_item", {"name": "Det CI", "owner_id": "USER_005",
                                     "location_id": "LOC_001", "serial_number": "DET-SER-1",
                                     "status": "in_use", "cost": 100}),
    ("create_problem", {"problem_statement": "det problem", "status": "new", "impact": "low",
                        "urgency": "low", "priority": "planning"}),
    ("create_change", {"short_description": "det change", "status": "new", "impact": "low",
                       "risk": "low", "priority": "low"}),
    ("send_notification", {"incident_id": "INC_001", "email": "marcus.thompson@techcorp.com",
                           "type": "reminder"}),
]


def test_cross_category_determinism():
    def run():
        db = ItsmDB.model_validate(json.loads(SEED.read_text()))
        tools = ItsmTools(db, acting_user_id="USER_001")
        for name, args in _DET_SCENARIO:
            try:
                tools.use_tool(name, **args)
            except Exception:
                pass
        return db.get_hash()
    h1, h2 = run(), run()
    assert h1 == h2, "non-deterministic tool output breaks gold-action DB-hash evaluation"


if __name__ == "__main__":
    for cat in _category_modules():
        mod = _module_for(cat)
        scenario = list(getattr(mod, "WRITE_SCENARIO", []))
        if not scenario:
            print(f"{cat}: (no write scenario)"); continue
        ours = _run_ours(scenario)
        o = MCPOracle("integ_" + cat)
        for name, args in scenario:
            o.call(name, args)
        diffs = diff_db(_strip(ours), _strip(o.dump_db()))
        print(f"{cat}: {'OK' if not diffs else str(len(diffs)) + ' DIFFS'}")
        for d in diffs[:10]:
            print("   ", d)
