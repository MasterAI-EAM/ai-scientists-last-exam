"""Check contribution completeness and internal consistency, not scientific validity.

This checker cannot establish data independence, audit raw measurements, or replace
scientific review. An internally consistent report is not evidence of acceptance.
"""

import hashlib
import json
import math
from pathlib import Path

from aisle.contracts import TaskManifest
from aisle.engine import Engine


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _check_finite(value, location):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not _finite_number(value):
            raise ValueError(f"non-finite number: {location}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_finite(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_finite(item, f"{location}[{index}]")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_document(path, package):
    resolved = path.resolve()
    if not resolved.is_relative_to(package) or not resolved.is_file():
        raise ValueError(f"missing or external sim validation document: {path}")
    raw = resolved.read_bytes()
    data = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(data, dict):
        raise TypeError(f"sim validation document must be an object: {path}")
    _check_finite(data, str(path))
    return data, hashlib.sha256(raw).hexdigest()


def _has_number(value):
    if _finite_number(value):
        return True
    if isinstance(value, dict):
        return any(_has_number(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_number(item) for item in value)
    return False


def _check_metric(value, location):
    if value is None or _finite_number(value):
        return
    if not isinstance(value, dict):
        raise TypeError(f"metric must be a number, null or object: {location}")
    # A zero denominator is not a measured zero error rate. Counts alone are
    # permitted; an estimate must remain null until relevant samples exist.
    count_keys = {"n", "denominator", "sample_count"}
    if any(value.get(key) == 0 for key in count_keys if key in value):
        estimates = {key: item for key, item in value.items() if key not in count_keys}
        estimates.pop("numerator", None)
        if _has_number(estimates):
            raise ValueError(f"numeric estimate with zero samples: {location}")
    for key, item in value.items():
        if isinstance(item, dict):
            _check_metric(item, f"{location}.{key}")


def _metric_complete(value):
    if _finite_number(value):
        return True
    if not isinstance(value, dict) or not value:
        return False
    if any(value.get(key) == 0 for key in ("n", "denominator", "sample_count") if key in value):
        return False
    reason = value.get("reason")
    has_reason = isinstance(reason, str) and bool(reason.strip())
    if "value" in value and value["value"] is None:
        return has_reason
    return _has_number(value) or has_reason


def validate_sim_validation_materials(task_path: Path, task: TaskManifest) -> None:
    """Validate a task's declared plan/report; never infer scientific approval."""
    package = task_path.parent.resolve()
    plan, plan_sha256 = _load_document(package / "validation/sim-validation-plan.json", package)
    report, _ = _load_document(package / "validation/sim-validation-report.json", package)
    current_task = TaskManifest.load(task_path)
    current_binding = {
        "task_manifest_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
        "sop_sha256": hashlib.sha256(
            (package / current_task.real.sop_path).read_bytes()
        ).hexdigest(),
        "simulator_sha256": current_task.sim.model_dump().get("asset_sha256"),
    }
    for name, document in (("plan", plan), ("report", report)):
        if document.get("schema_version") != "1.0" or document.get("task_id") != task.task_id:
            raise ValueError(f"{name} schema/task mismatch: {task_path}")
        if not isinstance(document.get("profile_id"), str) or not document["profile_id"].strip():
            raise ValueError(f"{name} profile_id is required: {task_path}")
        if "task_version" in document and document["task_version"] != current_task.version:
            raise ValueError(f"{name} task_version mismatch: {task_path}")
    binding = plan.get("binding", {})
    if not isinstance(binding, dict):
        raise TypeError(f"plan binding must be an object: {task_path}")
    for key, actual in current_binding.items():
        if key in binding and (
            not isinstance(binding[key], str)
            or len(binding[key]) != 64
            or any(character not in "0123456789abcdef" for character in binding[key])
            or binding[key] != actual
        ):
            raise ValueError(f"plan binding mismatch for {key}: {task_path}")
    if report["profile_id"] != plan["profile_id"]:
        raise ValueError(f"plan/report profile mismatch: {task_path}")
    if report.get("plan_sha256") != plan_sha256:
        raise ValueError(f"plan SHA-256 mismatch: {task_path}")
    if plan.get("status") not in {"proposed", "frozen"}:
        raise ValueError(f"invalid plan status: {task_path}")
    frozen_at = plan.get("frozen_at")
    if frozen_at is not None and (not isinstance(frozen_at, str) or not frozen_at.strip()):
        raise ValueError(f"frozen_at must be a nonempty string or null: {task_path}")
    if plan["status"] == "frozen" and not frozen_at:
        raise ValueError(f"frozen plan needs frozen_at: {task_path}")
    if not isinstance(plan.get("threshold_basis"), str) or not plan["threshold_basis"].strip():
        raise ValueError(f"threshold_basis is required: {task_path}")
    required = plan.get("required_metrics")
    if (
        not isinstance(required, list)
        or not required
        or any(not isinstance(key, str) or not key.strip() for key in required)
        or len(set(required)) != len(required)
    ):
        raise ValueError(f"unique required_metrics are required: {task_path}")
    metrics = report.get("metrics")
    if not isinstance(metrics, dict) or not set(required).issubset(metrics):
        raise ValueError(f"missing required metrics: {task_path}")
    for key, value in metrics.items():
        _check_metric(value, key)

    gates = plan.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError(f"nonempty gates are required: {task_path}")
    gate_ids = set()
    for gate in gates:
        if not isinstance(gate, dict):
            raise TypeError(f"invalid gate: {task_path}")
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not gate_id.strip() or gate_id in gate_ids:
            raise ValueError(f"missing or duplicate gate id: {task_path}")
        gate_ids.add(gate_id)
        if gate.get("op") not in {"<=", ">="} or not _finite_number(gate.get("threshold")):
            raise ValueError(f"invalid gate comparator/threshold: {gate_id}")
        if any(
            not isinstance(gate.get(key), str) or not gate[key].strip() for key in ("unit", "scope")
        ):
            raise ValueError(f"gate unit/scope are required: {gate_id}")
    results = report.get("gate_results")
    if not isinstance(results, dict) or set(results) != gate_ids:
        raise ValueError(f"gate_results must cover exactly all gates: {task_path}")
    for gate in gates:
        result = results[gate["id"]]
        if not isinstance(result, dict) or "value" not in result:
            raise ValueError(f"gate result needs value/status: {gate['id']}")
        status, value = result.get("status"), result["value"]
        if status not in {"pending", "pass", "fail", "insufficient_evidence"}:
            raise ValueError(f"invalid gate result status: {gate['id']}")
        if value is None:
            if status not in {"pending", "insufficient_evidence"}:
                raise ValueError(f"unmeasured gate cannot pass/fail: {gate['id']}")
        elif not _finite_number(value):
            raise ValueError(f"gate value must be finite or null: {gate['id']}")
        elif status in {"pass", "fail"}:
            passes = (
                value <= gate["threshold"] if gate["op"] == "<=" else value >= gate["threshold"]
            )
            if (status == "pass") != passes:
                raise ValueError(f"gate comparison disagrees with status: {gate['id']}")

    origin = report.get("data_origin")
    status = report.get("status")
    if origin not in {"not_collected", "independent_real", "synthetic"}:
        raise ValueError(f"invalid data_origin: {task_path}")
    if status not in {"pending", "insufficient_evidence", "failed", "ready_for_review", "accepted"}:
        raise ValueError(f"invalid report status: {task_path}")
    review = report.get("review")
    if not isinstance(review, dict) or review.get("decision") not in {"pending", "accepted"}:
        raise ValueError(f"report review decision is required: {task_path}")
    if not isinstance(report.get("evidence"), list):
        raise TypeError(f"report evidence must be a list: {task_path}")
    if origin == "not_collected" and (_has_number(metrics) or _has_number(results)):
        raise ValueError(f"not_collected report contains measured numbers: {task_path}")
    accepted = (
        status == "accepted"
        or task.sim.validation_status == "accepted"
        or review["decision"] == "accepted"
    )
    if accepted:
        evidence = report.get("evidence")
        if (
            plan["status"] != "frozen"
            or not plan.get("frozen_at")
            or origin != "independent_real"
            or status != "accepted"
            or any(item["status"] != "pass" for item in results.values())
            or not isinstance(evidence, list)
            or not evidence
            or not isinstance(review, dict)
            or review.get("decision") != "accepted"
            or not isinstance(review.get("scientific_reviewer"), str)
            or not review["scientific_reviewer"].strip()
            or not isinstance(review.get("date"), str)
            or not review["date"].strip()
            or any(not _metric_complete(metrics[key]) for key in required)
            or plan.get("task_version") != current_task.version
            or report.get("task_version") != current_task.version
            or not set(current_binding).issubset(binding)
        ):
            raise ValueError(f"accepted simulation lacks required review/evidence: {task_path}")


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
        validate_sim_validation_materials(path, task)
        print(f"VALID {path.relative_to(root)} [{task.review['status']}]")
    if not paths:
        raise ValueError("no task contributions found")


if __name__ == "__main__":
    main()
