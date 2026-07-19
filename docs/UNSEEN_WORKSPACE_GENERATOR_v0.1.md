# Unseen Workspace Generator v0.1

This checkpoint provides neutral infrastructure for testing project source scoping. It does not classify records and is not connected to Source Scoping, Bridge, Vault, desktop code, or a model provider.

## Generate a deterministic run

Run the repository CLI with an explicit integer seed and a new output directory:

```bash
uv run continuity-ai generate-unseen-workspace --seed 314159 --output-root generated-run
```

The output directory must not already exist. Reusing the same seed in separate output directories produces byte-identical files and the same semantic workspace. A different seed changes opaque evidence identifiers, project names, people, locations, dates, relationships, record filenames, and record order. The generator version is recorded with the seed in hidden metadata so a run can be reproduced deliberately.

## Security boundary

The generated layout is:

```text
generated-run/
  input/
    workspace.json
    records/
      record-<opaque-id>.txt
      record-<opaque-id>.md
      record-<opaque-id>.json
  oracle/
    expected_scope.json
    metadata.json
```

Only `generated-run/input/` is engine-visible. It contains the selected target project, opaque evidence identifiers, record paths, formats, checksums, and raw semantic content. It contains no seed, oracle path, expected status, scenario tag, or answer-bearing filename/identifier convention.

`generated-run/oracle/` is evaluation-only. `expected_scope.json` maps evidence identifiers to the hidden `include`, `exclude`, or `defer` expectation. `metadata.json` records the seed and generated entities for test reproducibility.

Production analysis must never receive the run root or either oracle file. Giving an engine the oracle would leak the expected answer and invalidate the generalization test. The raw loader therefore accepts only the `input/` directory, requires its exact closed layout, rejects traversal and symlink indirection, and never scans or resolves its parent.

Prompt-injection language deliberately appears in one generated record. It is untrusted record content: the generator writes it as inert text, the loader returns it as inert text, and the evaluator never interprets it as an instruction.

## Load engine-visible input

```python
from pathlib import Path

from continuity_ai.unseen_workspace import load_workspace

workspace = load_workspace(Path("generated-run/input"))
print(workspace.target_project.name)
print(len(workspace.records))
```

Supported record formats are UTF-8 `.txt`, `.md`, and strict-schema `.json`. Referenced or unreferenced unsupported files, malformed JSON, empty content, duplicate evidence identities, undeclared files, checksum mismatches, traversal, and links fail closed.

## Evaluate a later classification

A later classifier may write this independent result contract:

```json
{
  "schema_version": 1,
  "decisions": [
    {"evidence_id": "EV-OPAQUE", "status": "defer"}
  ]
}
```

Invoke the evaluator explicitly with the hidden oracle and the later result:

```bash
uv run continuity-ai evaluate-unseen-workspace \
  --expected-scope generated-run/oracle/expected_scope.json \
  --classification-result classification-result.json
```

The callable form is `evaluate_scope(expected_scope_path, classification_result)`, with JSON results loaded by `load_classification_result(path)`. The report includes classified/total records, records classified exactly once, valid/total evidence references, invalid references, unsafe automatic inclusions, correctly deferred/total ambiguous records, and exact status matches.

An automatic `include` is unsafe when the hidden expectation is `exclude` or `defer`. Duplicate and unknown identifiers remain representable in the result so the evaluator can report them instead of silently normalizing them away.
