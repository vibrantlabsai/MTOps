"""Run evals: tie agent <-> user simulator <-> environment <-> evaluator.

A small, registry-backed runner in the spirit of tau2's ``run.py``. Only the
``itsm`` domain is wired today; add an entry to ``DOMAINS`` to register more.
"""

from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel

from eops_gym.agent.llm_agent import LLMAgent
from eops_gym.config import (
    DEFAULT_LLM_NL_JUDGE,
    DEFAULT_LLM_USER,
)
from eops_gym.data_model.message import Message
from eops_gym.data_model.tasks import Task
from eops_gym.domains.itsm import environment as itsm_environment
from eops_gym.environment.environment import Environment
from eops_gym.evaluator.evaluator import RewardInfo, evaluate_task
from eops_gym.orchestrator.orchestrator import Orchestrator

DEFAULT_LLM_AGENT = "gpt-4o"


class DomainSpec(BaseModel):
    name: str
    get_environment: Callable[..., Environment]
    get_tasks: Callable[[], list[Task]]
    policy_path: Path

    model_config = {"arbitrary_types_allowed": True}


DOMAINS: dict[str, DomainSpec] = {
    "itsm": DomainSpec(
        name="itsm",
        get_environment=itsm_environment.get_environment,
        get_tasks=itsm_environment.get_tasks,
        policy_path=itsm_environment.ITSM_POLICY_PATH,
    ),
}


def list_domains() -> list[str]:
    return list(DOMAINS)


def get_domain(name: str) -> DomainSpec:
    if name not in DOMAINS:
        raise ValueError(f"Unknown domain {name!r}. Available: {list_domains()}")
    return DOMAINS[name]


class TaskResult(BaseModel):
    """Outcome of a single task run (serialisable for --save-to)."""

    task_id: str
    reward: float
    reward_info: RewardInfo
    stopped: bool
    num_tool_calls: int
    trajectory: list[Message]
    error: Optional[str] = None  # set if the task crashed (e.g. provider error); reward is 0


class RunResults(BaseModel):
    domain: str
    agent_llm: str
    user_llm: str
    judge_llm: str
    reward_mode: str = "verifier"
    results: list[TaskResult]

    @property
    def avg_reward(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.reward for r in self.results) / len(self.results)

    @property
    def avg_verifier_pass_rate(self) -> Optional[float]:
        """Mean per-verifier pass rate across tasks that define verifiers (the original's metric)."""
        rates = [
            r.reward_info.verifier_check.pass_rate
            for r in self.results
            if r.reward_info.verifier_check is not None
        ]
        return (sum(rates) / len(rates)) if rates else None


def run_task(
    domain: str,
    task: Task,
    agent_llm: str = DEFAULT_LLM_AGENT,
    user_llm: str = DEFAULT_LLM_USER,
    judge_llm: str = DEFAULT_LLM_NL_JUDGE,
    max_steps: int = 12,
    reward_mode: str = "verifier",
) -> TaskResult:
    """Run and evaluate a single task end to end."""
    spec = get_domain(domain)

    # Bake the task's runtime context (seed + acting user) into a constructor so the live run,
    # the gold-action replay, and the predicted-state rebuild all use the same environment.
    env_cfg = task.environment or {}

    def env_ctor(db_delta=None):
        return spec.get_environment(
            db_delta=db_delta,
            seed=env_cfg.get("seed", "seed_main"),
            acting_user_id=env_cfg.get("acting_user_id"),
        )

    env = env_ctor(db_delta=task.initial_state_delta)
    agent = LLMAgent(env.get_policy(), env.get_tool_schemas(include=task.selected_tools), agent_llm)
    user_sim = _make_user(task, user_llm)

    run = Orchestrator(agent, user_sim, env, max_steps=max_steps).run()
    reward_info = evaluate_task(
        env_ctor,
        task,
        trajectory=run.trajectory,
        final_env=env,
        nl_llm=judge_llm,
        reward_mode=reward_mode,
    )
    return TaskResult(
        task_id=task.id,
        reward=reward_info.reward,
        reward_info=reward_info,
        stopped=run.stopped,
        num_tool_calls=len(run.agent_tool_calls),
        trajectory=run.trajectory,
    )


def run_domain(
    domain: str,
    task_ids: Optional[list[str]] = None,
    num_tasks: Optional[int] = None,
    agent_llm: str = DEFAULT_LLM_AGENT,
    user_llm: str = DEFAULT_LLM_USER,
    judge_llm: str = DEFAULT_LLM_NL_JUDGE,
    max_steps: int = 12,
    reward_mode: str = "verifier",
    on_result: Optional[Callable[[TaskResult], None]] = None,
) -> RunResults:
    """Run and evaluate a set of tasks for a domain."""
    spec = get_domain(domain)
    tasks = spec.get_tasks()
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t.id in wanted]
    if num_tasks is not None:
        tasks = tasks[:num_tasks]

    results: list[TaskResult] = []
    for task in tasks:
        try:
            result = run_task(
                domain,
                task,
                agent_llm=agent_llm,
                user_llm=user_llm,
                judge_llm=judge_llm,
                max_steps=max_steps,
                reward_mode=reward_mode,
            )
        except Exception as e:  # noqa: BLE001 - one task's failure shouldn't abort the batch
            result = TaskResult(
                task_id=task.id,
                reward=0.0,
                reward_info=RewardInfo(reward=0.0),
                stopped=False,
                num_tool_calls=0,
                trajectory=[],
                error=f"{type(e).__name__}: {e}",
            )
        results.append(result)
        if on_result is not None:
            on_result(result)

    return RunResults(
        domain=domain,
        agent_llm=agent_llm,
        user_llm=user_llm,
        judge_llm=judge_llm,
        reward_mode=reward_mode,
        results=results,
    )


def _make_user(task: Task, user_llm: str):
    from eops_gym.user.user_simulator import UserSimulator

    return UserSimulator(task.user_scenario, llm=user_llm)
