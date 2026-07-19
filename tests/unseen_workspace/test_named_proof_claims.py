from __future__ import annotations

import hashlib
import json
from pathlib import Path

from continuity_ai.unseen_workspace.evaluator import evaluate_generated_run
from continuity_ai.unseen_workspace.generator import generate_unseen_workspace
from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    HumanOverride,
    OracleExposureStatus,
    ProofStatus,
    ScopeStatus,
)
from continuity_ai.unseen_workspace.proof_claims import (
    CLAIM_AMBIGUOUS_DEFERRED,
    CLAIM_APPROVED_SCOPE_INTEGRITY,
    CLAIM_DECLARED_REPORT_REFERENCES_WITHIN_APPROVED_SCOPE,
    CLAIM_EVIDENCE_REFERENCE_VALIDITY,
    CLAIM_EXACT_PARTITION_INTEGRITY,
    CLAIM_HUMAN_OVERRIDES_ACCOUNTED,
    CLAIM_NO_UNSAFE_AUTOMATIC_INCLUSIONS,
    CLAIM_ORACLE_NOT_PRESENT,
    PROOF_CLAIM_NAMES,
)
from .proof_test_support import (
    claim_status,
    load_oracle,
    perfect_submission,
    write_json,
)


def test_canonical_report_states_every_required_machine_evaluable_fact(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 55)
    oracle = load_oracle(run)
    submission = perfect_submission(oracle)

    report = evaluate_generated_run(run, submission)

    assert report.unseen_seed == 55
    assert report.target_project.name == oracle["target_project"]["name"]
    assert report.provider_identity == "deterministic-contract-provider"
    assert report.classified_records == report.total_records == 15
    assert report.exact_partition_integrity is True
    assert report.evidence_reference_validity is True
    assert report.unsafe_automatic_inclusions == ()
    assert report.ambiguous_records_deferred_to_human_review == report.total_ambiguous_records
    assert report.human_overrides == ()
    assert report.approved_scope_size > 0
    assert report.declared_project_report_references_outside_approved_scope == ()
    assert report.oracle_exposure_status is OracleExposureStatus.NOT_PRESENT_IN_ENGINE_INPUT
    assert tuple(claim.name for claim in report.claims) == PROOF_CLAIM_NAMES
    assert report.machine_evaluable_proof is ProofStatus.PASS


def test_exact_partition_integrity_claim_fails_for_duplicate_and_missing_decisions(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 61)
    submission = perfect_submission(load_oracle(run))
    malformed = ClassificationResult(
        provider_identity=submission.provider_identity,
        decisions=submission.decisions[1:] + (submission.decisions[1],),
        human_overrides=(),
        approved_scope_evidence_ids=submission.approved_scope_evidence_ids,
        project_report_evidence_ids=submission.project_report_evidence_ids,
    )

    report = evaluate_generated_run(run, malformed)

    assert report.records_classified_exactly_once == 13
    assert report.exact_partition_integrity is False
    assert claim_status(report, CLAIM_EXACT_PARTITION_INTEGRITY) is ProofStatus.FAIL
    assert report.machine_evaluable_proof is ProofStatus.FAIL


def test_evidence_reference_validity_claim_fails_for_unknown_evidence_reference(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 62)
    submission = perfect_submission(load_oracle(run))
    invalid = ClassificationResult(
        provider_identity=submission.provider_identity,
        decisions=submission.decisions,
        human_overrides=(),
        approved_scope_evidence_ids=submission.approved_scope_evidence_ids,
        project_report_evidence_ids=submission.project_report_evidence_ids + ("EV-UNKNOWN",),
    )

    report = evaluate_generated_run(run, invalid)

    assert report.evidence_reference_validity is False
    assert report.invalid_evidence_references == ("EV-UNKNOWN",)
    assert claim_status(report, CLAIM_EVIDENCE_REFERENCE_VALIDITY) is ProofStatus.FAIL


def test_no_unsafe_automatic_inclusions_claim_identifies_excluded_record(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 63)
    oracle = load_oracle(run)
    submission = perfect_submission(oracle)
    excluded_id = next(
        record["evidence_id"]
        for record in oracle["records"]
        if record["expected_status"] == "exclude"
    )
    decisions = tuple(
        ClassificationDecision(decision.evidence_id, ScopeStatus.INCLUDE)
        if decision.evidence_id == excluded_id
        else decision
        for decision in submission.decisions
    )
    unsafe = ClassificationResult(
        provider_identity=submission.provider_identity,
        decisions=decisions,
        human_overrides=(),
        approved_scope_evidence_ids=tuple(
            sorted(set(submission.approved_scope_evidence_ids) | {excluded_id})
        ),
        project_report_evidence_ids=submission.project_report_evidence_ids,
    )

    report = evaluate_generated_run(run, unsafe)

    assert report.unsafe_automatic_inclusions == (excluded_id,)
    assert claim_status(report, CLAIM_NO_UNSAFE_AUTOMATIC_INCLUSIONS) is ProofStatus.FAIL


def test_ambiguous_records_deferred_to_human_review_claim_counts_every_oracle_ambiguity(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 64)
    oracle = load_oracle(run)
    submission = perfect_submission(oracle)
    ambiguous_id = next(
        record["evidence_id"]
        for record in oracle["records"]
        if record["expected_status"] == "defer"
    )
    decisions = tuple(
        ClassificationDecision(decision.evidence_id, ScopeStatus.EXCLUDE)
        if decision.evidence_id == ambiguous_id
        else decision
        for decision in submission.decisions
    )
    not_deferred = ClassificationResult(
        provider_identity=submission.provider_identity,
        decisions=decisions,
        human_overrides=(),
        approved_scope_evidence_ids=submission.approved_scope_evidence_ids,
        project_report_evidence_ids=submission.project_report_evidence_ids,
    )

    report = evaluate_generated_run(run, not_deferred)

    assert report.ambiguous_records_not_deferred == (ambiguous_id,)
    assert report.ambiguous_records_deferred_to_human_review == report.total_ambiguous_records - 1
    assert claim_status(report, CLAIM_AMBIGUOUS_DEFERRED) is ProofStatus.FAIL


def test_human_overrides_accounted_and_approved_scope_integrity_claims_pass(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 65)
    oracle = load_oracle(run)
    ambiguous_id = next(
        record["evidence_id"]
        for record in oracle["records"]
        if record["expected_status"] == "defer"
    )
    override = HumanOverride(ambiguous_id, ScopeStatus.INCLUDE)
    submission = perfect_submission(oracle, human_overrides=(override,))

    report = evaluate_generated_run(run, submission)

    assert report.human_overrides == (override,)
    assert report.invalid_human_overrides == ()
    assert ambiguous_id in report.approved_scope_evidence_ids
    assert report.approved_scope_integrity is True
    assert claim_status(report, CLAIM_HUMAN_OVERRIDES_ACCOUNTED) is ProofStatus.PASS
    assert claim_status(report, CLAIM_APPROVED_SCOPE_INTEGRITY) is ProofStatus.PASS


def test_human_override_claim_rejects_override_of_automatic_include(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 66)
    oracle = load_oracle(run)
    included_id = next(
        record["evidence_id"]
        for record in oracle["records"]
        if record["expected_status"] == "include"
    )
    invalid_override = HumanOverride(included_id, ScopeStatus.EXCLUDE)
    submission = perfect_submission(oracle, human_overrides=(invalid_override,))

    report = evaluate_generated_run(run, submission)

    assert report.invalid_human_overrides == (included_id,)
    assert claim_status(report, CLAIM_HUMAN_OVERRIDES_ACCOUNTED) is ProofStatus.FAIL
    assert claim_status(report, CLAIM_APPROVED_SCOPE_INTEGRITY) is ProofStatus.FAIL


def test_declared_project_report_references_within_approved_scope_claim_detects_outside_reference(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 67)
    oracle = load_oracle(run)
    submission = perfect_submission(oracle)
    excluded_id = next(
        record["evidence_id"]
        for record in oracle["records"]
        if record["expected_status"] == "exclude"
    )
    leaked = ClassificationResult(
        provider_identity=submission.provider_identity,
        decisions=submission.decisions,
        human_overrides=(),
        approved_scope_evidence_ids=submission.approved_scope_evidence_ids,
        project_report_evidence_ids=submission.project_report_evidence_ids + (excluded_id,),
    )

    report = evaluate_generated_run(run, leaked)

    assert report.declared_project_report_references_outside_approved_scope == (excluded_id,)
    assert (
        claim_status(report, CLAIM_DECLARED_REPORT_REFERENCES_WITHIN_APPROVED_SCOPE)
        is ProofStatus.FAIL
    )


def test_oracle_not_present_in_engine_input_claim_detects_exposure_marker(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 68)
    oracle = load_oracle(run)
    manifest_path = run / "input" / "workspace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(record for record in manifest["records"] if record["format"] == "txt")
    record_path = run / "input" / Path(*entry["path"].split("/"))
    exposed = record_path.read_bytes() + b'\n"expected_status": "include"\n'
    record_path.write_bytes(exposed)
    entry["sha256"] = hashlib.sha256(exposed).hexdigest()
    write_json(manifest_path, manifest)

    report = evaluate_generated_run(run, perfect_submission(oracle))

    assert report.oracle_exposure_status is OracleExposureStatus.DETECTED_IN_ENGINE_INPUT
    assert claim_status(report, CLAIM_ORACLE_NOT_PRESENT) is ProofStatus.FAIL


def test_oracle_exposure_status_fails_closed_when_engine_input_validation_fails(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    generate_unseen_workspace(run, 681)
    oracle = load_oracle(run)
    manifest = json.loads((run / "input" / "workspace.json").read_text(encoding="utf-8"))
    record_path = run / "input" / Path(*manifest["records"][0]["path"].split("/"))
    record_path.write_bytes(record_path.read_bytes() + b"tampered")

    report = evaluate_generated_run(run, perfect_submission(oracle))

    assert report.oracle_exposure_status is OracleExposureStatus.INPUT_VALIDATION_FAILED
    assert claim_status(report, CLAIM_ORACLE_NOT_PRESENT) is ProofStatus.FAIL
