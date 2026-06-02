"""ITSM environment + task loader factory. Mirrors tau2 domain ``environment.py``."""

from pathlib import Path
from typing import Optional

from eops_gym.data_model.tasks import Task
from eops_gym.domains.itsm.data_model import ItsmDB
from eops_gym.domains.itsm.tools import ItsmTools
from eops_gym.environment.delta import Delta, apply_delta
from eops_gym.environment.environment import Environment
from eops_gym.utils.io_utils import load_file

_DATA_DIR = Path(__file__).resolve().parents[3].parent / "data" / "itsm"
SEEDS_DIR = _DATA_DIR / "seeds"
ITSM_POLICY_PATH = _DATA_DIR / "policy.md"
ITSM_TASKS_PATH = _DATA_DIR / "tasks.json"

DEFAULT_SEED = "seed_main"
DOMAIN_NAME = "itsm"


def seed_path(seed: str) -> Path:
    """Path to a seed db.json (e.g. 'seed_main', 'seed_alt')."""
    return SEEDS_DIR / f"{seed}.json"


def get_environment(
    db_delta: Optional[Delta | dict] = None,
    seed: str = DEFAULT_SEED,
    acting_user_id: Optional[str] = None,
) -> Environment:
    """Build a fresh ITSM environment: load the seed DB, apply the task delta (item 7).

    ``seed`` selects which ported seed database to load; ``acting_user_id`` is the
    authenticated caller from the task context (used for org scoping in the tools).
    """
    db = ItsmDB.load(seed_path(seed))
    db = apply_delta(db, db_delta)
    policy = ITSM_POLICY_PATH.read_text(encoding="utf-8") if ITSM_POLICY_PATH.exists() else ""
    return Environment(
        domain_name=DOMAIN_NAME, policy=policy, tools=ItsmTools(db, acting_user_id=acting_user_id)
    )


def get_tasks() -> list[Task]:
    """Load and validate the ITSM tasks from tasks.json (item 6)."""
    raw = load_file(ITSM_TASKS_PATH)
    return [Task.model_validate(t) for t in raw]
