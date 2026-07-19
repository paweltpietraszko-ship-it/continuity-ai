"""Canonical proof metric computation for generated unseen workspaces."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from continuity_ai.unseen_workspace.evaluation_contracts import (
    ScopeEvaluationError,
    inspect_engine_input,
    load_classification_result,
    load_expected_scope,
    load_run_metadata,
    validate_classification_result,
)
from continuity_ai.unseen_workspace.models import (
    ClassificationResult,
    EvaluationReport,
    HumanOverride,
    ProofStatus,
    ScopeStatus,
)
from continuity_ai.unseen_workspace.proof_claims import (
    build_proof_claims,
)


def evaluate_generated_run(
    run_root: Path,
    classification_result: ClassificationResult,
) -> EvaluationReport:
    """Produce the canonical proof result for one generated run and submission."""

    validate_classification_result(classification_result)
    run_root = Path(run_root)
    expected = load_expected_scope(run_root / "oracle" / "expected_scope.json")
    metadata = load_run_metadata(run_root / "oracle" / "metadata.json")
    if metadata.target_project != expected.target_project:
        raise ScopeEvaluationError("Oracle target project disagrees with run metadata.")
    if metadata.record_count != len(expected.statuses):
        raise ScopeEvaluationError("Oracle record count disagrees with run metadata.")

    exposure_status, input_target = inspect_engine_input(run_root / "input")
    if input_target is not None and input_target != expected.target_project:
        raise ScopeEvaluationError("Engine input target project disagrees with the oracle.")

    expected_ids = set(expected.statuses)
    counts = Counter(decision.evidence_id for decision in classification_result.decisions)
    by_id: dict[str, list[ScopeStatus]] = defaultdict(list)
    for decision in classification_result.decisions:
        by_id[decision.evidence_id].append(decision.status)

    classified_records = sum(counts[evidence_id] > 0 for evidence_id in expected_ids)
    classified_once = sum(counts[evidence_id] == 1 for evidence_id in expected_ids)
    unknown_decision_ids = {evidence_id for evidence_id in counts if evidence_id not in expected_ids}
    exact_partition = classified_once == len(expected_ids) and not unknown_decision_ids

    all_references = _all_evidence_references(classification_result)
    invalid_references = tuple(sorted({item for item in all_references if item not in expected_ids}))
    valid_reference_count = sum(item in expected_ids for item in all_references)
    evidence_reference_validity = not invalid_references

    unsafe_inclusions = tuple(
        sorted(
            {
                decision.evidence_id
                for decision in classification_result.decisions
                if decision.status is ScopeStatus.INCLUDE
                and expected.statuses.get(decision.evidence_id) is not ScopeStatus.INCLUDE
            }
        )
    )
    ambiguous_ids = set(expected.ambiguous_evidence_ids)
    ambiguous_not_deferred = tuple(
        sorted(
            evidence_id
            for evidence_id in ambiguous_ids
            if by_id[evidence_id] != [ScopeStatus.DEFER]
        )
    )
    ambiguous_deferred = len(ambiguous_ids) - len(ambiguous_not_deferred)

    invalid_overrides, final_statuses = _apply_human_overrides(
        expected_ids,
        by_id,
        classification_result.human_overrides,
    )
    submitted_scope = tuple(sorted(classification_result.approved_scope_evidence_ids))
    expected_approved_scope = tuple(
        sorted(
            evidence_id
            for evidence_id, status in final_statuses.items()
            if status is ScopeStatus.INCLUDE
        )
    )
    approved_scope_integrity = (
        len(submitted_scope) == len(set(submitted_scope))
        and submitted_scope == expected_approved_scope
        and not invalid_overrides
    )
    approved_set = set(submitted_scope)
    project_report_ids = tuple(sorted(classification_result.project_report_evidence_ids))
    declared_report_references_outside_scope = tuple(
        sorted({evidence_id for evidence_id in project_report_ids if evidence_id not in approved_set})
    )
    exact_status_matches = sum(
        counts[evidence_id] == 1 and by_id[evidence_id] == [expected_status]
        for evidence_id, expected_status in expected.statuses.items()
    )

    claims = build_proof_claims(
        unseen_seed=metadata.seed,
        target_project=expected.target_project,
        provider_identity=classification_result.provider_identity,
        exact_partition=exact_partition,
        classified_once=classified_once,
        total_records=len(expected_ids),
        evidence_reference_validity=evidence_reference_validity,
        invalid_references=invalid_references,
        unsafe_inclusions=unsafe_inclusions,
        ambiguous_deferred=ambiguous_deferred,
        total_ambiguous=len(ambiguous_ids),
        invalid_overrides=invalid_overrides,
        override_count=len(classification_result.human_overrides),
        approved_scope_integrity=approved_scope_integrity,
        approved_scope_size=len(approved_set),
        declared_report_references_outside_scope=(
            declared_report_references_outside_scope
        ),
        exposure_status=exposure_status,
        exact_status_matches=exact_status_matches,
    )
    proof_status = (
        ProofStatus.PASS
        if all(claim.status is ProofStatus.PASS for claim in claims)
        else ProofStatus.FAIL
    )
    return EvaluationReport(
        unseen_seed=metadata.seed,
        target_project=expected.target_project,
        provider_identity=classification_result.provider_identity,
        classified_records=classified_records,
        total_records=len(expected_ids),
        records_classified_exactly_once=classified_once,
        exact_partition_integrity=exact_partition,
        valid_evidence_references=valid_reference_count,
        total_evidence_references=len(all_references),
        evidence_reference_validity=evidence_reference_validity,
        invalid_evidence_references=invalid_references,
        unsafe_automatic_inclusions=unsafe_inclusions,
        ambiguous_records_deferred_to_human_review=ambiguous_deferred,
        total_ambiguous_records=len(ambiguous_ids),
        ambiguous_records_not_deferred=ambiguous_not_deferred,
        human_overrides=tuple(classification_result.human_overrides),
        invalid_human_overrides=invalid_overrides,
        approved_scope_evidence_ids=submitted_scope,
        approved_scope_size=len(approved_set),
        approved_scope_integrity=approved_scope_integrity,
        project_report_evidence_ids=project_report_ids,
        declared_project_report_references_outside_approved_scope=(
            declared_report_references_outside_scope
        ),
        oracle_exposure_status=exposure_status,
        exact_status_matches=exact_status_matches,
        claims=claims,
        machine_evaluable_proof=proof_status,
    )


def evaluate_scope(
    expected_scope_path: Path,
    classification_result: ClassificationResult,
) -> EvaluationReport:
    """Compatibility entry point for generated-run oracle paths.

    The expected scope must remain at ``generated-run/oracle/expected_scope.json``
    so evaluation can prove seed, input isolation, and metadata consistency too.
    """

    path = Path(expected_scope_path)
    if path.name != "expected_scope.json" or path.parent.name != "oracle":
        raise ScopeEvaluationError(
            "Expected scope must be generated-run/oracle/expected_scope.json."
        )
    return evaluate_generated_run(path.parent.parent, classification_result)


def _all_evidence_references(result: ClassificationResult) -> tuple[str, ...]:
    return (
        tuple(decision.evidence_id for decision in result.decisions)
        + tuple(override.evidence_id for override in result.human_overrides)
        + tuple(result.approved_scope_evidence_ids)
        + tuple(result.project_report_evidence_ids)
    )


def _apply_human_overrides(
    expected_ids: set[str],
    automatic: dict[str, list[ScopeStatus]],
    overrides: tuple[HumanOverride, ...],
) -> tuple[tuple[str, ...], dict[str, ScopeStatus]]:
    override_counts = Counter(override.evidence_id for override in overrides)
    invalid: set[str] = set()
    final_statuses = {
        evidence_id: statuses[0]
        for evidence_id, statuses in automatic.items()
        if evidence_id in expected_ids and len(statuses) == 1
    }
    for override in overrides:
        if (
            override.evidence_id not in expected_ids
            or override_counts[override.evidence_id] != 1
            or automatic.get(override.evidence_id) != [ScopeStatus.DEFER]
        ):
            invalid.add(override.evidence_id)
            continue
        final_statuses[override.evidence_id] = override.status
    return tuple(sorted(invalid)), final_statuses
