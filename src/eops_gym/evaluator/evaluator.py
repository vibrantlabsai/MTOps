"""Evaluator dispatcher (item 5).

Combines DB-based match (5a) and NL assertions (5b) into a single RewardInfo.
The combined reward is multiplicative over the criteria that the task defines,
so a task passes only if every defined criterion passes.
"""

from typing import Callable, Optional

from pydantic import BaseModel

from eops_gym.data_model.message import Message, ToolCall
from eops_gym.data_model.tasks import Task
from eops_gym.environment.environment import Environment
from eops_gym.evaluator.evaluator_env import DBCheck, calculate_db_reward
from eops_gym.evaluator.evaluator_nl import NLCheck, evaluate_nl_assertions


class RewardInfo(BaseModel):
    reward: float
    db_check: Optional[DBCheck] = None
    nl_check: Optional[NLCheck] = None


def evaluate_task(
    environment_constructor: Callable[..., Environment],
    task: Task,
    trajectory: list[Message],
    final_env: Optional[Environment] = None,
    agent_tool_calls: Optional[list[ToolCall]] = None,
    nl_llm: Optional[str] = None,
    nl_llm_args: Optional[dict] = None,
    skip_nl_assertions: bool = False,
) -> RewardInfo:
    """Score a completed run against the task's evaluation criteria.

    The reward is the product of the two criteria the task may define: gold-action
    full-DB-hash match and the NL-assertion judge. A task passes (reward 1.0) only if
    every defined criterion passes.
    """
    criteria = task.evaluation_criteria

    # gold-action full-DB-hash (computed whenever the task defines gold actions)
    db_check: Optional[DBCheck] = None
    if criteria.actions:
        db_check = calculate_db_reward(
            environment_constructor, task, final_env=final_env, agent_tool_calls=agent_tool_calls
        )

    # NL-assertion judge. Skipped for RL/gym reward, where the judge LLM is unnecessary
    # overhead/non-determinism.
    nl_check: Optional[NLCheck] = None
    if criteria.nl_assertions and not skip_nl_assertions:
        nl_check = evaluate_nl_assertions(
            trajectory, criteria.nl_assertions, llm=nl_llm, llm_args=nl_llm_args
        )

    reward = (db_check.reward if db_check else 1.0) * (nl_check.reward if nl_check else 1.0)

    return RewardInfo(reward=reward, db_check=db_check, nl_check=nl_check)
