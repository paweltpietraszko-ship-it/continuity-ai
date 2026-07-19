# continuity-ai
An evidence-grounded continuity layer that reconstructs project state from scattered artifacts, detects where the project contradicts itself, and recommends the next action.


## Gate G-01 fixture generation

Install dependencies and generate the deterministic Project Aurora fixture with:

```bash
uv run continuity-ai generate-aurora-fixture --output-root .
```

The command creates local scenario artifacts under `fixtures/project_aurora/generated/artifacts/` and test-only ground truth under `fixtures/project_aurora/generated/test_only/ground_truth.json`. The generated directory is intentionally ignored by Git because these artifacts are reproducible outputs, not source files. Production reasoning must receive only `fixtures/project_aurora/generated/artifacts/`.

## Unseen Workspace Generator v0.1

Generate an unseen mixed workspace with an explicit seed:

```bash
uv run continuity-ai generate-unseen-workspace --seed 314159 --output-root generated-run
```

Only `generated-run/input/` is engine-visible. Hidden expectations and seed metadata remain under `generated-run/oracle/`.

Evaluate a later classification and atomically emit equivalent machine-readable JSON and demo-suitable Markdown from one canonical report:

```bash
uv run continuity-ai evaluate-unseen-workspace \
  --run-root generated-run \
  --classification-result classification-result.json \
  --output-root evaluation-proof
```

The evaluator emits `evaluation-proof/report.json` and `evaluation-proof/report.md` and prints the Markdown proof. Stable named claims include `EXACT_PARTITION_INTEGRITY`, `CITATION_VALIDITY`, `NO_UNSAFE_AUTOMATIC_INCLUSIONS`, `AMBIGUOUS_RECORDS_DEFERRED_TO_HUMAN_REVIEW`, `HUMAN_OVERRIDES_ACCOUNTED`, `APPROVED_SCOPE_INTEGRITY`, `PROJECT_REPORT_USES_APPROVED_SCOPE_ONLY`, and `ORACLE_NOT_PRESENT_IN_ENGINE_INPUT`.

See [Unseen Workspace Generator and Machine-Evaluable Proof v0.1](docs/UNSEEN_WORKSPACE_GENERATOR_v0.1.md) for contracts, exact claim meanings, architecture, and the proof matrix.

## License

Apache License 2.0. See `LICENSE`.
