# Diagnostic Proof Core v0.1

Base: `ff1ca167986596d7676e971cd680bd5d43ee6277`

## Outcome

`continuity_ai.diagnostic_proof` is an isolated diagnostic orchestrator around the existing unseen-workspace generator, production mixed-to-approved lifecycle, and independent oracle evaluator. It does not introduce a classifier, alternate pipeline, provider fallback, UI, or changes to existing contracts.

The public flow has four explicit phases:

1. `prepare_diagnostic_workspace(run_root, seed)` creates a temporary generated evaluation run, fingerprints its input, copies only that input into standalone `engine/input`, and deletes the complete temporary evaluation tree before publishing the workspace. The returned controller object retains the seed and generated-input fingerprint in memory; the published run tree contains only `engine/`.
2. `run_diagnostic_engine(controller, input_root, approved_workspace_root, review)` accepts only the standalone engine input root. It receives no seed, run root, oracle path, or future evaluation path. Oracle-free filesystem checkpoints surround both existing Codex process calls while the existing production lifecycle remains unchanged.
3. `regenerate_diagnostic_evaluation(workspace, completed)` is callable only with a completed engine result. It first proves the run tree still contains no oracle artifacts, regenerates the seed into a fresh `evaluation/` directory, and requires the preparation, standalone, completed-run, and regenerated fingerprints to agree before returning the evaluation workspace.
4. `evaluate_completed_diagnostic_run(completed, evaluation)` accepts only that verified post-engine regeneration and delegates hidden-status evaluation to `evaluate_generated_run`.

The engine result cannot be constructed by the package until reporting has completed. It records the initial input fingerprint, oracle-absence checkpoint result, controller ID, investigation Codex ID, reporting Codex ID, automatic decisions, explicit human overrides, approved/excluded partitions, materialization receipt, and reported approved-workspace paths.

## Proof output

`write_diagnostic_reports` atomically writes `report.json` and `report.md` from one immutable `DiagnosticProofReport`. Both views include:

- seed;
- engine input fingerprint;
- controller session ID;
- retained Codex session ID;
- every diagnostic and oracle claim with `PASS` or `FAIL`;
- overall `PASS` or `FAIL`.

Diagnostic claims add lifecycle and filesystem evidence to the existing oracle claims:

| Claim | Evidence |
|---|---|
| `INPUT_FINGERPRINT_UNCHANGED` | Recomputed standalone input fingerprint equals the pre-investigation fingerprint. |
| `ENGINE_INPUT_PHYSICALLY_ISOLATED_FROM_ORACLE` | Standalone engine input and the post-engine regenerated evaluation tree are distinct and non-nested. |
| `ORACLE_ABSENT_DURING_ENGINE_EXECUTION` | Preparation removed the complete temporary evaluation tree; engine checkpoints passed before and after both Codex calls; regeneration observed no oracle before creating the fresh evaluation tree. |
| `ENGINE_INPUT_MATCHES_GENERATED_INPUT` | Preparation, standalone engine input, completed-run input, and post-engine regenerated input fingerprints all agree. |
| `SAME_CODEX_SESSION_ID` | Investigation and approved-workspace reporting retain the identical Codex ID. |
| `APPROVED_WORKSPACE_FINGERPRINT_MATCH` | Recomputed approved-workspace fingerprint equals the materialization receipt. |
| `APPROVED_WORKSPACE_EXACT_PARTITION` | The manifest is unique and equal to the approved evidence set; physical artifact paths and hashes match it exactly. |
| `EXCLUDED_OUTSIDE_APPROVED_WORKSPACE` | No excluded evidence ID occurs in the approved manifest. |
| `PROJECT_REPORT_PATHS_MATCH_APPROVED_SCOPE` | Reporting returns exactly the approved artifact paths, with no duplicates. |

The existing evaluator contributes its complete named claim set, including `EXACT_PARTITION_INTEGRITY`, `ORACLE_NOT_PRESENT_IN_ENGINE_INPUT`, `ORACLE_STATUS_MATCH`, approved-scope integrity, ambiguity deferral, and evidence-reference validity. Overall PASS requires every diagnostic claim and the complete existing oracle proof to pass.

## Controlled failure

`apply_controlled_workspace_tamper(completed)` is an explicit diagnostic-only operation. It changes one approved artifact after successful reporting. The independent evaluator then returns FAIL for both the approved-workspace fingerprint and exact physical partition claims while preserving the original materialization receipt as the expected state. It never changes an engine decision, production pipeline function, or oracle.

## Test coverage

Tests under `tests/diagnostic_proof/` cover:

- complete passing flows for three unrelated seeds;
- absence of fixture project names in production diagnostic logic;
- complete removal of the temporary evaluation tree before engine execution;
- direct pre-launch and instrumented process-launch proof that no oracle directory or payload exists;
- post-engine regeneration of the oracle in a fresh directory;
- byte-identical regenerated and standalone inputs plus evaluator detection of later divergence;
- exact automatic decision partition;
- physical absence of excluded artifacts from the approved workspace;
- one retained Codex ID across investigation and reporting;
- controlled post-completion tamper producing FAIL;
- byte-identical standalone input and identical fingerprint for the same seed;
- required JSON/Markdown identity and claim fields;
- a real local Codex live flow, guarded by the repository's `live_network` marker.

## Validation

The final validation commands and results are recorded here after the implementation run:

```text
uv run pytest -q tests/diagnostic_proof
10 passed, 1 deselected in 6.01s

uv run pytest -q
572 passed, 5 skipped, 4 deselected in 73.01s

uv run pytest --force-enable-socket -m live_network \
  tests/diagnostic_proof/test_diagnostic_proof_live.py -q
1 passed in 63.28s

uv run python -m compileall -q src tests
PASS

git diff --check
PASS
```
