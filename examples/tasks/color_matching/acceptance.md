# Task acceptance record

Status: development task; scientific acceptance and laboratory readiness pending.

## Available engineering evidence

2026-11-01: `AISLE_SIM_MODEL=<trusted PSI-Bench asset> uv run pytest tests/ -q`
completed with 57 passing tests in 4.97 seconds under managed Python 3.12.11.
The test suite included actual pretrained LightGBM inference and direct original-code
prediction parity, task formula/constraint regressions, durable orders, budget and
idempotency, Agent/API separation and Top-K gates. See the adjacent
`../engineering-validation.json` for versions and exact simulator predictions.
Real-adapter tests used explicitly labeled engineering fixtures, not wet experiments.
Scientific simulator holdout validation and physical lab acceptance remain pending.

## Engineering gate

- [ ] Manifest schema and mandatory sim + real mapping pass.
- [ ] Legal and illegal actions are checked without modifying proposed recipes.
- [ ] CIEDE2000 reference pairs, exact forbidden boundaries, invalid measurements, recovery and termination tests pass.
- [ ] The existing trained LightGBM asset runs successfully; its hash and software versions are recorded.
- [ ] End-to-end Agent trajectory includes proposal, execution, scored feedback, next action and termination.
- [ ] Durable real work-order flow and duplicate-result handling pass without claiming a physical experiment occurred.

## Simulation scientific gate

- [ ] [Validation plan](validation/sim-validation-plan.json) freezes the [colour profile and full procedure](validation/README.md) before final testing; [validation report](validation/sim-validation-report.json) records actual results and evidence.
- [ ] Lab provides original calibration data with sample/batch identities and provenance.
- [ ] Training and holdout partitions are independently identified; repeated sample/batch leakage excluded.
- [ ] Predeclared independent validation measures error, action-domain coverage and optimization/ranking regions.
- [ ] Per-channel MAE/RMSE/R², domain error mean/P95, target-score errors, candidate-score ranking and success confusion counts/rates are reported with the required strata, denominators and uncertainty.
- [ ] Every applicable hard gate in the [sim verifier standard](../../../docs/sim-verifier-acceptance.zh-CN.md) passes; thresholds are justified by scientific tolerance, repeat noise, decision risk and sample size, rather than fitted to final-test outcomes.
- [ ] Thresholds, seeds, repeats, simulator/environment hashes and failure cases frozen.
- [ ] Reviewer accepts physical mapping, range restrictions and fitness for Sim Top-K selection.

A successful inference call or a low training error cannot satisfy this gate. Learned surrogate predictions outside validated scope cannot be presented as scientifically accepted experiments.

Current independent holdout results are unmeasured: the companion report keeps metric values `null`, not zero or pass. The numeric profile is an acceptance requirement, not observed LightGBM performance. R² is diagnostic and cannot replace domain-error, decision-fidelity or ranking gates. Insufficient stratum counts or undefined required metrics remain insufficient evidence; scoring-code tests separately establish formula and boundary correctness.

This task may merge as a G1 development example while retaining `review.status: draft`, `sim.validation_status: pending` and `real.readiness: pending`. G2 scientific acceptance requires the complete report and independent scientific sign-off; it does not follow from engineering CI.

## Real readiness gate

- [ ] All required SOP fields completed by the lab.
- [ ] Actual reference/QC experiments meet frozen criteria and raw data are inspectable.
- [ ] Independent repeats, batching, randomization and allowable deviations defined.
- [ ] Resource budget, operator role and factual feedback contract agreed.
- [ ] Sample/action/evidence mapping and failure/retry rules verified.
- [ ] Lab scientist and independent reviewer sign the readiness report.

## Real closed-loop / publication gate

- [ ] Sim Top-K eligibility frozen for this task and full model+harness version.
- [ ] A selected Agent decides again after receiving true new measurements; remeasuring its offline winner alone does not suffice.
- [ ] All physical consumption, invalid runs and human assistance retained.
- [ ] Predeclared repeat/statistical plan complete, raw evidence hashes and versions verified.
- [ ] Reviewer records scope, result, evidence links, date and remaining limitations.

No box is automatically checked by this template. Engineering test output should be linked as evidence with date and command; scientific/real gates remain unaccepted until the relevant laboratory evidence exists.
