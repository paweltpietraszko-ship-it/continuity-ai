# continuity-ai
An evidence-grounded continuity layer that reconstructs project state from scattered artifacts, detects where the project contradicts itself, and recommends the next action.


## Gate G-01 fixture generation

Install dependencies and generate the deterministic Project Aurora fixture with:

```bash
uv run continuity-ai generate-aurora-fixture --output-root .
```

The command creates the local scenario artifacts under `fixtures/project_aurora/generated/`, including EML, ICS, XLSX, PDF, Markdown, and test-only JSON ground truth files. The generated directory is intentionally ignored by Git because these artifacts are reproducible outputs, not source files.
