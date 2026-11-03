"""The repository layout contract is checked across all contributed tasks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci_checks.check_tasks import TASKS_DIR, check_tasks

ROOT = Path(__file__).resolve().parents[1]


def make_task(tasks_dir: Path, name: str = "sample_one", *, copies: bool = True) -> Path:
    task = tasks_dir / name
    for directory in ("environment", "tests", "solution"):
        (task / directory).mkdir(parents=True)
    (task / "instruction.md").write_text("Produce the requested output.\n")
    (task / "task.toml").write_text(
        f'schema_version = "1.4"\n[task]\nname = "aisle/{name}"\nversion = "1.0.0"\n'
    )
    raw = json.dumps({"task_id": name, "value": 1}) + "\n"
    (task / "input.json").write_text(raw)
    (task / "environment/Dockerfile").write_text("FROM python:3.12-slim\n")
    (task / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
    (task / "solution/solve.sh").write_text("#!/bin/sh\nexit 0\n")
    if copies:
        for relative in ("environment/input.json", "tests/input.json"):
            (task / relative).write_text(raw)
    return task


def test_repository_tasks_conform():
    assert check_tasks(TASKS_DIR) == []


def test_every_task_is_checked_and_input_copies_are_optional(tmp_path):
    make_task(tmp_path, "sample_one")
    second = make_task(tmp_path, "sample_two", copies=False)
    assert check_tasks(tmp_path) == []
    (second / "solution/README.md").write_text("Misplaced author notes")
    errors = check_tasks(tmp_path)
    assert any("sample_two/solution/README.md" in error for error in errors)
    assert not any("sample_one" in error for error in errors)


@pytest.mark.parametrize("relative", ["README.md", "environment/notes.MD", "solution/README.md"])
def test_author_markdown_is_rejected_anywhere_in_task(tmp_path, relative):
    task = make_task(tmp_path)
    (task / relative).write_text("Author notes")
    assert any("only task-root instruction.md" in error for error in check_tasks(tmp_path))


@pytest.mark.parametrize("relative", ["input.json", "tests/test.sh", "solution/solve.sh"])
def test_missing_required_entrypoint_is_rejected(tmp_path, relative):
    task = make_task(tmp_path)
    (task / relative).unlink()
    assert check_tasks(tmp_path)


def test_identity_and_stale_copy_errors_are_reported_together(tmp_path):
    task = make_task(tmp_path)
    (task / "input.json").write_text('{"task_id":"different_id"}\n')
    (task / "task.toml").write_text('schema_version = "1.4"\n[task]\nname = "aisle/also_wrong"\n')
    errors = check_tasks(tmp_path)
    assert any("task_id must match" in error for error in errors)
    assert any("task.name must end" in error for error in errors)
    assert sum("byte-identical" in error for error in errors) == 2


@pytest.mark.parametrize("raw", ["[]", "{", '{"x":NaN}', '{"x":1,"x":2}'])
def test_input_must_be_a_strict_json_object(tmp_path, raw):
    task = make_task(tmp_path, copies=False)
    (task / "input.json").write_text(raw)
    assert any("JSON" in error for error in check_tasks(tmp_path))


def test_empty_instruction_and_invalid_harbor_config_are_rejected(tmp_path):
    task = make_task(tmp_path)
    (task / "instruction.md").write_text(" \n")
    (task / "task.toml").write_text("not valid TOML")
    errors = check_tasks(tmp_path)
    assert any("instruction must not be empty" in error for error in errors)
    assert any("invalid Harbor task" in error for error in errors)


def test_file_and_directory_types_are_enforced(tmp_path):
    task = make_task(tmp_path)
    (task / "input.json").unlink()
    (task / "input.json").mkdir()
    for child in (task / "solution").iterdir():
        child.unlink()
    (task / "solution").rmdir()
    (task / "solution").write_text("wrong type")
    errors = check_tasks(tmp_path)
    assert any("input.json: must be a regular file" in error for error in errors)
    assert any("solution: must be a directory" in error for error in errors)


def test_collection_root_has_tasks_only_and_cli_fails_with_all_errors(tmp_path):
    first = make_task(tmp_path, "first")
    second = make_task(tmp_path, "second")
    (tmp_path / "README.md").write_text("Index belongs outside the task collection")
    (first / "instruction.md").write_text("")
    (second / "tests/test.sh").unlink()
    completed = subprocess.run(
        [sys.executable, str(ROOT / "ci_checks/check_tasks.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert "tasks/ may contain only task directories" in completed.stdout
    assert "first/instruction.md" in completed.stdout
    assert "second/task.toml" in completed.stdout


def test_empty_task_collection_is_rejected(tmp_path):
    assert any("no task packages found" in error for error in check_tasks(tmp_path))
