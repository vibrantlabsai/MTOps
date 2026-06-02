"""Assemble the per-task ported JSON files into the domain's tasks.json.

Reads every ``data/itsm/ported_tasks/*.json``, validates each against the ``Task`` model, and
writes the combined, id-sorted list to ``data/itsm/tasks.json`` (what ``get_tasks`` loads).
"""

from __future__ import annotations

import json
from pathlib import Path

from eops_gym.data_model.tasks import Task

REPO = Path(__file__).resolve().parents[1]
PORTED_DIR = REPO / "data" / "itsm" / "ported_tasks"
TASKS_JSON = REPO / "data" / "itsm" / "tasks.json"


def main() -> None:
    tasks: list[dict] = []
    for fp in sorted(PORTED_DIR.glob("*.json")):
        raw = json.loads(fp.read_text())
        Task.model_validate(raw)  # fail loudly on a malformed ported task
        tasks.append(raw)
    tasks.sort(key=lambda t: t["id"])
    TASKS_JSON.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"assembled {len(tasks)} tasks -> {TASKS_JSON}")
    for t in tasks:
        ec = t.get("evaluation_criteria", {})
        print(f"  {t['id']:42s} actions={len(ec.get('actions', []))} nl={len(ec.get('nl_assertions', []))}")


if __name__ == "__main__":
    main()
