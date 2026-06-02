"""Merge the original benchmark's SQL verifiers into the ported task files.

Reads the snapshot in ``tests/fixtures/itsm_original_verifiers.json`` and writes each task's
verifiers into ``evaluation_criteria.verifiers`` of its ``data/itsm/ported_tasks/*.json`` file,
so the verifiers travel with the tasks and can be scored at runtime (original-comparable).
Run ``scripts/assemble_tasks.py`` afterwards to rebuild ``tasks.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PORTED = REPO / "data" / "itsm" / "ported_tasks"
FIXTURE = REPO / "tests" / "fixtures" / "itsm_original_verifiers.json"


def main() -> None:
    verifiers_by_id = {k: v["verifiers"] for k, v in json.loads(FIXTURE.read_text()).items()}
    for fp in sorted(PORTED.glob("*.json")):
        task = json.loads(fp.read_text())
        tid = task["id"]
        if tid not in verifiers_by_id:
            print(f"  WARN: no verifiers for {tid}")
            continue
        task.setdefault("evaluation_criteria", {})["verifiers"] = verifiers_by_id[tid]
        fp.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {tid}: +{len(verifiers_by_id[tid])} verifiers")


if __name__ == "__main__":
    main()
