"""Typed public contracts for unseen-workspace infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ScopeStatus(str, Enum):
    """A later scope classifier's decision for one evidence record."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    DEFER = "defer"


class ProofStatus(str, Enum):
    """Machine-evaluable outcome for a named proof claim."""

    PASS = "PASS"
    FAIL = "FAIL"


class OracleExposureStatus(str, Enum):
    """What the evaluator can prove about the generated engine input."""

    NOT_PRESENT_IN_ENGINE_INPUT = "NOT_PRESENT_IN_ENGINE_INPUT"
    DETECTED_IN_ENGINE_INPUT = "DETECTED_IN_ENGINE_INPUT"
    INPUT_VALIDATION_FAILED = "INPUT_VALIDATION_FAILED"


@dataclass(frozen=True)
class ProjectReference:
    """The user-selected target project visible to an analysis engine."""

    project_id: str
    name: str


@dataclass(frozen=True)
class RawWorkspaceRecord:
    """One validated raw record loaded from the engine-visible input root."""

    evidence_id: str
    relative_path: str
    source_format: str
    sha256: str
    content: str


@dataclass(frozen=True)
class WorkspaceInput:
    """A complete engine-visible unseen workspace."""

    input_root: Path
    target_project: ProjectReference
    records: tuple[RawWorkspaceRecord, ...]


@dataclass(frozen=True)
class ClassificationDecision:
    """One classifier decision; duplicates remain representable for evaluation."""

    evidence_id: str
    status: ScopeStatus


@dataclass(frozen=True)
class HumanOverride:
    """A human's final include/exclude decision for one automatically deferred record."""

    evidence_id: str
    status: ScopeStatus


@dataclass(frozen=True)
class ClassificationResult:
    """Complete later-stage submission accepted by the neutral oracle evaluator."""

    provider_identity: str
    decisions: tuple[ClassificationDecision, ...]
    human_overrides: tuple[HumanOverride, ...]
    approved_scope_evidence_ids: tuple[str, ...]
    project_report_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProofClaim:
    """One stable, named product invariant and its observed result."""

    name: str
    status: ProofStatus
    observed: str
    expected: str


@dataclass(frozen=True)
class EvaluationReport:
    """Canonical machine- and human-renderable proof result for one generated run."""

    unseen_seed: int
    target_project: ProjectReference
    provider_identity: str
    classified_records: int
    total_records: int
    records_classified_exactly_once: int
    exact_partition_integrity: bool
    valid_evidence_references: int
    total_evidence_references: int
    citation_validity: bool
    invalid_evidence_references: tuple[str, ...]
    unsafe_automatic_inclusions: tuple[str, ...]
    ambiguous_records_deferred_to_human_review: int
    total_ambiguous_records: int
    ambiguous_records_not_deferred: tuple[str, ...]
    human_overrides: tuple[HumanOverride, ...]
    invalid_human_overrides: tuple[str, ...]
    approved_scope_evidence_ids: tuple[str, ...]
    approved_scope_size: int
    approved_scope_integrity: bool
    project_report_evidence_ids: tuple[str, ...]
    excluded_records_reaching_project_report: tuple[str, ...]
    oracle_exposure_status: OracleExposureStatus
    exact_status_matches: int
    claims: tuple[ProofClaim, ...]
    machine_evaluable_proof: ProofStatus

    @property
    def correctly_deferred_ambiguous_records(self) -> int:
        """Compatibility alias for the explicit human-review deferral metric."""

        return self.ambiguous_records_deferred_to_human_review

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""

        return {
            "schema_version": 1,
            "unseen_seed": self.unseen_seed,
            "target_project": {
                "project_id": self.target_project.project_id,
                "name": self.target_project.name,
            },
            "provider_identity": self.provider_identity,
            "classified_records": self.classified_records,
            "total_records": self.total_records,
            "records_classified_exactly_once": self.records_classified_exactly_once,
            "exact_partition_integrity": self.exact_partition_integrity,
            "valid_evidence_references": self.valid_evidence_references,
            "total_evidence_references": self.total_evidence_references,
            "citation_validity": self.citation_validity,
            "invalid_evidence_references": list(self.invalid_evidence_references),
            "unsafe_automatic_inclusions": list(self.unsafe_automatic_inclusions),
            "ambiguous_records_deferred_to_human_review": (
                self.ambiguous_records_deferred_to_human_review
            ),
            "total_ambiguous_records": self.total_ambiguous_records,
            "ambiguous_records_not_deferred": list(self.ambiguous_records_not_deferred),
            "human_overrides": [
                {"evidence_id": override.evidence_id, "status": override.status.value}
                for override in self.human_overrides
            ],
            "invalid_human_overrides": list(self.invalid_human_overrides),
            "approved_scope_evidence_ids": list(self.approved_scope_evidence_ids),
            "approved_scope_size": self.approved_scope_size,
            "approved_scope_integrity": self.approved_scope_integrity,
            "project_report_evidence_ids": list(self.project_report_evidence_ids),
            "excluded_records_reaching_project_report": list(
                self.excluded_records_reaching_project_report
            ),
            "oracle_exposure_status": self.oracle_exposure_status.value,
            "exact_status_matches": self.exact_status_matches,
            "claims": [
                {
                    "name": claim.name,
                    "status": claim.status.value,
                    "observed": claim.observed,
                    "expected": claim.expected,
                }
                for claim in self.claims
            ],
            "machine_evaluable_proof": self.machine_evaluable_proof.value,
        }
