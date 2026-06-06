"""DB-based match (item 5a).

Computes the expected ("gold") DB by replaying the task's gold ``actions`` through the real
tools on a fresh seed+delta environment, then compares it to the run's final DB record by record:
**structured fields exact, free-text fields fuzzy** (an LLM can't reproduce prose like a
notification subject verbatim — see ``compare_dbs`` and ``utils.text_match``).
"""

from typing import Callable, Optional

from loguru import logger
from pydantic import BaseModel, Field

from eops_gym.data_model.message import Message, ToolCall
from eops_gym.data_model.tasks import Task
from eops_gym.environment.db import DB
from eops_gym.environment.environment import Environment
from eops_gym.utils.text_match import DB_FUZZY_THRESHOLD, fuzzy_text_match


class DBCheck(BaseModel):
    db_match: bool
    reward: float
    mismatches: list[str] = Field(default_factory=list)  # first divergences, for debugging


def _build_gold_env(environment_constructor: Callable[..., Environment], task: Task) -> Environment:
    gold_env = environment_constructor(db_delta=task.initial_state_delta)
    for action in task.evaluation_criteria.actions:
        try:
            gold_env.make_tool_call(action.name, **action.arguments)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"gold action {action.name} failed: {e}")
    return gold_env


def _predicted_env(
    environment_constructor: Callable[..., Environment],
    task: Task,
    final_env: Optional[Environment],
    agent_tool_calls: Optional[list[ToolCall]],
) -> Environment:
    """The DB state the agent actually produced.

    Default: the live ``final_env`` the run already mutated. Offline fallback:
    rebuild from recorded ``agent_tool_calls`` on a fresh seed+delta env.
    """
    if final_env is not None:
        return final_env
    if agent_tool_calls is None:
        raise ValueError("Provide either final_env or agent_tool_calls.")
    env = environment_constructor(db_delta=task.initial_state_delta)
    for tc in agent_tool_calls:
        try:
            env.make_tool_call(tc.name, **tc.arguments)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"replayed agent call {tc.name} failed: {e}")
    return env


def tool_calls_from_trajectory(trajectory: list[Message]) -> list[ToolCall]:
    """Extract assistant tool calls from a trajectory (for offline re-eval)."""
    calls: list[ToolCall] = []
    for msg in trajectory:
        tcs = getattr(msg, "tool_calls", None)
        if tcs and getattr(msg, "role", None) == "assistant":
            calls.extend(tcs)
    return calls


def _compare_record(
    gold: dict, pred: dict, freetext: list[str], baseline: dict, threshold: float
) -> Optional[str]:
    """Compare two record dicts; return the first divergence (or None if they match).

    Non-free-text fields must be equal. A free-text field is only checked — and then by content
    overlap, not exact — when the gold actually *changed* it from ``baseline`` (the pre-action
    seed+delta value). If the task's gold left a prose field untouched, the agent's value there is
    unconstrained (it may add a worknote the task never asked for).
    """
    for field in sorted(set(gold) | set(pred)):
        gv, pv = gold.get(field), pred.get(field)
        if field in freetext:
            if gv == baseline.get(field):
                continue  # gold didn't set this prose field; don't constrain the agent
            if not fuzzy_text_match(gv, pv, threshold):
                return f"{field}: {gv!r} !~ {pv!r}"
        elif gv != pv:
            return f"{field}: {gv!r} != {pv!r}"
    return None


def _dump(rec):
    return rec.model_dump() if isinstance(rec, BaseModel) else rec


def compare_dbs(
    gold_db: DB,
    pred_db: DB,
    baseline_db: Optional[DB] = None,
    threshold: float = DB_FUZZY_THRESHOLD,
) -> tuple[bool, list[str]]:
    """Record-by-record DB comparison: structured fields exact, free-text fields fuzzy.

    Collections must have identical record-id sets (no missing / no extra rows). ``baseline_db``
    (the seed+delta DB before the gold actions) lets free-text fields the gold never changed be
    ignored. Returns ``(matched, mismatches)`` where ``mismatches`` lists the first divergences.
    """
    freetext = gold_db.freetext_fields()
    mismatches: list[str] = []
    for coll in type(gold_db).model_fields:
        gold_coll, pred_coll = getattr(gold_db, coll), getattr(pred_db, coll)
        if not isinstance(gold_coll, dict):
            if gold_coll != pred_coll:
                mismatches.append(f"{coll}: {gold_coll!r} != {pred_coll!r}")
            continue
        gold_ids, pred_ids = set(gold_coll), set(pred_coll)
        if gold_ids != pred_ids:
            if missing := sorted(gold_ids - pred_ids):
                mismatches.append(f"{coll}: missing {missing}")
            if extra := sorted(pred_ids - gold_ids):
                mismatches.append(f"{coll}: unexpected {extra}")
            continue
        ft = freetext.get(coll, [])
        base_coll = getattr(baseline_db, coll, {}) if baseline_db is not None else {}
        for rid in sorted(gold_ids):
            base = _dump(base_coll[rid]) if rid in base_coll else {}
            if reason := _compare_record(_dump(gold_coll[rid]), _dump(pred_coll[rid]), ft, base, threshold):
                mismatches.append(f"{coll}/{rid} {reason}")
    return (not mismatches), mismatches


def calculate_db_reward(
    environment_constructor: Callable[..., Environment],
    task: Task,
    final_env: Optional[Environment] = None,
    agent_tool_calls: Optional[list[ToolCall]] = None,
) -> DBCheck:
    gold_env = _build_gold_env(environment_constructor, task)
    pred_env = _predicted_env(environment_constructor, task, final_env, agent_tool_calls)
    # Baseline = seed+delta before any gold action, so free-text fields the gold never changed
    # don't constrain the agent.
    baseline_db = environment_constructor(db_delta=task.initial_state_delta).tools.db
    match, mismatches = compare_dbs(gold_env.tools.db, pred_env.tools.db, baseline_db)
    return DBCheck(db_match=match, reward=1.0 if match else 0.0, mismatches=mismatches[:20])
