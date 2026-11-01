"""Validate every discovered task contribution, including future PR additions."""

from pathlib import Path

from aisle.contracts import TaskManifest
from aisle.engine import Engine


def main():
    root = Path(__file__).resolve().parents[1]
    paths = sorted(
        {
            p
            for folder in ("examples/tasks", "tasks", "templates/task")
            for p in (root / folder).rglob("task.yaml")
        }
    )
    task_ids = set()
    for path in paths:
        task = TaskManifest.load(path)
        Engine.task(task.model_dump()).validate_target(task.target)
        if task.task_id in task_ids:
            raise ValueError(f"duplicate task_id: {task.task_id}")
        task_ids.add(task.task_id)
        for name in (task.real.sop_path, "scoring.md", task.review.get("report", "acceptance.md")):
            candidate = (path.parent / name).resolve()
            if not candidate.is_relative_to(path.parent) or not candidate.is_file():
                raise ValueError(f"missing or external contribution document: {path}: {name}")
        print(f"VALID {path.relative_to(root)} [{task.review['status']}]")
    if not paths:
        raise ValueError("no task contributions found")


if __name__ == "__main__":
    main()
