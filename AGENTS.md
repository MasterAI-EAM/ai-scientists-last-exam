# AISLE development rules

- Use uv; run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`.
- Every contributed task requires both simulation and an executable wet-lab mapping.
- Only frozen simulation Top-K agents may enter official real evaluations.
- Humans execute the fixed SOP and return measurements; scientific interventions are logged.
- Never equate engineering tests with scientific acceptance or real physical validation.
- Persist physical work orders and evidence outside disposable agent sandboxes.
- Never retry an ambiguously executed physical action without reconciliation.
- Do not commit credentials, private experimental data, model bundles, or live run tokens.
- The source PSI-Bench repository is read-only; do not modify its core or user configuration.
