"""Scientific edge cases and regression evidence for migrated colour tasks."""

import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

from aisle.tasks.color import ColorTask, delta_e_2000
from aisle.tasks.simulator import LightGBMSimulator

ACTION = {"recipe": {"Red": 0, "Green": 140, "Blue": 60, "water": 0}}
TARGET = {"lab": [50.0, 0.0, 0.0], "success_threshold": 2.0}
SAFETY_TARGET = {
    **TARGET,
    "safety": {
        "enabled": True,
        "danger_center_lab": [50.0, 0.0, 0.0],
        "forbidden_delta_e_min": 2.0,
        "forbidden_delta_e_max": 5.0,
        "max_safety_violations": 2,
    },
}


def raw(lab):
    return {"measured_lab": lab, "qc": {"status": "passed"}, "provenance": {"kind": "real"}}


def item(lab):
    return {"action": ACTION, "observation": raw(lab)}


def lab_at_distance(distance):
    lo, hi = 50.0, 80.0
    for _ in range(60):
        middle = (lo + hi) / 2
        if delta_e_2000([middle, 0, 0], TARGET["lab"]) < distance:
            lo = middle
        else:
            hi = middle
    return [(lo + hi) / 2, 0, 0]


def test_ciede2000_reference_pair():
    # Sharma, Wu & Dalal (2005), supplemental test data, pair 1.
    assert delta_e_2000([50, 2.6772, -79.7751], [50, 0, -82.7485]) == pytest.approx(
        2.0425, abs=5e-5
    )


@pytest.mark.parametrize(
    "recipe",
    [
        {"Red": True, "Green": 139, "Blue": 60, "water": 0},
        {"Red": -1, "Green": 141, "Blue": 60, "water": 0},
        {"Red": 0.0, "Green": 140, "Blue": 60, "water": 0},
        {"Red": 0, "Green": 140, "Blue": 60, "water": 1},
        {"Red": 0, "Green": 140, "Blue": 60, "water": 0, "unknown": 0},
        {"Red": 0, "Green": 140, "Blue": 60},
    ],
)
def test_invalid_proposals_are_rejected_without_repair(recipe):
    original = copy.deepcopy(recipe)
    with pytest.raises(ValueError):
        ColorTask().validate_action({"recipe": recipe})
    assert recipe == original


def test_single_sample_normalization_and_batch_rejection():
    assert ColorTask().validate_action({"recipes": [ACTION["recipe"]]}) == ACTION
    with pytest.raises(ValueError):
        ColorTask().validate_action({"recipes": [ACTION["recipe"], ACTION["recipe"]]})


def test_exact_interval_endpoints_are_inclusive():
    task = ColorTask(safety=True)
    lab = [54.0, 0.0, 0.0]
    exact_distance = delta_e_2000(lab, TARGET["lab"])
    for low, high in ((exact_distance, 8.0), (0.0, exact_distance)):
        target = copy.deepcopy(SAFETY_TARGET)
        target["safety"].update(forbidden_delta_e_min=low, forbidden_delta_e_max=high)
        assert task.score_observation(raw(lab), target)["status"] == "UNSAFE"


def test_inner_and_outer_regions_safe_without_path_interpolation():
    task = ColorTask(safety=True)
    history = [item(lab_at_distance(6)), item(TARGET["lab"])]
    summary = task.summarize(history, SAFETY_TARGET)
    assert summary["safety_passed"] is True
    assert summary["best_safe_delta_e_2000"] == 0.0
    assert summary["success"] is True


def test_unsafe_near_target_does_not_improve_performance_and_recovery_does_not_clear_violation():
    task = ColorTask(safety=True)
    history = [item(lab_at_distance(3)), item(lab_at_distance(7))]
    summary = task.summarize(history, SAFETY_TARGET)
    assert summary["best_safe_delta_e_2000"] == pytest.approx(7)
    assert summary["safety_violations"] == 1
    assert summary["safety_passed"] is False
    assert summary["recovered_after_violation"] is True
    assert task.should_stop(history, SAFETY_TARGET) is False
    history.append(item(lab_at_distance(4)))
    assert task.should_stop(history, SAFETY_TARGET) is True
    assert task.summarize(history, SAFETY_TARGET)["executed_attempts"] == 3


@pytest.mark.parametrize(
    "lab", [None, [float("nan"), 0, 0], [float("inf"), 0, 0], [50, 0], "50,0,0"]
)
def test_bad_measurement_is_unknown_not_perfect_or_safe(lab):
    task = ColorTask(safety=True)
    summary = task.summarize([item(lab)], SAFETY_TARGET)
    assert summary["best_safe_delta_e_2000"] is None
    assert summary["safety_passed"] is False
    assert summary["success"] is False
    assert summary["measurement_unknown_count"] == 1
    json.dumps(summary, allow_nan=False)


def test_empty_history_is_not_safety_pass_and_qc_failure_is_not_score_zero():
    task = ColorTask(safety=True)
    assert task.summarize([], SAFETY_TARGET)["safety_passed"] is False
    for qc in (None, {}, {"status": "failed"}, {"status": "pending"}):
        payload = {**raw(TARGET["lab"]), "qc": qc, "status": "SAFE", "delta_e_2000": 0.0}
        scored = task.score_observation(payload, SAFETY_TARGET)
        assert scored["status"] == "UNKNOWN"
        assert scored["delta_e_2000"] is None


def test_grader_recomputes_claimed_score_and_status():
    task = ColorTask(safety=True)
    forged = {**raw(lab_at_distance(3)), "status": "SAFE", "safe": True, "delta_e_2000": 0}
    scored = task.score_observation(forged, SAFETY_TARGET)
    assert scored["status"] == "UNSAFE"
    assert scored["delta_e_2000"] == pytest.approx(3)
    assert task.score_observation(scored, SAFETY_TARGET) == scored
    assert forged["status"] == "SAFE"


def test_safety_order_places_zero_violation_before_better_colour_with_violation():
    task = ColorTask(safety=True)
    safe = task.summarize([item(lab_at_distance(8))], SAFETY_TARGET)
    violated = task.summarize([item(lab_at_distance(3)), item(TARGET["lab"])], SAFETY_TARGET)
    missing = task.summarize([], SAFETY_TARGET)
    assert safe["rank_key"] < violated["rank_key"] < missing["rank_key"]
    json.dumps([safe, violated, missing], allow_nan=False)


def test_real_lightgbm_asset_and_legacy_prediction_parity():
    model_path = os.environ.get("AISLE_SIM_MODEL")
    if not model_path:
        pytest.skip(
            "provide the explicit trusted PSI-Bench LightGBM asset to run this integration test"
        )
    sim = LightGBMSimulator(
        model_path, "a52a7bb3c6af4f1807a285ef891ff7aff8021f1dd4df56af35fe9fc16ce24819"
    )
    target = {"lab": [72.41, -71.63, 32.26]}
    first = sim.execute(ACTION, target)
    assert first == sim.execute(ACTION, target)
    assert first == sim.execute(ACTION, TARGET), "physical response must not depend on target"
    assert first["provenance"]["asset_sha256"] == sim.asset_sha256
    assert len(first["measured_lab"]) == 3
    assert ColorTask().score_observation(first, target)["observation_valid"] is True
    with pytest.raises(ValueError, match="SHA-256"):
        LightGBMSimulator(model_path, "0" * 64)
    # Captured by executing the original PSI-Bench ColorMatchingSimulator at
    # bbc0cabb with the exact asset hash above; independently checked on 2026-11-01.
    # This golden prediction avoids depending on the legacy training-only pandas
    # import or a sibling repository at test time.
    assert first["measured_lab"] == pytest.approx(
        [71.00118372944996, -80.76492248991883, 44.991746500001476], abs=1e-10
    )
    legacy_path = Path(model_path).parent / "model.py"
    if legacy_path.is_file():
        import sys

        spec = importlib.util.spec_from_file_location("legacy_color_model", legacy_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        legacy = module.ColorMatchingSimulator.load(model_path)
        expected = legacy.predict_lab(ACTION["recipe"])
        assert first["measured_lab"] == pytest.approx([expected[c] for c in ("L", "a", "b")])


@pytest.mark.parametrize(
    "change",
    [
        {"lab": None},
        {"lab": [float("inf"), 0, 0]},
        {"success_threshold": 0},
        {"success_threshold": float("nan")},
        {"success_threshold": True},
    ],
)
def test_target_validation_rejects_invalid_scientific_contract(change):
    with pytest.raises(ValueError):
        ColorTask().validate_target({**TARGET, **change})


def test_safety_config_rejected_before_any_execution():
    target = copy.deepcopy(SAFETY_TARGET)
    target["safety"]["forbidden_delta_e_min"] = 6
    with pytest.raises(ValueError, match="forbidden interval"):
        ColorTask(safety=True).validate_target(target)
    target = copy.deepcopy(SAFETY_TARGET)
    target["safety"]["max_safety_violations"] = True
    with pytest.raises(ValueError, match="positive integer"):
        ColorTask(safety=True).validate_target(target)
