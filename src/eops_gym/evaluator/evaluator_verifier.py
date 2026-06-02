"""Verifier-based scoring — the original EnterpriseOps benchmark's method.

Each task may carry ``database_state`` verifiers (``{query, expected_value, comparison_type}``)
copied from the original benchmark. We materialize the final in-memory DB into a throwaway
SQLite (schema inferred from the pydantic models, so this is domain-agnostic) and run each
verifier's SQL exactly as the original did. This yields results directly comparable to the
original leaderboard, and is more faithful than gold-action full-DB-hash matching (which also
penalizes fields the task never required).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Optional, Union, get_args, get_origin

from pydantic import BaseModel

from eops_gym.environment.db import DB


def _sqlite_affinity(annotation: Any) -> str:
    """Map a pydantic field annotation to a SQLite column affinity (for correct comparisons)."""
    if get_origin(annotation) is Union:  # unwrap Optional[X]
        args = [a for a in get_args(annotation) if a is not type(None)]
        annotation = args[0] if args else str
    if annotation is bool:
        return "INTEGER"
    if annotation is int:
        return "INTEGER"
    if annotation is float:
        return "REAL"
    return "TEXT"


def _record_model(collection_annotation: Any) -> Optional[type[BaseModel]]:
    """Extract the record model from a ``Dict[str, RecordModel]`` collection annotation."""
    args = get_args(collection_annotation)
    if len(args) == 2 and isinstance(args[1], type) and issubclass(args[1], BaseModel):
        return args[1]
    return None


def db_to_sqlite(db: DB) -> sqlite3.Connection:
    """Materialize a domain DB into an in-memory SQLite with type-appropriate affinities."""
    con = sqlite3.connect(":memory:")
    for coll_name, field in type(db).model_fields.items():
        rec_model = _record_model(field.annotation)
        if rec_model is None:
            continue
        cols = {fn: _sqlite_affinity(f.annotation) for fn, f in rec_model.model_fields.items()}
        con.execute(f"CREATE TABLE {coll_name} ({', '.join(f'{c} {t}' for c, t in cols.items())})")
        for rec in getattr(db, coll_name).values():
            d = rec.model_dump()
            con.execute(
                f"INSERT INTO {coll_name} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
                list(d.values()),
            )
    con.commit()
    return con


def _compare(actual: Any, expected: Any, comparison_type: str) -> bool:
    if comparison_type == "greater_than":
        return actual is not None and actual > expected
    if comparison_type == "less_than":
        return actual is not None and actual < expected
    if comparison_type == "not_equals":
        return actual != expected and str(actual) != str(expected)
    return actual == expected or str(actual) == str(expected)  # equals (default)


class VerifierResult(BaseModel):
    name: str
    passed: bool
    detail: Optional[str] = None


class VerifierCheck(BaseModel):
    checks: list[VerifierResult]
    all_passed: bool
    pass_rate: float  # fraction of verifiers that passed (the original's "verifier pass rate")
    reward: float  # 1.0 iff all verifiers passed, else 0.0 (the original's task success)


def run_verifiers(db: DB, verifiers: list[dict]) -> VerifierCheck:
    """Run the database_state verifiers against ``db`` and return a VerifierCheck."""
    checkable = [v for v in verifiers if v.get("verifier_type", "database_state") == "database_state"]
    con = db_to_sqlite(db)
    results: list[VerifierResult] = []
    for v in checkable:
        cfg = v.get("validation_config", v)
        name = v.get("name") or cfg.get("query", "")[:40]
        try:
            row = con.execute(cfg["query"]).fetchone()
            actual = row[0] if row else None
            passed = _compare(actual, cfg.get("expected_value"), cfg.get("comparison_type", "equals"))
            results.append(VerifierResult(name=name, passed=passed,
                                          detail=None if passed else f"actual={actual!r}"))
        except Exception as e:  # noqa: BLE001
            results.append(VerifierResult(name=name, passed=False, detail=f"SQL error: {e}"))
    con.close()

    total = len(results)
    n_pass = sum(r.passed for r in results)
    all_passed = total > 0 and n_pass == total
    return VerifierCheck(
        checks=results,
        all_passed=all_passed,
        pass_rate=(n_pass / total) if total else 0.0,
        reward=1.0 if all_passed else 0.0,
    )
