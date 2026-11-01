"""Run/order-ledger acceptance tests, using explicit engineering-only fixtures."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from aisle.contracts import TaskManifest
from aisle.engine import Engine
from aisle.store import Store

ACTION = {"recipe": {"Red": 0, "Green": 140, "Blue": 60, "water": 0}}
OTHER_ACTION = {"recipe": {"Red": 1, "Green": 139, "Blue": 60, "water": 0}}


def result_for(order, lab=None, sample="sample-1", passed=True):
    return {
        "recipe": order["action"]["recipe"],
        "measured_lab": lab if lab is not None else [72.41, -71.63, 32.26],
        "sample_id": sample,
        "qc": {"status": "passed" if passed else "failed"},
        "provenance": {"kind": "real"},
    }


def eligible_run(engine, manifest_factory, agent_factory):
    path = manifest_factory(official=True)
    agent = agent_factory()
    campaign = engine.create_campaign(path, [agent], 1)
    sim, _ = engine.create_run(path, agent, campaign_id=campaign["id"])
    engine.submit(sim["id"], ACTION, "sim-1")
    engine.finish(sim["id"])
    selection = engine.select([sim["id"]], 1)
    real, token = engine.create_run(
        path, agent, mode="real", selection_id=selection["id"], source_run_id=sim["id"]
    )
    return path, agent, sim, selection, real, token


def test_manifest_requires_sim_and_real_and_consistent_scoring(manifest_factory):
    path = manifest_factory()
    payload = json.loads(path.read_text())
    for field in ("sim", "real"):
        incomplete = copy.deepcopy(payload)
        del incomplete[field]
        with pytest.raises(ValidationError):
            TaskManifest.model_validate(incomplete)
    payload["metric"]["success_threshold"] = 5
    with pytest.raises(ValidationError, match="success_threshold"):
        TaskManifest.model_validate(payload)


def test_invalid_action_does_not_consume_budget(engine, manifest_factory, agent_factory):
    run, _ = engine.create_run(manifest_factory(), agent_factory())
    bad = {"recipe": {"Red": 0, "Green": 140, "Blue": 60, "water": 1}}
    with pytest.raises(ValueError):
        engine.submit(run["id"], bad, "invalid")
    with pytest.raises(SchemaError):
        engine.submit(run["id"], {"recipe": {}}, "empty")
    saved = engine.store.read("runs", run["id"])
    assert saved["attempts"] == 0
    assert saved["cost"]["proposed_samples"] == 0
    assert engine.store.list("orders") == []


def test_minimum_of_round_and_sample_budget_is_enforced(engine, manifest_factory, agent_factory):
    run, _ = engine.create_run(manifest_factory(rounds=3, samples=1), agent_factory())
    engine.submit(run["id"], ACTION, "one")
    assert engine.state(run["id"])["status"] == "completed"
    with pytest.raises(ValueError):
        engine.submit(run["id"], OTHER_ACTION, "two")
    assert len(engine.state(run["id"])["history"]) == 1


def test_concurrent_duplicate_proposal_executes_once(tmp_path, manifest_factory, agent_factory):
    calls = 0
    lock = Lock()

    class Counter:
        def execute(self, action, target):
            nonlocal calls
            with lock:
                calls += 1
            return {
                "recipe": action["recipe"],
                "measured_lab": target["lab"],
                "qc": {"status": "passed"},
                "provenance": {"kind": "sim"},
            }

    engine = Engine(Store(tmp_path / "concurrent"), simulator_factory=lambda manifest: Counter())
    run, _ = engine.create_run(manifest_factory(), agent_factory())
    with ThreadPoolExecutor(max_workers=6) as pool:
        orders = list(pool.map(lambda _: engine.submit(run["id"], ACTION, "stable-key"), range(6)))
    assert len({order["id"] for order in orders}) == 1
    assert calls == 1
    assert engine.store.read("runs", run["id"])["attempts"] == 1
    with pytest.raises(ValueError, match="different action"):
        engine.submit(run["id"], OTHER_ACTION, "stable-key")


def test_measurement_redelivery_is_idempotent_and_evidence_immutable(
    engine, manifest_factory, agent_factory
):
    _, _, _, _, run, _ = eligible_run(engine, manifest_factory, agent_factory)
    order = engine.submit(run["id"], ACTION, "physical-1")
    engine.transition(order["id"], "executing", "operator")
    raw = result_for(order)
    complete = engine.complete(order["id"], raw, "operator", [b"raw-spectrum-fixture"])
    again = engine.complete(order["id"], raw, "operator", [b"raw-spectrum-fixture"])
    assert again == complete
    assert engine.state(run["id"])["cost"]["physical_samples"] == 1
    assert len(engine.state(run["id"])["history"]) == 1
    assert all((engine.store.root / e["path"]).is_file() for e in complete["evidence"])
    changed = {**raw, "measured_lab": [70, 0, 0]}
    with pytest.raises(ValueError, match="immutable"):
        engine.complete(order["id"], changed, "operator", [b"different spectrum"])


def test_checkpoint_cannot_modify_score_or_budget(engine, manifest_factory, agent_factory):
    run, _ = engine.create_run(manifest_factory(), agent_factory())
    engine.submit(run["id"], ACTION, "one")
    before = engine.store.read("runs", run["id"])
    engine.checkpoint(run["id"], {"summary": {"best_score": -999}, "attempts": 0, "history": []})
    after = engine.store.read("runs", run["id"])
    assert after["summary"] == before["summary"]
    assert after["history"] == before["history"]
    assert after["attempts"] == before["attempts"]


def test_non_topk_agent_and_changed_agent_cannot_create_real_run(
    engine, manifest_factory, agent_factory
):
    path = manifest_factory(official=True)
    runs = []
    campaign = engine.create_campaign(path, [agent_factory("a"), agent_factory("b")], 1)
    for name in ("a", "b"):
        run, _ = engine.create_run(path, agent_factory(name), campaign_id=campaign["id"])
        engine.submit(run["id"], ACTION, "one")
        engine.finish(run["id"])
        runs.append(run)
    selection = engine.select([run["id"] for run in runs], 1)
    excluded = next(run for run in runs if run["id"] not in selection["selected"])
    with pytest.raises(ValueError, match="not in an official Top-K"):
        engine.create_run(
            path,
            agent_factory(excluded["agent"]["agent_id"]),
            mode="real",
            selection_id=selection["id"],
            source_run_id=excluded["id"],
        )
    chosen = next(run for run in runs if run["id"] in selection["selected"])
    with pytest.raises(ValueError, match="complete agent"):
        engine.create_run(
            path,
            agent_factory(chosen["agent"]["agent_id"], harness="tools"),
            mode="real",
            selection_id=selection["id"],
            source_run_id=chosen["id"],
        )


def test_unaccepted_task_and_engineering_selection_cannot_enter_real(
    engine, manifest_factory, agent_factory
):
    path = manifest_factory()
    agent = agent_factory()
    campaign = engine.create_campaign(path, [agent], 1)
    run, _ = engine.create_run(path, agent, campaign_id=campaign["id"])
    engine.submit(run["id"], ACTION, "one")
    engine.finish(run["id"])
    with pytest.raises(ValueError, match="scientific simulation acceptance"):
        engine.select([run["id"]], 1)
    selection = engine.select([run["id"]], 1, engineering_only=True)
    with pytest.raises(ValueError, match="not in an official Top-K"):
        engine.create_run(
            path, agent, mode="real", selection_id=selection["id"], source_run_id=run["id"]
        )


def test_different_versions_cannot_share_selection(engine, manifest_factory, agent_factory):
    runs = []
    for i, version in enumerate(("v1", "v2")):
        run, _ = engine.create_run(
            manifest_factory(version=version, name=version), agent_factory(f"a{i}")
        )
        engine.submit(run["id"], ACTION, "one")
        engine.finish(run["id"])
        runs.append(run["id"])
    with pytest.raises(ValueError, match="same frozen task"):
        engine.select(runs, 1, engineering_only=True)


def test_sop_mutation_invalidates_real_transfer(engine, manifest_factory, agent_factory):
    path, agent, sim, selection, _, _ = eligible_run(engine, manifest_factory, agent_factory)
    (path.parent / "SOP.md").write_text("changed operation")
    with pytest.raises(ValueError, match="revision"):
        engine.create_run(
            path, agent, mode="real", selection_id=selection["id"], source_run_id=sim["id"]
        )


def test_failed_qc_pauses_without_zero_score_or_automatic_retry(
    engine, manifest_factory, agent_factory
):
    _, _, _, _, run, _ = eligible_run(engine, manifest_factory, agent_factory)
    order = engine.submit(run["id"], ACTION, "one")
    engine.transition(order["id"], "executing", "operator")
    raw = result_for(order, passed=False)
    engine.complete(order["id"], raw, "operator", [b"bad-instrument-output"])
    state = engine.state(run["id"])
    assert state["status"] == "qc_review"
    assert state["summary"]["best_score"] is None
    assert state["cost"]["physical_samples"] == 1
    with pytest.raises(ValueError):
        engine.submit(run["id"], ACTION, "retry")
    with pytest.raises(ValueError):
        engine.finish(run["id"])


def test_execution_uncertain_requires_explicit_reconciliation(
    engine, manifest_factory, agent_factory
):
    run, _ = engine.create_run(manifest_factory(), agent_factory(), mode="rehearsal")
    order = engine.submit(run["id"], ACTION, "one")
    engine.transition(order["id"], "executing", "operator")
    engine.transition(order["id"], "execution_uncertain", "operator")
    with pytest.raises(ValueError, match="reconcile"):
        engine.complete(order["id"], result_for(order), "operator")
    with pytest.raises(ValueError):
        engine.submit(run["id"], ACTION, "retry")
    engine.transition(order["id"], "measurement_pending", "reconciler")
    engine.complete(order["id"], result_for(order), "operator")
    assert len(engine.state(run["id"])["history"]) == 1


def test_cancelled_order_cannot_trigger_physical_resubmission(
    engine, manifest_factory, agent_factory
):
    run, _ = engine.create_run(manifest_factory(), agent_factory(), mode="rehearsal")
    order = engine.submit(run["id"], ACTION, "one")
    engine.transition(order["id"], "cancelled", "operator")
    assert engine.state(run["id"])["status"] == "cancelled"
    assert engine.state(run["id"])["pending_order"] is None
    with pytest.raises(ValueError):
        engine.submit(run["id"], ACTION, "retry")


def test_same_sample_cannot_be_counted_as_two_independent_preparations(
    engine, manifest_factory, agent_factory
):
    _, _, _, _, run, _ = eligible_run(engine, manifest_factory, agent_factory)
    first = engine.submit(run["id"], ACTION, "one")
    engine.transition(first["id"], "executing", "operator")
    engine.complete(first["id"], result_for(first), "operator", [b"one raw file"])
    second = engine.submit(run["id"], OTHER_ACTION, "two")
    engine.transition(second["id"], "executing", "operator")
    with pytest.raises(ValueError, match="sample"):
        engine.complete(second["id"], result_for(second), "operator", [b"same sample read"])
    assert engine.state(run["id"])["cost"]["physical_samples"] == 1


def test_official_selection_requires_preregistered_campaign(
    engine, manifest_factory, agent_factory
):
    path = manifest_factory(official=True)
    run, _ = engine.create_run(path, agent_factory())
    engine.submit(run["id"], ACTION, "one")
    engine.finish(run["id"])
    with pytest.raises(ValueError, match="preregistered campaign"):
        engine.select([run["id"]], 1)


def test_campaign_rejects_changed_k_incomplete_cohort_nonmember_and_duplicate_run(
    engine, manifest_factory, agent_factory
):
    path = manifest_factory(official=True)
    agents = [agent_factory("a"), agent_factory("b")]
    campaign = engine.create_campaign(path, agents, 1)
    with pytest.raises(ValueError, match="frozen campaign"):
        engine.create_run(path, agent_factory("outsider"), campaign_id=campaign["id"])
    runs = []
    for agent in agents:
        run, _ = engine.create_run(path, agent, campaign_id=campaign["id"])
        engine.submit(run["id"], ACTION, "one")
        engine.finish(run["id"])
        runs.append(run["id"])
    with pytest.raises(ValueError, match="already has a run"):
        engine.create_run(path, agents[0], campaign_id=campaign["id"])
    with pytest.raises(ValueError, match="preregistered K"):
        engine.select(runs, 2)
    with pytest.raises(ValueError, match="complete frozen cohort"):
        engine.select(runs[:1], 1)
    selected = engine.select(runs, 1)
    assert selected["campaign_id"] == campaign["id"]
    assert len(selected["selected"]) == 1
