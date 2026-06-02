"""Validate a ported task's gold actions against the ORIGINAL SQL verifiers.

A ported task's gold ``actions``, replayed on its seed (+ delta) via the real tools, must
produce a DB state satisfying the original benchmark's ``database_state`` verifiers. We check
that by materializing the in-memory ItsmDB into a throwaway SQLite (using the authoritative
DDL) and running each verifier's SQL exactly as the original benchmark did.

This is the objective gate for task porting (the analogue of diff_db for tools).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from eops_gym.domains.itsm.data_model import ItsmDB

_DDL = (Path(__file__).resolve().parents[1] / "docs" / "itsm_schema.sql").read_text()

# original seed .sql basename -> our ported seed name
SEED_FILE_MAP = {
    "db_1765301900121_3mwjj54xy.sql": "seed_main",
    "db_1765893060767_9rwtfbbp7.sql": "seed_alt",
}


def db_to_sqlite(db: ItsmDB) -> sqlite3.Connection:
    """Materialize an ItsmDB into an in-memory SQLite (schema from the authoritative DDL)."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=OFF;")
    con.executescript(_DDL)
    data = db.model_dump()
    for table, rows in data.items():
        for rec in rows.values():
            cols = list(rec.keys())
            con.execute(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [rec[c] for c in cols],
            )
    con.commit()
    return con


def _compare(actual, expected, comparison_type: str) -> bool:
    if comparison_type == "equals":
        return actual == expected or str(actual) == str(expected)
    if comparison_type == "greater_than":
        return actual is not None and actual > expected
    if comparison_type == "less_than":
        return actual is not None and actual < expected
    if comparison_type == "not_equals":
        return actual != expected
    return actual == expected


def check_verifiers(db: ItsmDB, verifiers: list[dict]) -> list[str]:
    """Run each database_state verifier against ``db``; return a list of failure strings ([] = all pass)."""
    con = db_to_sqlite(db)
    failures: list[str] = []
    for v in verifiers:
        if v.get("verifier_type") not in (None, "database_state"):
            continue  # only DB-state verifiers are checkable offline
        cfg = v.get("validation_config", v)
        query = cfg.get("query")
        expected = cfg.get("expected_value")
        comp = cfg.get("comparison_type", "equals")
        name = v.get("name", query)
        try:
            row = con.execute(query).fetchone()
            actual = row[0] if row else None
        except Exception as e:  # noqa: BLE001
            failures.append(f"[{name}] SQL error: {e}")
            continue
        if not _compare(actual, expected, comp):
            failures.append(f"[{name}] actual={actual!r} {comp} expected={expected!r} -> FAIL")
    con.close()
    return failures


if __name__ == "__main__":
    # Smoke test: verifiers should mostly FAIL on the raw seed (task not yet performed).
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    task_path = sys.argv[1]
    orig = json.load(open(task_path))
    seed_file = orig["gym_servers_config"][0]["seed_database_file"].split("/")[-1]
    seed = SEED_FILE_MAP[seed_file]
    db = ItsmDB.load(Path(__file__).resolve().parents[1] / "data" / "itsm" / "seeds" / f"{seed}.json")
    fails = check_verifiers(db, orig["verifiers"])
    print(f"seed={seed} verifiers={len(orig['verifiers'])} failing_on_raw_seed={len(fails)}")
    for f in fails:
        print("  ", f)
