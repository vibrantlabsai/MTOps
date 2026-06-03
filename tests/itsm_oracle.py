"""Differential-testing oracle: talk to the live ITSM MCP and snapshot its DB.

Used to verify our in-memory reimplementation matches the original ServiceNow MCP server
(the ground truth). Requires the Docker container ``eops-itsm`` running on :8016 (see
``docs/itsm_build_spec.md``). Tests that use this are skipped when the oracle is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ORACLE_BASE = "http://localhost:8016"
CONTAINER = "eops-itsm"
CANONICAL_SEED = (
    "/Users/ankitsridhar/Desktop/hobby/EnterpriseOps-Gym/"
    "Domain Wise DBs and Task-DB Mappings/itsm/dbs/db_1765301900121_3mwjj54xy.sql"
)
ADMIN_TOKEN = "admin_token_marcus_2024_secure"

# Volatile columns to ignore when diffing DB state (oracle uses wall-clock; we use a frozen clock).
TIMESTAMP_COLS = {
    "created_at", "updated_at", "created_on", "updated_on", "resolved",
    "start_time", "breach_time", "completed_time", "sent_on", "paused_at",
}


def oracle_available() -> bool:
    try:
        with urllib.request.urlopen(ORACLE_BASE + "/", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


class MCPOracle:
    """Thin client over the MCP server: seed a DB, call tools, snapshot the SQLite."""

    def __init__(self, database_id: str, seed_path: str = CANONICAL_SEED, token: str = ADMIN_TOKEN):
        # Unique suffix: the server's delete API is unsupported, so reusing an id re-seeds to a
        # no-op. A fresh id per instance guarantees a clean, isolated database.
        self.database_id = f"{database_id}_{uuid.uuid4().hex[:8]}"
        self.token = token
        self._sid: str | None = None
        self._seed(seed_path)
        self._handshake()

    # -- setup ---------------------------------------------------------------
    def _seed(self, seed_path: str) -> None:
        sql = Path(seed_path).read_text(encoding="utf-8")
        self._delete()  # idempotent
        body = json.dumps({
            "database_id": self.database_id, "name": "conf", "description": "conf",
            "sql_content": sql,
        }).encode()
        req = urllib.request.Request(ORACLE_BASE + "/api/seed-database", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=180).read()

    def _delete(self) -> None:
        try:
            body = json.dumps({"database_id": self.database_id}).encode()
            req = urllib.request.Request(ORACLE_BASE + "/api/delete-database", data=body,
                                         headers={"Content-Type": "application/json"}, method="DELETE")
            urllib.request.urlopen(req, timeout=30).read()
        except Exception:
            pass

    def _rpc(self, method: str, params: dict, notify: bool = False):
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            payload["id"] = 1
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "x-database-id": self.database_id,
            "x-itsm-user-token": self.token,
        }
        if self._sid:
            headers["mcp-session-id"] = self._sid
        req = urllib.request.Request(ORACLE_BASE + "/mcp", data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=60)
        if resp.headers.get("mcp-session-id"):
            self._sid = resp.headers["mcp-session-id"]
        raw = resp.read().decode()
        out = None
        if "data:" in raw:
            for line in raw.splitlines():
                if line.startswith("data:"):
                    try:
                        out = json.loads(line[5:].strip())
                    except Exception:
                        pass
        else:
            try:
                out = json.loads(raw)
            except Exception:
                out = {"raw": raw}
        return out

    def _handshake(self) -> None:
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                 "clientInfo": {"name": "conf", "version": "1"}})
        self._rpc("notifications/initialized", {}, notify=True)

    # -- calls ---------------------------------------------------------------
    def call(self, tool: str, args: dict):
        """Call a tool; return the parsed result payload (dict/list) or an error dict."""
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        try:
            content = res["result"]["content"][0]["text"]
            try:
                return json.loads(content)
            except Exception:
                return content
        except Exception:
            return res

    # Reads the SQLite through a fresh in-container connection so committed WAL writes are
    # visible (copying just the .sqlite file out misses the -wal and is timing-flaky).
    _DUMP_SCRIPT = """
import sqlite3, json
con = sqlite3.connect("__DBPATH__")
con.row_factory = sqlite3.Row
out = {}
for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    info = con.execute("PRAGMA table_info(" + t + ")").fetchall()
    pk = [c[1] for c in sorted(info, key=lambda c: c[5]) if c[5] > 0]
    coll = {}
    for row in con.execute("SELECT * FROM " + t):
        rec = {k: row[k] for k in row.keys()}
        key = ":".join(str(rec[c]) for c in pk) if pk else str(len(coll))
        coll[key] = rec
    out[t] = coll
print(json.dumps(out, default=str))
"""

    def dump_db(self) -> dict:
        """Snapshot the server's SQLite as {table: {pk: row}} (WAL-safe, in-container read)."""
        path = f"/app/mcp_databases/itsm_{self.database_id}.sqlite"
        script = self._DUMP_SCRIPT.replace("__DBPATH__", path)
        r = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "python3", "-"],
            input=script, capture_output=True, text=True, check=True,
        )
        return json.loads(r.stdout)


def strip_volatile(db: dict) -> dict:
    """Drop timestamp columns so DB snapshots can be compared semantically."""
    return {
        t: {k: {c: v for c, v in row.items() if c not in TIMESTAMP_COLS} for k, row in coll.items()}
        for t, coll in db.items()
    }


def diff_db(ours: dict, oracle: dict) -> list[str]:
    """Return human-readable differences between two DB snapshots (volatile cols stripped)."""
    a, b = strip_volatile(ours), strip_volatile(oracle)
    diffs: list[str] = []
    for table in sorted(set(a) | set(b)):
        ra, rb = a.get(table, {}), b.get(table, {})
        for key in sorted(set(ra) | set(rb)):
            if key not in ra:
                diffs.append(f"{table}/{key}: missing in OURS")
            elif key not in rb:
                diffs.append(f"{table}/{key}: extra in OURS")
            else:
                for col in sorted(set(ra[key]) | set(rb[key])):
                    va, vb = ra[key].get(col), rb[key].get(col)
                    # numeric tolerance (1200 vs 1200.0)
                    if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                        if float(va) == float(vb):
                            continue
                    if str(va) != str(vb):
                        diffs.append(f"{table}/{key}.{col}: ours={va!r} oracle={vb!r}")
    return diffs
