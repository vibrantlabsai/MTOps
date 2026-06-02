"""Task FIDELITY gate (offline, no LLM / no oracle).

The strongest port guarantee: each ported task's gold ``actions``, replayed through the real
tools on its seed (+ delta), must satisfy that task's ``verifiers`` — the ORIGINAL benchmark's
SQL checks, now carried on the task itself. Uses the same ``run_verifiers`` code path the
evaluator uses at runtime, so this certifies the ported tasks are faithful (not merely
internally consistent).
"""

from __future__ import annotations

import pytest

from eops_gym.domains.itsm import environment as itsm_env
from eops_gym.environment.delta import apply_delta
from eops_gym.evaluator.evaluator_verifier import run_verifiers

TASKS = itsm_env.get_tasks()


def test_every_task_carries_verifiers():
    missing = [t.id for t in TASKS if not t.evaluation_criteria.verifiers]
    assert not missing, f"tasks missing original verifiers: {missing}"


@pytest.mark.parametrize("task", TASKS, ids=[t.id for t in TASKS])
def test_gold_actions_satisfy_verifiers(task):
    cfg = task.environment or {}
    env = itsm_env.get_environment(
        seed=cfg.get("seed", "seed_main"), acting_user_id=cfg.get("acting_user_id")
    )
    env.tools.db = apply_delta(env.tools.db, task.initial_state_delta)
    for a in task.evaluation_criteria.actions:
        env.make_tool_call(a.name, **a.arguments)

    vc = run_verifiers(env.tools.db, task.evaluation_criteria.verifiers)
    failed = [c.name for c in vc.checks if not c.passed]
    assert vc.all_passed, f"{task.id}: gold actions fail original verifiers: {failed}"
