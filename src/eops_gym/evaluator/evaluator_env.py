"""DB-based match (item 5a).

Computes the expected ("gold") DB by replaying the task's gold ``actions``
through the real tools on a fresh seed+delta environment, then compares its hash
to the run's final DB. Trimmed: no user DB, no env assertions, no
message-history reconstruction.
"""

from typing import Callable, Optional

from loguru import logger
from pydantic import BaseModel

from eops_gym.data_model.message import Message, ToolCall
from eops_gym.data_model.tasks import Task
from eops_gym.environment.environment import Environment


class DBCheck(BaseModel):
    db_match: bool
    reward: float


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


def calculate_db_reward(
    environment_constructor: Callable[..., Environment],
    task: Task,
    final_env: Optional[Environment] = None,
    agent_tool_calls: Optional[list[ToolCall]] = None,
) -> DBCheck:
    gold_env = _build_gold_env(environment_constructor, task)
    pred_env = _predicted_env(environment_constructor, task, final_env, agent_tool_calls)
    match = gold_env.get_db_hash() == pred_env.get_db_hash()
    return DBCheck(db_match=match, reward=1.0 if match else 0.0)
