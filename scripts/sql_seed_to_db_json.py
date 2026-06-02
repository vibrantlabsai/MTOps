"""Port an INSERT-only ITSM seed `.sql` into a typed `db.json`.

The original EnterpriseOps seed files contain only INSERT statements (no DDL). We have the
authoritative schema in ``docs/itsm_schema.sql`` (dumped from the live MCP's SQLite). The
robust way to convert is to let SQLite itself parse everything: create a throwaway in-memory
DB, apply the DDL, replay the seed INSERTs, then export typed rows to JSON keyed by primary
key. This reuses SQLite's parser (handling quoting, ``datetime('...')`` calls, NULLs, etc.)
instead of a fragile hand-rolled SQL reader.

Usage:
    python scripts/sql_seed_to_db_json.py \
        --ddl docs/itsm_schema.sql \
        --seed "/path/to/db_xxx.sql" \
        --out data/itsm/seeds/seed_main.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


def _parse_pk_and_types(ddl_sql: str) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    """Return ({table: [pk_cols]}, {table: {col: declared_type}}) from CREATE TABLE statements."""
    pks: dict[str, list[str]] = {}
    types: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"CREATE TABLE\s+([a-zA-Z_]+)\s*\((.*?)\)\s*;", ddl_sql, re.S | re.I):
        table, body = m.group(1).lower(), m.group(2)
        col_types: dict[str, str] = {}
        pk_cols: list[str] = []
        # split on top-level commas
        depth, cur, parts = 0, "", []
        for ch in body:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur); cur = ""
            else:
                cur += ch
        if cur.strip():
            parts.append(cur)
        for part in parts:
            p = part.strip()
            up = p.upper()
            pk_inline = re.match(r"PRIMARY KEY\s*\(([^)]*)\)", p, re.I)
            if pk_inline:
                pk_cols = [c.strip().strip('"`') for c in pk_inline.group(1).split(",")]
                continue
            if up.startswith(("FOREIGN KEY", "PRIMARY KEY", "UNIQUE", "CONSTRAINT", "CHECK")):
                continue
            cm = re.match(r'["`]?([a-zA-Z_]+)["`]?\s+([A-Za-z]+)', p)
            if cm:
                col_types[cm.group(1)] = cm.group(2).upper()
                if "PRIMARY KEY" in up:
                    pk_cols = [cm.group(1)]
        pks[table] = pk_cols
        types[table] = col_types
    return pks, types


def _coerce(value, decl_type: str | None):
    if value is None:
        return None
    t = (decl_type or "").upper()
    if t.startswith("BOOL"):
        return bool(value)
    if t.startswith(("DATE", "TIME")):
        # Normalize SQLite "YYYY-MM-DD HH:MM:SS" to ISO-8601 "YYYY-MM-DDTHH:MM:SS"
        # to match the MCP's API serialization.
        return value.replace(" ", "T") if isinstance(value, str) else value
    if t.startswith(("INT", "NUMERIC", "REAL", "FLOAT", "DECIMAL")):
        # keep ints as ints, numerics as float only if fractional
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    return value if isinstance(value, str) else str(value)


def port(ddl_path: Path, seed_path: Path) -> dict[str, dict]:
    ddl_sql = ddl_path.read_text(encoding="utf-8")
    seed_sql = seed_path.read_text(encoding="utf-8")
    pks, types = _parse_pk_and_types(ddl_sql)

    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=OFF;")
    con.executescript(ddl_sql)
    con.executescript(seed_sql)
    con.row_factory = sqlite3.Row

    db: dict[str, dict] = {}
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for table in tables:
        coll: dict[str, dict] = {}
        col_types = types.get(table, {})
        pk_cols = pks.get(table) or []
        for row in con.execute(f"SELECT * FROM {table}"):
            rec = {k: _coerce(row[k], col_types.get(k)) for k in row.keys()}
            if len(pk_cols) == 1:
                key = str(rec[pk_cols[0]])
            elif pk_cols:
                key = ":".join(str(rec[c]) for c in pk_cols)
            else:  # no declared PK — fall back to row index
                key = str(len(coll))
            coll[key] = rec
        db[table] = coll
    con.close()
    return db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ddl", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    db = port(Path(args.ddl), Path(args.seed))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(db, indent=2, ensure_ascii=False), encoding="utf-8")

    total = sum(len(v) for v in db.values())
    print(f"wrote {out}  ({len(db)} tables, {total} records)")
    for t in sorted(db):
        print(f"  {t:28s} {len(db[t])}")


if __name__ == "__main__":
    main()
