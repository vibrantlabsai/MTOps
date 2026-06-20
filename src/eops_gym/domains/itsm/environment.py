"""ITSM environment + task loader factory."""

from pathlib import Path
from typing import Iterable, Optional

from eops_gym.data_model.tasks import Task
from eops_gym.domains.itsm.data_model import ItsmDB, slice_db_to_orgs
from eops_gym.domains.itsm.tools import ItsmTools
from eops_gym.environment.delta import Delta, apply_delta
from eops_gym.environment.environment import Environment
from eops_gym.utils.io_utils import load_file

_DATA_DIR = Path(__file__).resolve().parents[3].parent / "data" / "itsm"
ITSM_DB_PATH = _DATA_DIR / "db.json"
ITSM_POLICY_PATH = _DATA_DIR / "policy.md"
ITSM_TASKS_PATH = _DATA_DIR / "tasks.json"
ITSM_TASKS_DIR = _DATA_DIR / "tasks"

DOMAIN_NAME = "itsm"


def get_environment(
    db_delta: Optional[Delta | dict] = None,
    acting_user_id: Optional[str] = None,
    org_id: Optional[str] = None,
    org_ids: Optional[Iterable[str]] = None,
) -> Environment:
    """Build a fresh ITSM environment: load ``db.json`` and apply the task delta (item 7).

    ``acting_user_id`` is the authenticated caller from the task context. ``org_ids`` is the task's
    **tenancy scope** — the set of orgs its data lives in (a 1-element set for single-tenant, the
    ``{provider, client}`` pair for an MSP task). When given, the DB is sliced to that set (after the
    delta) so numbers/names that collide *outside* the scope resolve unambiguously. ``org_id`` is the
    legacy single-org alias (treated as a 1-element scope). Both ``None`` ⇒ no slice (multi-org).
    """
    db = ItsmDB.load(ITSM_DB_PATH)
    db = apply_delta(db, db_delta)
    scope = set(org_ids) if org_ids is not None else ({org_id} if org_id is not None else None)
    if scope is not None:
        db = slice_db_to_orgs(db, scope)
    policy = ITSM_POLICY_PATH.read_text(encoding="utf-8") if ITSM_POLICY_PATH.exists() else ""
    return Environment(
        domain_name=DOMAIN_NAME,
        policy=policy,
        tools=ItsmTools(db, acting_user_id=acting_user_id, org_id=org_id),
    )


def get_tasks() -> list[Task]:
    """Load and validate the ITSM tasks (item 6).

    Tasks are gathered from two optional sources and merged: ``tasks.json`` (a JSON list of
    tasks) and a ``tasks/`` directory (each ``*.json`` file holds one task object or a list of
    them). Duplicate task ids across the sources are rejected.
    """
    raw: list[dict] = []
    if ITSM_TASKS_PATH.exists():
        raw.extend(load_file(ITSM_TASKS_PATH))
    if ITSM_TASKS_DIR.is_dir():
        for fp in sorted(ITSM_TASKS_DIR.glob("*.json")):
            data = load_file(fp)
            raw.extend(data if isinstance(data, list) else [data])

    tasks = [Task.model_validate(t) for t in raw]
    seen: set[str] = set()
    for t in tasks:
        if t.id in seen:
            raise ValueError(f"duplicate task id {t.id!r} across tasks.json / tasks/")
        seen.add(t.id)
    return tasks
