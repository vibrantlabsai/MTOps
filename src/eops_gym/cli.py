"""EnterpriseOps Gym command-line interface.

Trimmed, tau2-style CLI:

    eops run    --domain itsm [--task-ids ...] [--agent-llm ...] [--user-llm ...]
    eops tasks  --domain itsm
    eops domain itsm
"""

import argparse
import sys

from eops_gym.run import (
    DEFAULT_LLM_AGENT,
    TaskResult,
    get_domain,
    list_domains,
    run_domain,
)
from eops_gym.config import DEFAULT_LLM_NL_JUDGE, DEFAULT_LLM_USER
from eops_gym.utils.io_utils import dump_file


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--domain", "-d", type=str, default="itsm", choices=list_domains(),
        help="The domain to run the eval on. Default is itsm.",
    )
    parser.add_argument(
        "--agent-llm", type=str, default=DEFAULT_LLM_AGENT,
        help=f"LLM for the agent. Default is {DEFAULT_LLM_AGENT}.",
    )
    parser.add_argument(
        "--user-llm", type=str, default=DEFAULT_LLM_USER,
        help=f"LLM for the user simulator. Default is {DEFAULT_LLM_USER}.",
    )
    parser.add_argument(
        "--judge-llm", type=str, default=DEFAULT_LLM_NL_JUDGE,
        help=f"LLM for the NL-assertion judge. Default is {DEFAULT_LLM_NL_JUDGE}.",
    )
    parser.add_argument(
        "--task-ids", type=str, nargs="+", default=None,
        help="(Optional) run only the tasks with these ids.",
    )
    parser.add_argument(
        "--num-tasks", type=int, default=None,
        help="(Optional) run at most this many tasks.",
    )
    parser.add_argument(
        "--max-steps", type=int, default=12,
        help="Max conversation steps per task. Default is 12.",
    )
    parser.add_argument(
        "--reward-mode", type=str, default="verifier", choices=["verifier", "db_hash"],
        help="How to score: 'verifier' (original SQL verifiers, comparable to the original "
             "benchmark; default) or 'db_hash' (tau2-strict gold-action DB-hash x NL).",
    )
    parser.add_argument(
        "--save-to", type=str, default=None,
        help="(Optional) path to write full results (trajectories + rewards) as JSON.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print the conversation for each task.",
    )


def _print_task_result(result: TaskResult, verbose: bool) -> None:
    print(f"\n=== {result.task_id} ===")
    if verbose:
        for msg in result.trajectory:
            role = getattr(msg, "role", "?")
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    print(f"  [{role} tool_call] {tc.name}({tc.arguments})")
            elif getattr(msg, "content", None):
                print(f"  [{role}] {msg.content}")
    if result.error:
        print(f"  ERROR    : {result.error}")
    ri = result.reward_info
    if ri.verifier_check is not None:
        vc = ri.verifier_check
        print(f"  verifiers: {sum(c.passed for c in vc.checks)}/{len(vc.checks)} passed "
              f"(all_passed={vc.all_passed})")
    if ri.db_check is not None:
        print(f"  DB match : {ri.db_check.db_match}")
    if ri.nl_check is not None:
        for c in ri.nl_check.checks:
            print(f"  NL [{'PASS' if c.met else 'FAIL'}] {c.nl_assertion}")
    print(f"  reward   : {result.reward}  (stopped={result.stopped}, tool_calls={result.num_tool_calls})")


def run_run(args: argparse.Namespace) -> None:
    results = run_domain(
        domain=args.domain,
        task_ids=args.task_ids,
        num_tasks=args.num_tasks,
        agent_llm=args.agent_llm,
        user_llm=args.user_llm,
        judge_llm=args.judge_llm,
        max_steps=args.max_steps,
        reward_mode=args.reward_mode,
        on_result=lambda r: _print_task_result(r, args.verbose),
    )
    print("\n=== Summary ===")
    print(f"domain={results.domain}  agent={results.agent_llm}  user={results.user_llm}  judge={results.judge_llm}")
    n = len(results.results)
    errored = sum(1 for r in results.results if r.error)
    print(f"reward_mode={results.reward_mode}  tasks={n}  errored={errored}")
    print(f"avg_reward (task success)={results.avg_reward:.3f}")
    vpr = results.avg_verifier_pass_rate
    if vpr is not None:
        print(f"avg_verifier_pass_rate={vpr:.3f}")
    if args.save_to:
        dump_file(args.save_to, results.model_dump())
        print(f"saved results to {args.save_to}")


def run_tasks(args: argparse.Namespace) -> None:
    spec = get_domain(args.domain)
    for task in spec.get_tasks():
        persona = task.user_scenario.persona
        n = task.initial_state_delta.record_count if task.initial_state_delta else 0
        print(f"{task.id}")
        print(f"  persona  : {persona.name} — {persona.personality}")
        print(f"  goal     : {task.user_scenario.task_description}")
        print(f"  delta    : {n} record op(s)")
        print(
            f"  criteria : {len(task.evaluation_criteria.actions)} action(s), "
            f"{len(task.evaluation_criteria.nl_assertions)} nl-assertion(s)"
        )


def run_show_domain(args: argparse.Namespace) -> None:
    spec = get_domain(args.domain)
    print(spec.policy_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="eops", description="EnterpriseOps Gym command line interface")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    run_parser = subparsers.add_parser("run", help="Run an eval over a domain's tasks")
    add_run_args(run_parser)
    run_parser.set_defaults(func=run_run)

    tasks_parser = subparsers.add_parser("tasks", help="List the tasks in a domain")
    tasks_parser.add_argument("--domain", "-d", type=str, default="itsm", choices=list_domains())
    tasks_parser.set_defaults(func=run_tasks)

    domain_parser = subparsers.add_parser("domain", help="Show a domain's policy")
    domain_parser.add_argument("domain", type=str, choices=list_domains(), help="Domain name")
    domain_parser.set_defaults(func=run_show_domain)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    try:
        args.func(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
