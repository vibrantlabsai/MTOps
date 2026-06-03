"""Differential conformance: our in-memory incident-knowledge link tools vs the live ITSM MCP.

Runs an identical scenario against both, then asserts the resulting DB state is identical
(volatile timestamps ignored). This is the primary correctness gate for the tool port.
Skipped automatically when the oracle container is not reachable.

Run directly for fast iteration:
    .venv/bin/python tests/test_itsm_incident_knowledges_conformance.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # for itsm_oracle
import pytest

from itsm_oracle import MCPOracle, diff_db, oracle_available

from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools.incident_knowledges import IncidentKnowledgeToolsMixin

SEED_JSON = Path(__file__).resolve().parents[1] / "data" / "itsm" / "db.json"


class T(IncidentKnowledgeToolsMixin):
    """Concrete toolkit exposing only the incident-knowledge link tools."""


# WRITE calls exercising link (default used_as, explicit used_as, org inherited from incident,
# ORG_002 incident), and remove (by incident_kb_id, by incident_id+knowledge_id, by
# incident_id+knowledge_id+used_as). Order matters (sequential IKB id generation).
WRITE_SCENARIO = [
    # link with used_as omitted -> defaults to 'suggested', org_id from incident (ORG_001) -> IKB_006
    ("link_knowledge_to_incident", {"incident_id": "INC_002", "knowledge_id": "KB_001"}),
    # link with explicit used_as -> IKB_007
    ("link_knowledge_to_incident", {"incident_id": "INC_003", "knowledge_id": "KB_002",
                                    "used_as": "applied"}),
    # link an ORG_002 incident -> org_id inherited from incident (ORG_002) -> IKB_008
    ("link_knowledge_to_incident", {"incident_id": "INC_009", "knowledge_id": "KB_004",
                                    "used_as": "resolution"}),
    # remove by incident_kb_id (seed row IKB_002)
    ("remove_knowledge_link_to_incident", {"incident_kb_id": "IKB_002"}),
    # remove by incident_id + knowledge_id (seed row IKB_003 = INC_002/KB_003)
    ("remove_knowledge_link_to_incident", {"incident_id": "INC_002", "knowledge_id": "KB_003"}),
    # remove by incident_id + knowledge_id + matching used_as (seed row IKB_004 = INC_013/KB_004 resolution)
    ("remove_knowledge_link_to_incident", {"incident_id": "INC_013", "knowledge_id": "KB_004",
                                           "used_as": "resolution"}),
    # remove a just-created link by incident_id + knowledge_id (IKB_007 = INC_003/KB_002)
    ("remove_knowledge_link_to_incident", {"incident_id": "INC_003", "knowledge_id": "KB_002"}),
]

# Read calls compared on return value (oracle projects out org_id; compare shared keys).
READ_SCENARIO = [
    ("find_incident_knowledge_links", {}),
    ("find_incident_knowledge_links", {"incident_id": "INC_001"}),
    ("find_incident_knowledge_links", {"knowledge_id": "KB_002"}),
    ("find_incident_knowledge_links", {"incident_kb_id": "IKB_003"}),
    ("find_incident_knowledge_links", {"used_as": "resolution"}),
    ("find_incident_knowledge_links", {"used_as": "suggested,resolution"}),
    ("find_incident_knowledge_links", {"used_as": "suggested, resolution"}),
    ("find_incident_knowledge_links", {"incident_id": "INC_013", "used_as": "suggested"}),
    ("find_incident_knowledge_links", {"incident_id": "INC_999"}),
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
    """Compare returns on keys the oracle provides (it projects out org_id)."""
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
        else:
            for i, (o_item, oc_item) in enumerate(zip(ours, oracle)):
                d = _compare_return(o_item, oc_item)
                if d:
                    diffs.append(f"[{i}]: {d}")
    return diffs


def run_all(verbose: bool = True):
    # DB-state conformance over the write scenario
    ours_db, _ = _run_ours(WRITE_SCENARIO)
    o = MCPOracle("conf_ikb_writes")
    for tool, args in WRITE_SCENARIO:
        o.call(tool, args)
    oracle_db = o.dump_db()
    o._delete()
    db_diffs = diff_db(ours_db, oracle_db)

    # Read-return conformance (fresh DB so ids are stable)
    read_diffs: list[str] = []
    db = ItsmDB.model_validate(json.loads(SEED_JSON.read_text()))
    tools = T(db, acting_user_id="USER_001")
    o2 = MCPOracle("conf_ikb_reads")
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
def test_incident_knowledge_db_state_matches_oracle():
    db_diffs, _ = run_all(verbose=False)
    assert not db_diffs, "DB-state divergences vs oracle:\n" + "\n".join(db_diffs[:40])


@pytest.mark.skipif(not oracle_available(), reason="ITSM MCP oracle not reachable on :8016")
def test_incident_knowledge_read_returns_match_oracle():
    _, read_diffs = run_all(verbose=False)
    assert not read_diffs, "read-return divergences vs oracle:\n" + "\n".join(read_diffs)


if __name__ == "__main__":
    db_diffs, read_diffs = run_all(verbose=True)
    print(f"\nRESULT: {len(db_diffs)} db diffs, {len(read_diffs)} read diffs")
    sys.exit(1 if (db_diffs or read_diffs) else 0)
