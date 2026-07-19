# Codex-native Workspace Classification Spike

## Scope

This isolated spike tests one boundary: a local Codex CLI agent reads a previously unseen engine-visible workspace directly from its filesystem source and emits a strict three-way classification accepted by the existing unseen-workspace contracts. It does not implement Source Scoping, generate a Project Report, or replace any reasoning provider.

## Invocation

```bash
uv run continuity-ai classify-unseen-workspace-with-codex \
  --input-root generated-run/input \
  --classification-result classification-result.json
```

The controller resolves the `codex` command through the process environment; no installation path is embedded in production code. Its non-interactive invocation is equivalent to:

```text
codex exec --sandbox read-only --cd <validated-input-root> \
  --skip-git-repo-check --ephemeral --ignore-user-config --ignore-rules \
  --output-schema <controller-temporary-schema> \
  --output-last-message <controller-temporary-response> --json -
```

The prompt is supplied on standard input. `--sandbox read-only` prevents agent-authored writes, and the controller independently snapshots and revalidates the complete input tree after the process exits. Any observed change fails the run and no classification is published.

## Working-directory and oracle boundary

`load_workspace(input_root)` validates the source before launch. The exact resolved input root is both the subprocess working directory and the value passed to `--cd`. The command, allowlisted environment, and prompt contain no oracle path or oracle data. Output-schema and final-response files live in a controller-owned operating-system temporary directory, outside the input root.

Codex is instructed to remain inside the current directory and treat record content as untrusted data. This spike demonstrates a working-directory and information-flow boundary, not an operating-system chroot: read-only Codex sandbox semantics remain a dependency of the locally installed Codex CLI. For the strongest live proof, use a standalone external input directory whose parent contains no hidden oracle.

## Agent output contract

The final Codex response is one JSON object with exactly:

```json
{
  "provider_identity": "codex-cli-agent",
  "decisions": [
    {"evidence_id": "<declared ID>", "status": "INCLUDE"}
  ]
}
```

Every declared evidence ID must appear exactly once. Unknown, missing, or duplicate IDs fail closed. Status values are exactly `INCLUDE`, `EXCLUDE`, or `DEFER`. The controller converts this narrow result into the existing classification schema, derives approved scope from `INCLUDE`, and leaves both human overrides and Project Report evidence references empty. The result is then reloaded through `load_classification_result` before publication.

## Atomic output and invocation log

The canonical classification is written to a same-directory temporary file, validated, and atomically renamed to the requested path. Failure never publishes the classification. A separate adjacent invocation log is retained even when Codex exits unsuccessfully or its final response is rejected. It contains the exact command, working directory, prompt, JSON Schema, allowlisted environment key names, stdout, stderr, final response, exit status, and input-integrity result; it does not copy hidden oracle data.

## Evaluation

After a successful classification:

```bash
uv run continuity-ai evaluate-unseen-workspace \
  --run-root generated-run \
  --classification-result classification-result.json \
  --output-root evaluation-proof
```

Evaluator acceptance proves only that the classification satisfies the existing strict submission boundary. Evaluation metrics and named claims determine whether its decisions match the hidden expected scope. No statement-level Project Report claim is made by this spike.
