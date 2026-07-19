# Unseen Workspace Generator and Machine-Evaluable Proof v0.1

This checkpoint provides neutral infrastructure for testing project source scoping. It generates an unseen mixed workspace, loads only engine-visible input, and evaluates a later classification submission against a physically separated oracle. It does not classify records and is not connected to Source Scoping, Bridge, Vault, desktop code, Project Report generation, or a model provider.

## Generate a deterministic unseen run

```bash
uv run continuity-ai generate-unseen-workspace --seed 314159 --output-root generated-run
```

The seed is mandatory and the output root must not exist. The same seed produces byte-identical files and the same semantics. Different seeds change project names, people, locations, dates, evidence IDs, relationships, filenames, and record order. Independent deterministic sub-seeds isolate semantic construction from layout, so serialization changes cannot silently change project relationships.

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

Only `generated-run/input/` is engine-visible. It contains no seed, expected status, scenario tag, oracle path, or answer-bearing filename/identifier convention. `generated-run/oracle/` is evaluation-only. Production analysis must never receive the run root or either oracle file.

The raw loader accepts only the `input/` directory, requires its exact closed layout, verifies checksums and strict schemas, rejects path traversal, symbolic links, Windows junctions, undeclared files, malformed JSON, empty records, duplicate identities, and unsupported formats, and never scans its parent.

Prompt-injection language deliberately appears in one generated record. It remains untrusted text: the generator writes it, the loader returns it, and the evaluator never executes or interprets it as an instruction.

## Classification submission contract

The evaluator accepts one explicit later-stage submission:

```json
{
  "schema_version": 1,
  "provider_identity": "source-scoping-provider-and-model-id",
  "decisions": [
    {"evidence_id": "EV-OPAQUE", "status": "defer"}
  ],
  "human_overrides": [
    {"evidence_id": "EV-OPAQUE", "status": "include"}
  ],
  "approved_scope_evidence_ids": ["EV-OPAQUE"],
  "project_report_evidence_ids": ["EV-OPAQUE"]
}
```

`provider_identity` is a declared identity and is reported exactly; this evaluator does not claim cryptographic provider attestation. Automatic decisions use `include`, `exclude`, or `defer`. A human override may resolve only an automatically deferred record and must resolve it to `include` or `exclude`. Approved scope must equal final `include` decisions after valid overrides. The submitted `project_report_evidence_ids` declaration must be a subset of approved scope.

## Emit equivalent JSON and Markdown proof

```bash
uv run continuity-ai evaluate-unseen-workspace \
  --run-root generated-run \
  --classification-result classification-result.json \
  --output-root evaluation-proof
```

The output root must not exist. The command atomically writes:

```text
evaluation-proof/
  report.json
  report.md
```

Both files are rendered from the same immutable `EvaluationReport`. `report.json` is the machine-readable result. `report.md` is the human-readable and demo-video result. The CLI also prints the complete Markdown proof so every claim and metric is visible in a terminal recording.

The callable contracts are:

- `evaluate_generated_run(run_root, classification_result) -> EvaluationReport`
- `render_evaluation_json(report) -> str`
- `render_evaluation_markdown(report) -> str`
- `write_evaluation_reports(report, output_root) -> EvaluationReportArtifacts`

## Product invariant: EXACT_PARTITION_INTEGRITY

PASS requires every oracle record to have exactly one automatic decision and requires zero automatic decisions referencing unknown records. The report exposes total records, classified records, and records classified exactly once.

## Product invariant: EVIDENCE_REFERENCE_VALIDITY

PASS requires every evidence ID referenced by automatic decisions, human overrides, approved scope, and the declared Project Report reference set to exist in the generated workspace. The report exposes valid/total references and every invalid identity. This proves evidence-reference validity only; it does not prove statement-level citations, span ownership, or report-statement binding.

## Product invariant: NO_UNSAFE_AUTOMATIC_INCLUSIONS

PASS requires zero automatic `include` decisions for records whose hidden expectation is `exclude` or `defer`, and zero unknown records automatically included. Every unsafe evidence ID is reported.

## Product invariant: AMBIGUOUS_RECORDS_DEFERRED_TO_HUMAN_REVIEW

PASS requires every hidden ambiguous record to receive exactly one automatic `defer` decision. The report exposes deferred/total ambiguity and every ambiguous record not deferred.

## Product invariant: HUMAN_OVERRIDES_ACCOUNTED

PASS requires each human override to be unique, reference a valid record, and resolve a record whose one automatic decision was `defer`. The report exposes all overrides and invalid override identities.

## Product invariant: APPROVED_SCOPE_INTEGRITY

PASS requires the submitted approved scope to have no duplicates and equal the final `include` partition after valid human overrides. The report exposes approved evidence IDs and approved scope size.

## Product invariant: DECLARED_PROJECT_REPORT_REFERENCES_WITHIN_APPROVED_SCOPE

PASS requires every evidence ID in the submitted `project_report_evidence_ids` declaration to belong to approved scope. The report explicitly lists declared references outside approved scope. This checkpoint does not inspect an actual generated Project Report and does not certify report statements, spans, or statement-level citations.

## Product invariant: ORACLE_NOT_PRESENT_IN_ENGINE_INPUT

PASS means the strict input loader accepted `generated-run/input/` and no oracle marker was found in that validated input tree. The precise status is one of `NOT_PRESENT_IN_ENGINE_INPUT`, `DETECTED_IN_ENGINE_INPUT`, or `INPUT_VALIDATION_FAILED`. This proves the generated input boundary; it does not claim knowledge of unrelated external operator actions.

## Product invariant: ORACLE_STATUS_MATCH

PASS requires every automatic status to equal the hidden expected status. This is an evaluator result for the supplied classification; it is not a claim that this checkpoint implements Source Scoping.

## Proof matrix

| CLAIM | CODE LOCATION | TEST | GENERATED EVIDENCE | DEMO-SUITABLE OUTPUT |
|---|---|---|---|---|
| `UNSEEN_SEED_RECORDED` | `unseen_workspace/evaluation_contracts.py::load_run_metadata` | `test_canonical_report_states_every_required_machine_evaluable_fact` | `report.json.unseen_seed` | Run Identity / Unseen seed |
| `TARGET_PROJECT_IDENTIFIED` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_canonical_report_states_every_required_machine_evaluable_fact` | `report.json.target_project` | Run Identity / Target project |
| `PROVIDER_IDENTITY_RECORDED` | `unseen_workspace/evaluation_contracts.py::load_classification_result` | `test_classification_submission_contract_fails_closed` | `report.json.provider_identity` | Run Identity / Provider identity |
| `EXACT_PARTITION_INTEGRITY` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_exact_partition_integrity_claim_fails_for_duplicate_and_missing_decisions` | `report.json.exact_partition_integrity` | Named Proof Claims table |
| `EVIDENCE_REFERENCE_VALIDITY` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_evidence_reference_validity_claim_fails_for_unknown_evidence_reference` | `report.json.evidence_reference_validity` | Evaluation Metrics and Evidence Sets |
| `NO_UNSAFE_AUTOMATIC_INCLUSIONS` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_no_unsafe_automatic_inclusions_claim_identifies_excluded_record` | `report.json.unsafe_automatic_inclusions` | Evaluation Metrics and Evidence Sets |
| `AMBIGUOUS_RECORDS_DEFERRED_TO_HUMAN_REVIEW` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_ambiguous_records_deferred_to_human_review_claim_counts_every_oracle_ambiguity` | `report.json.ambiguous_records_deferred_to_human_review` | Evaluation Metrics and Named Proof Claims |
| `HUMAN_OVERRIDES_ACCOUNTED` | `unseen_workspace/evaluator.py::_apply_human_overrides` | `test_human_overrides_accounted_and_approved_scope_integrity_claims_pass` | `report.json.human_overrides` | Human Overrides table |
| `APPROVED_SCOPE_INTEGRITY` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_human_overrides_accounted_and_approved_scope_integrity_claims_pass` | `report.json.approved_scope_integrity` | Evaluation Metrics and Evidence Sets |
| `DECLARED_PROJECT_REPORT_REFERENCES_WITHIN_APPROVED_SCOPE` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_declared_project_report_references_within_approved_scope_claim_detects_outside_reference` | `report.json.declared_project_report_references_outside_approved_scope` | Evaluation Metrics and Evidence Sets |
| `ORACLE_NOT_PRESENT_IN_ENGINE_INPUT` | `unseen_workspace/evaluation_contracts.py::inspect_engine_input` | `test_oracle_not_present_in_engine_input_claim_detects_exposure_marker` | `report.json.oracle_exposure_status` | Run Identity / Oracle exposure status |
| `ORACLE_STATUS_MATCH` | `unseen_workspace/evaluator.py::evaluate_generated_run` | `test_canonical_report_states_every_required_machine_evaluable_fact` | `report.json.exact_status_matches` | Evaluation Metrics and Named Proof Claims |
| JSON/Markdown equivalence | `unseen_workspace/reporting.py` | `test_json_and_markdown_are_equivalent_views_of_one_canonical_report` | `report.json` and `report.md` | CLI prints the same Markdown model |

## Architectural responsibilities

- `scenario_factory.py`: dynamic projects, relationships, dates, and required semantic cases.
- `generator.py`: deterministic layout, opaque identities, serialization, and physical input/oracle separation.
- `ingestion.py`: engine-input filesystem and raw-format boundary.
- `validation.py`: shared strict JSON, identity, project, and scope-status validation.
- `evaluation_contracts.py`: strict submission, oracle, metadata, and engine-input proof boundaries.
- `evaluator.py`: canonical proof metric computation and human-override application.
- `proof_claims.py`: stable claim names and deterministic claim outcomes.
- `reporting.py`: deterministic JSON/Markdown rendering and atomic report persistence.
- `models.py`: immutable public domain contracts.
- `cli.py`: argument parsing and visible command output only.

There is no provider call, persistence layer, Bridge adapter, or UI coupling in this checkpoint.
