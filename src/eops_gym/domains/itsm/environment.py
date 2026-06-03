"""ITSM environment + task loader factory."""

from pathlib import Path
from typing import Optional

from eops_gym.data_model.tasks import Task
from eops_gym.domains.itsm.data_model import ItsmDB
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
) -> Environment:
    """Build a fresh ITSM environment: load ``db.json`` and apply the task delta (item 7).

    ``acting_user_id`` is the authenticated caller from the task context (used for org
    scoping in the tools).
    """
    db = ItsmDB.load(ITSM_DB_PATH)
    db = apply_delta(db, db_delta)
    policy = ITSM_POLICY_PATH.read_text(encoding="utf-8") if ITSM_POLICY_PATH.exists() else ""
    return Environment(
        domain_name=DOMAIN_NAME, policy=policy, tools=ItsmTools(db, acting_user_id=acting_user_id)
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
