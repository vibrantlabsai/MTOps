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
from eops_gym.evaluator.evaluator_env import DBCheck, _predicted_env, calculate_db_reward
from eops_gym.evaluator.evaluator_nl import NLCheck, evaluate_nl_assertions
from eops_gym.evaluator.evaluator_verifier import VerifierCheck, run_verifiers

# How the final reward is gated:
#   "verifier" — task success = all SQL verifiers pass (comparable to the original benchmark);
#                NL assertions are computed for info but do not gate. Falls back to DB-hash if a
#                task has no verifiers.
#   "db_hash"  — tau2-strict: gold-action full-DB-hash match × NL assertions.
REWARD_MODES = ("verifier", "db_hash")


class RewardInfo(BaseModel):
    reward: float
    db_check: Optional[DBCheck] = None
    nl_check: Optional[NLCheck] = None
    verifier_check: Optional[VerifierCheck] = None


def evaluate_task(
    environment_constructor: Callable[..., Environment],
    task: Task,
    trajectory: list[Message],
    final_env: Optional[Environment] = None,
    agent_tool_calls: Optional[list[ToolCall]] = None,
    nl_llm: Optional[str] = None,
    nl_llm_args: Optional[dict] = None,
    reward_mode: str = "verifier",
) -> RewardInfo:
    """Score a completed run against the task's evaluation criteria.

    All applicable checks are computed for information; ``reward_mode`` decides which gate the
    final reward (see REWARD_MODES).
    """
    criteria = task.evaluation_criteria

    # gold-action full-DB-hash (computed whenever the task defines gold actions)
    db_check: Optional[DBCheck] = None
    if criteria.actions:
        db_check = calculate_db_reward(
            environment_constructor, task, final_env=final_env, agent_tool_calls=agent_tool_calls
        )

    # original-style SQL verifiers over the predicted final DB
    verifier_check: Optional[VerifierCheck] = None
    if criteria.verifiers:
        pred_env = _predicted_env(environment_constructor, task, final_env, agent_tool_calls)
        verifier_check = run_verifiers(pred_env.tools.db, criteria.verifiers)

    # NL-assertion judge (informational under verifier mode; gating under db_hash mode)
    nl_check: Optional[NLCheck] = None
    if criteria.nl_assertions:
        nl_check = evaluate_nl_assertions(
            trajectory, criteria.nl_assertions, llm=nl_llm, llm_args=nl_llm_args
        )

    if reward_mode == "db_hash":
        reward = (db_check.reward if db_check else 1.0) * (nl_check.reward if nl_check else 1.0)
    else:  # "verifier" (default): verifiers gate, falling back to DB-hash if none defined
        if verifier_check is not None:
            reward = verifier_check.reward
        elif db_check is not None:
            reward = db_check.reward
        else:
            reward = 1.0

    return RewardInfo(
        reward=reward, db_check=db_check, nl_check=nl_check, verifier_check=verifier_check
    )
