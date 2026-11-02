"""Adversarial contribution reports; all measurements here are software fixtures."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from aisle.contracts import TaskManifest

SCRIPT = Path(__file__).parents[1] / "scripts/validate_contributions.py"
SPEC = importlib.util.spec_from_file_location("validate_contributions", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate = MODULE.validate_sim_validation_materials


@pytest.fixture
def materials(manifest_factory):
    path = manifest_factory()
    task = TaskManifest.load(path)
    directory = path.parent / "validation"
    directory.mkdir()
    plan = {
        "schema_version": "1.0",
        "task_id": task.task_id,
        "task_version": task.version,
        "profile_id": "test-fixture",
        "status": "proposed",
        "frozen_at": None,
        "threshold_basis": "Software test fixture, not a scientific threshold.",
        "required_metrics": ["mean_error", "r2"],
        "binding": {
            "task_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "sop_sha256": hashlib.sha256(
                (path.parent / task.real.sop_path).read_bytes()
            ).hexdigest(),
            "simulator_sha256": task.sim.model_dump()["asset_sha256"],
        },
        "gates": [
            {"id": "mean_error", "op": "<=", "threshold": 0.5, "unit": "test", "scope": "all"}
        ],
    }
    report = {
        "schema_version": "1.0",
        "task_id": task.task_id,
        "task_version": task.version,
        "profile_id": "test-fixture",
        "data_origin": "not_collected",
        "status": "pending",
        "metrics": {"mean_error": None, "r2": None},
        "gate_results": {"mean_error": {"value": None, "status": "pending"}},
        "evidence": [],
        "review": {"scientific_reviewer": None, "decision": "pending", "date": None},
    }

    def write():
        raw = json.dumps(plan).encode()
        (directory / "sim-validation-plan.json").write_bytes(raw)
        report["plan_sha256"] = hashlib.sha256(raw).hexdigest()
        (directory / "sim-validation-report.json").write_text(json.dumps(report))
        return path, task

    return plan, report, write


def test_draft_may_be_complete_without_fabricated_measurements(materials):
    _, _, write = materials
    validate(*write())


@pytest.mark.parametrize("missing", ["metric", "gate", "file"])
def test_missing_scientific_material_is_not_silently_ignored(materials, missing):
    _, report, write = materials
    if missing == "metric":
        del report["metrics"]["r2"]
    elif missing == "gate":
        del report["gate_results"]["mean_error"]
    args = write()
    if missing == "file":
        (args[0].parent / "validation/sim-validation-report.json").unlink()
    with pytest.raises(ValueError):
        validate(*args)


@pytest.mark.parametrize("value,status", [(None, "pass"), (1.2, "pass"), (0.1, "fail")])
def test_declared_gate_decision_must_match_measurement(materials, value, status):
    _, report, write = materials
    report["data_origin"] = "synthetic"
    report["gate_results"]["mean_error"] = {"value": value, "status": status}
    with pytest.raises(ValueError, match="gate"):
        validate(*write())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nested_nonfinite_numbers_are_rejected(materials, value):
    _, report, write = materials
    report["data_origin"] = "synthetic"
    report["metrics"]["r2"] = {"value": value, "reason": "not allowed in JSON"}
    with pytest.raises(ValueError, match="non-finite"):
        validate(*write())


def test_changed_plan_cannot_reuse_old_report_hash(materials):
    _, _, write = materials
    args = write()
    plan_path = args[0].parent / "validation/sim-validation-plan.json"
    plan_path.write_bytes(plan_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        validate(*args)


@pytest.mark.parametrize("value", [0.0, {"value": 0.0, "n": 0}])
def test_no_data_is_not_a_measured_zero_error(materials, value):
    _, report, write = materials
    report["metrics"]["mean_error"] = value
    with pytest.raises(ValueError, match="zero samples|not_collected"):
        validate(*write())


def test_zero_denominator_cannot_claim_zero_error_rate(materials):
    _, report, write = materials
    report["data_origin"] = "synthetic"
    report["metrics"]["mean_error"] = {"numerator": 0, "denominator": 0, "rate": 0.0}
    with pytest.raises(ValueError, match="zero samples"):
        validate(*write())


def accepted_fixture(plan, report):
    """Only tests structural checks; these strings do not prove real experiments."""
    plan.update(status="frozen", frozen_at="2026-11-02")
    report.update(data_origin="independent_real", status="accepted")
    report["metrics"] = {"mean_error": 0.25, "r2": {"value": None, "reason": "constant target"}}
    report["gate_results"]["mean_error"] = {"value": 0.25, "status": "pass"}
    report["evidence"] = [{"uri": "fixture://not-real-evidence"}]
    report["review"] = {
        "scientific_reviewer": "fixture-reviewer",
        "decision": "accepted",
        "date": "2026-11-02",
    }


@pytest.mark.parametrize(
    "defect",
    [
        "synthetic",
        "proposed",
        "no_evidence",
        "no_reviewer",
        "no_metric",
        "empty_metric",
        "undefined_without_reason",
        "zero_denominator",
        "no_binding",
        "no_plan_version",
        "no_report_version",
    ],
)
def test_accepted_status_requires_complete_independent_review_material(materials, defect):
    plan, report, write = materials
    accepted_fixture(plan, report)
    if defect == "synthetic":
        report["data_origin"] = "synthetic"
    elif defect == "proposed":
        plan["status"] = "proposed"
    elif defect == "no_evidence":
        report["evidence"] = []
    elif defect == "no_reviewer":
        report["review"]["scientific_reviewer"] = None
    elif defect == "no_metric":
        report["metrics"]["r2"] = None
    elif defect == "empty_metric":
        report["metrics"]["r2"] = {}
    elif defect == "undefined_without_reason":
        report["metrics"]["r2"] = {"value": None}
    elif defect == "zero_denominator":
        report["metrics"]["r2"] = {"value": None, "n": 0, "reason": "no samples"}
    elif defect == "no_binding":
        del plan["binding"]
    elif defect == "no_plan_version":
        del plan["task_version"]
    elif defect == "no_report_version":
        del report["task_version"]
    with pytest.raises(ValueError, match="accepted simulation"):
        validate(*write())


def test_undefined_r2_with_reason_is_compatible_with_complete_material(materials):
    plan, report, write = materials
    accepted_fixture(plan, report)
    validate(*write())


def test_manifest_cannot_bypass_pending_report(materials):
    _, _, write = materials
    path, task = write()
    task.sim.validation_status = "accepted"
    with pytest.raises(ValueError, match="accepted simulation"):
        validate(path, task)


@pytest.mark.parametrize("changed", ["sop", "simulator", "version", "target"])
def test_old_report_cannot_validate_changed_task_or_asset(materials, changed):
    plan, report, write = materials
    accepted_fixture(plan, report)
    path, task = write()
    if changed == "sop":
        (path.parent / task.real.sop_path).write_text("Changed SOP after validation.\n")
    else:
        payload = json.loads(path.read_text())
        if changed == "simulator":
            payload["sim"]["asset_sha256"] = "b" * 64
        elif changed == "version":
            payload["version"] = "changed-after-validation"
        else:
            payload["target"]["lab"][0] += 1
        path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="binding mismatch|task_version mismatch"):
        validate(path, TaskManifest.load(path))


def test_asset_binding_is_checked_even_if_manifest_hash_was_refreshed(materials):
    plan, report, write = materials
    accepted_fixture(plan, report)
    path, _ = write()
    payload = json.loads(path.read_text())
    payload["sim"]["asset_sha256"] = "b" * 64
    path.write_text(json.dumps(payload))
    plan["binding"]["task_manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write()
    with pytest.raises(ValueError, match="simulator_sha256"):
        validate(path, TaskManifest.load(path))
