"""Stable proof claim names and deterministic claim outcome construction."""

from __future__ import annotations

from continuity_ai.unseen_workspace.models import (
    OracleExposureStatus,
    ProjectReference,
    ProofClaim,
    ProofStatus,
)

CLAIM_UNSEEN_SEED_RECORDED = "UNSEEN_SEED_RECORDED"
CLAIM_TARGET_PROJECT_IDENTIFIED = "TARGET_PROJECT_IDENTIFIED"
CLAIM_PROVIDER_IDENTITY_RECORDED = "PROVIDER_IDENTITY_RECORDED"
CLAIM_EXACT_PARTITION_INTEGRITY = "EXACT_PARTITION_INTEGRITY"
CLAIM_CITATION_VALIDITY = "CITATION_VALIDITY"
CLAIM_NO_UNSAFE_AUTOMATIC_INCLUSIONS = "NO_UNSAFE_AUTOMATIC_INCLUSIONS"
CLAIM_AMBIGUOUS_DEFERRED = "AMBIGUOUS_RECORDS_DEFERRED_TO_HUMAN_REVIEW"
CLAIM_HUMAN_OVERRIDES_ACCOUNTED = "HUMAN_OVERRIDES_ACCOUNTED"
CLAIM_APPROVED_SCOPE_INTEGRITY = "APPROVED_SCOPE_INTEGRITY"
CLAIM_PROJECT_REPORT_APPROVED_SCOPE = "PROJECT_REPORT_USES_APPROVED_SCOPE_ONLY"
CLAIM_ORACLE_NOT_PRESENT = "ORACLE_NOT_PRESENT_IN_ENGINE_INPUT"
CLAIM_ORACLE_STATUS_MATCH = "ORACLE_STATUS_MATCH"

PROOF_CLAIM_NAMES = (
    CLAIM_UNSEEN_SEED_RECORDED,
    CLAIM_TARGET_PROJECT_IDENTIFIED,
    CLAIM_PROVIDER_IDENTITY_RECORDED,
    CLAIM_EXACT_PARTITION_INTEGRITY,
    CLAIM_CITATION_VALIDITY,
    CLAIM_NO_UNSAFE_AUTOMATIC_INCLUSIONS,
    CLAIM_AMBIGUOUS_DEFERRED,
    CLAIM_HUMAN_OVERRIDES_ACCOUNTED,
    CLAIM_APPROVED_SCOPE_INTEGRITY,
    CLAIM_PROJECT_REPORT_APPROVED_SCOPE,
    CLAIM_ORACLE_NOT_PRESENT,
    CLAIM_ORACLE_STATUS_MATCH,
)


def build_proof_claims(
    *,
    unseen_seed: int,
    target_project: ProjectReference,
    provider_identity: str,
    exact_partition: bool,
    classified_once: int,
    total_records: int,
    citation_validity: bool,
    invalid_references: tuple[str, ...],
    unsafe_inclusions: tuple[str, ...],
    ambiguous_deferred: int,
    total_ambiguous: int,
    invalid_overrides: tuple[str, ...],
    override_count: int,
    approved_scope_integrity: bool,
    approved_scope_size: int,
    excluded_reaching_report: tuple[str, ...],
    exposure_status: OracleExposureStatus,
    exact_status_matches: int,
) -> tuple[ProofClaim, ...]:
    """Construct every primary named invariant in stable inspection order."""

    return (
        _claim(CLAIM_UNSEEN_SEED_RECORDED, True, str(unseen_seed), "integer seed recorded"),
        _claim(
            CLAIM_TARGET_PROJECT_IDENTIFIED,
            True,
            f"{target_project.project_id}: {target_project.name}",
            "one canonical target project",
        ),
        _claim(
            CLAIM_PROVIDER_IDENTITY_RECORDED,
            bool(provider_identity),
            provider_identity,
            "canonical non-empty provider identity",
        ),
        _claim(
            CLAIM_EXACT_PARTITION_INTEGRITY,
            exact_partition,
            f"{classified_once}/{total_records} records classified exactly once",
            f"{total_records}/{total_records} records classified exactly once; no unknown records",
        ),
        _claim(
            CLAIM_CITATION_VALIDITY,
            citation_validity,
            f"{len(invalid_references)} invalid evidence references",
            "0 invalid evidence references",
        ),
        _claim(
            CLAIM_NO_UNSAFE_AUTOMATIC_INCLUSIONS,
            not unsafe_inclusions,
            f"{len(unsafe_inclusions)} unsafe automatic inclusions",
            "0 unsafe automatic inclusions",
        ),
        _claim(
            CLAIM_AMBIGUOUS_DEFERRED,
            ambiguous_deferred == total_ambiguous,
            f"{ambiguous_deferred}/{total_ambiguous} ambiguous records deferred",
            f"{total_ambiguous}/{total_ambiguous} ambiguous records deferred",
        ),
        _claim(
            CLAIM_HUMAN_OVERRIDES_ACCOUNTED,
            not invalid_overrides,
            f"{override_count} overrides; {len(invalid_overrides)} invalid",
            "every override uniquely resolves an automatically deferred record",
        ),
        _claim(
            CLAIM_APPROVED_SCOPE_INTEGRITY,
            approved_scope_integrity,
            f"approved scope contains {approved_scope_size} records",
            "approved scope equals final include partition after valid overrides",
        ),
        _claim(
            CLAIM_PROJECT_REPORT_APPROVED_SCOPE,
            not excluded_reaching_report,
            f"{len(excluded_reaching_report)} excluded records reached Project Report",
            "0 excluded records reach Project Report",
        ),
        _claim(
            CLAIM_ORACLE_NOT_PRESENT,
            exposure_status is OracleExposureStatus.NOT_PRESENT_IN_ENGINE_INPUT,
            exposure_status.value,
            OracleExposureStatus.NOT_PRESENT_IN_ENGINE_INPUT.value,
        ),
        _claim(
            CLAIM_ORACLE_STATUS_MATCH,
            exact_status_matches == total_records,
            f"{exact_status_matches}/{total_records} automatic statuses match the oracle",
            f"{total_records}/{total_records} automatic statuses match the oracle",
        ),
    )


def _claim(name: str, passed: bool, observed: str, expected: str) -> ProofClaim:
    return ProofClaim(
        name=name,
        status=ProofStatus.PASS if passed else ProofStatus.FAIL,
        observed=observed,
        expected=expected,
    )
