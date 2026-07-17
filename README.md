# continuity-ai
An evidence-grounded continuity layer that reconstructs project state from scattered artifacts, detects where the project contradicts itself, and recommends the next action.


## Gate G-01 fixture generation

Install dependencies and generate the deterministic Project Aurora fixture with:

```bash
uv run continuity-ai generate-aurora-fixture --output-root .
```

The command creates local scenario artifacts under `fixtures/project_aurora/generated/artifacts/` and test-only ground truth under `fixtures/project_aurora/generated/test_only/ground_truth.json`. The generated directory is intentionally ignored by Git because these artifacts are reproducible outputs, not source files. Production reasoning must receive only `fixtures/project_aurora/generated/artifacts/`.

## License

Apache License 2.0. See `LICENSE`.
