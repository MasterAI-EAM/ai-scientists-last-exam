"""Exports must preserve runnable behavior without leaking private or oracle files."""

import json
from pathlib import Path

import pytest
from harbor.models.task.config import TaskConfig
from harbor.models.task.task import Task
from test_task_structure import make_task

from scripts import export_harbor as exporter
from scripts import prepare as preparation


@pytest.fixture
def source(tmp_path, monkeypatch):
    task = make_task(tmp_path / "sources")
    replay = tmp_path / "runtime/scripts/replay_witness.py"
    replay.parent.mkdir(parents=True)
    replay.write_text("# execute a reference through the experiment API\n")
    monkeypatch.setattr(exporter, "ROOT", replay.parents[1])
    return task


def snapshot(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_export_is_native_harbor_with_same_config_and_single_input(source, tmp_path):
    before = snapshot(source)
    output = exporter.export_task(source, tmp_path / "exports")
    task = Task(output)
    manifest = json.loads((source / "task.json").read_text())
    manifest.pop("input")
    assert task.config == TaskConfig.model_validate(manifest)
    assert Task.is_valid_dir(output)
    assert task.paths.discovered_solve_path == output / "solution/solve.sh"
    assert (output / "solution/solve.sh").stat().st_mode & 0o111
    raw = (output / "input.json").read_bytes()
    assert raw == (output / "environment/input.json").read_bytes()
    assert raw == (output / "tests/input.json").read_bytes()
    assert json.loads(raw)["target"]["success_threshold"] == 1
    assert (output / "tests/score.py").read_bytes() == (source / "verifier/score.py").read_bytes()
    assert (output / "instruction.md").read_bytes() == (source / "instruction.md").read_bytes()
    assert (output / "solution/curated_01.jsonl").read_bytes() == (
        source / "witnesses/curated_01.jsonl"
    ).read_bytes()
    assert snapshot(source) == before


def test_private_assets_and_oracle_stay_out_of_agent_environment(source, tmp_path):
    (source / "environment/assets").mkdir()
    (source / "environment/assets/private.joblib").write_bytes(b"not authorized")
    (source / "environment/__pycache__").mkdir()
    (source / "environment/__pycache__/server.pyc").write_bytes(b"cache")
    output = exporter.export_task(source, tmp_path / "exports")
    assert not (output / "environment/assets").exists()
    assert not (output / "environment/__pycache__").exists()
    assert not list((output / "environment").rglob("*.jsonl"))
    assert (output / "solution/curated_01.jsonl").exists()


def test_model_hash_is_verified_and_only_staged_in_export(source, tmp_path):
    model = tmp_path / "frozen.joblib"
    model.write_bytes(b"authorized model")
    output = exporter.export_task(source, tmp_path / "exports", model)
    assert (
        output / "environment/assets/lightgbm_lab_model.joblib"
    ).read_bytes() == model.read_bytes()
    assert not (source / "environment/assets").exists()
    original = snapshot(output)
    model.write_bytes(b"different model")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        exporter.export_task(source, tmp_path / "exports", model)
    assert snapshot(output) == original


def test_export_refreshes_only_its_owned_destination(source, tmp_path):
    output = exporter.export_task(source, tmp_path / "exports")
    (output / "stale-output.txt").write_text("must not survive export refresh")
    (source / "instruction.md").write_text("Updated task instructions.\n")
    assert exporter.export_task(source, tmp_path / "exports") == output
    assert not (output / "stale-output.txt").exists()
    assert (output / "instruction.md").read_text() == "Updated task instructions.\n"
    unrelated = tmp_path / "unrelated" / source.name
    unrelated.mkdir(parents=True)
    (unrelated / "keep.txt").write_text("user data")
    with pytest.raises(ValueError, match="not owned"):
        exporter.export_task(source, unrelated.parent)
    assert (unrelated / "keep.txt").read_text() == "user data"


def test_source_overlap_and_destination_symlinks_are_rejected(source, tmp_path):
    with pytest.raises(ValueError, match="overlap"):
        exporter.export_task(source, source.parent)
    with pytest.raises(ValueError, match="overlap"):
        exporter.export_task(source, source / "generated")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "linked-export"
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        exporter.export_task(source, link)
    assert not list(elsewhere.iterdir())


def test_failed_export_does_not_replace_previous_working_package(source, tmp_path, monkeypatch):
    output = exporter.export_task(source, tmp_path / "exports")
    original = snapshot(output)
    original_copy = exporter.shutil.copyfile

    def failed_copy(src, dst, *args, **kwargs):
        if Path(src).name == "replay_witness.py":
            raise OSError("controlled write failure")
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(exporter.shutil, "copyfile", failed_copy)
    with pytest.raises(OSError, match="controlled"):
        exporter.export_task(source, tmp_path / "exports")
    assert snapshot(output) == original
    assert sorted(path.name for path in output.parent.iterdir()) == [source.name]


def test_prepare_check_is_read_only_and_export_targets_selected_task(source, tmp_path):
    before = snapshot(source)
    output = tmp_path / "prepared"
    checked = preparation.prepare(None, check=True, task=source, output=output)
    assert checked["source_valid"] is True
    assert not output.exists()
    result = preparation.prepare(None, task=source, output=output)
    assert result["asset_staged"] is False
    assert Path(result["exported_task"]) == output / source.name
    assert snapshot(source) == before


def test_failed_publish_restores_previous_export(source, tmp_path, monkeypatch):
    output = exporter.export_task(source, tmp_path / "exports")
    original = snapshot(output)
    rename = Path.rename

    def failed_publish(path, target):
        if path.name.startswith(f".{source.name}-") and "previous" not in path.name:
            raise OSError("controlled publication failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", failed_publish)
    with pytest.raises(OSError, match="publication"):
        exporter.export_task(source, tmp_path / "exports")
    assert snapshot(output) == original
    assert sorted(path.name for path in output.parent.iterdir()) == [source.name]
