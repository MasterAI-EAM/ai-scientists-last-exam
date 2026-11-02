# Task acceptance record

Task: `my_color_task` · Version: `0.1.0-draft` · Status: **incomplete**.

Machine validation of this template does not constitute scientific acceptance. Unfilled fields and missing original measurements block official task admission.

Required companion files in this directory: [sim-validation-plan.json](sim-validation-plan.json) and [sim-validation-report.json](sim-validation-report.json). Follow the [sim verifier standard](https://github.com/nlz25/ai-scientists-last-exam/blob/main/docs/sim-verifier-acceptance.zh-CN.md) and [complete colour example](https://github.com/nlz25/ai-scientists-last-exam/blob/main/examples/tasks/color_matching/validation/README.md). The colour profile contains task-specific numeric requirements; a new scientific task needs a justified profile of its own.

## Frozen scope and criteria

- Scientific objective / supported laboratory and conditions: TODO.
- Action and measurement mappings between sim and real: TODO.
- Data splits, independent sample/batch counts and leakage checks: TODO.
- Simulator error metrics, numeric tolerances and uncertainty method: TODO.
- Scientific tolerance, repeated-measurement noise, decision risk and sample-size justification for each hard gate: TODO.
- Per-output MAE/RMSE/R² and domain error mean/P95; candidate-score ranking for optimization; success confusion counts/rates; false-safe rate and confidence bound for constraint tasks: TODO. Record explicit reasons for inapplicable metrics.
- Boundary/high-score/near-success-threshold coverage: TODO.
- Reference experimental protocol, controls and QC limits: TODO.
- Repetitions, invalid-result policy, redo cap and budget accounting: TODO.
- Candidate selection policy, K, ties and Agent configuration binding: TODO.
- Freeze date, task/schema/asset/SOP/verifier hashes: TODO.

Freeze the plan before final testing. R² is a required diagnostic for a numerical surrogate, not a standalone acceptance gate. Scoring formulas require controls, exact-boundary and invalid-measurement tests. Do not change a threshold after seeing final-test outcomes; a changed model, scope or gate needs a new frozen version and untouched final-test evidence.

## Gate decisions

| Gate | Actual result | Evidence URI + SHA-256 | Reviewer and date | Decision |
|---|---|---|---|---|
| G0 scientific scope + sim feasibility + wet-real feasibility | TODO | TODO | TODO | pending |
| G1 engineering package and contract checks | TODO | TODO | TODO | pending |
| G2 independent simulator scientific validation | TODO | TODO | TODO | pending |
| G3 laboratory readiness and reference experiment | TODO | TODO | TODO | pending |
| G4 shortlisted Agent real closed loop | TODO | TODO | TODO | pending |
| G5 publication evidence, repetitions, statistics and limitations | TODO | TODO | TODO | pending |

## Evidence rules

Record raw file and processed output separately. Each actual physical result needs action/sample/batch identifiers, timestamp, instrument and SOP versions, QC, and operator/intervention records. Distinguish independent preparations from repeated readings. An empty measurement or failed QC is not a valid zero score.

Before measurement, report metric values as `null` with a pending reason. Preserve numerator/denominator counts, per-stratum results and uncertainty in the final report. Zero observed errors with a nonzero denominator is different from having no relevant samples. A missing, undefined or underpowered required estimate cannot pass G2. One good metric cannot compensate for another failed gate.

Simulator development/reference/QC experiments have a separate budget. Formal Agent real evaluation is restricted to frozen sim Top-K. Testing file import or using synthetic measurements proves software behavior only.

G1 permits a complete development package to merge with `review.status: draft`, `sim.validation_status: pending` and `real.readiness: pending`. G2 requires independent laboratory evidence meeting every mandatory numeric gate and scientific sign-off; G3 separately requires laboratory readiness. Neither decision follows automatically from file/schema checks or CI.

## Remaining limitations and sign-off

- Unresolved scientific limitations: TODO.
- Supported scope and excluded conditions: TODO.
- Laboratory scientific owner: TODO.
- Platform engineering reviewer: TODO.
- Independent scientific reviewer (not the main task author): TODO.
- Decision and date: pending.
