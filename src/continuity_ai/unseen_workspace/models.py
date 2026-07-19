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
class ClassificationResult:
    """The result contract accepted by the neutral oracle evaluator."""

    decisions: tuple[ClassificationDecision, ...]


@dataclass(frozen=True)
class EvaluationReport:
    """Deterministic aggregate and safety metrics for one classification result."""

    classified_records: int
    total_records: int
    records_classified_exactly_once: int
    valid_evidence_references: int
    total_evidence_references: int
    invalid_evidence_references: tuple[str, ...]
    unsafe_automatic_inclusions: tuple[str, ...]
    correctly_deferred_ambiguous_records: int
    total_ambiguous_records: int
    exact_status_matches: int

    def to_dict(self) -> dict[str, object]:
        """Return a stable JSON-compatible representation."""

        return {
            "classified_records": self.classified_records,
            "total_records": self.total_records,
            "records_classified_exactly_once": self.records_classified_exactly_once,
            "valid_evidence_references": self.valid_evidence_references,
            "total_evidence_references": self.total_evidence_references,
            "invalid_evidence_references": list(self.invalid_evidence_references),
            "unsafe_automatic_inclusions": list(self.unsafe_automatic_inclusions),
            "correctly_deferred_ambiguous_records": self.correctly_deferred_ambiguous_records,
            "total_ambiguous_records": self.total_ambiguous_records,
            "exact_status_matches": self.exact_status_matches,
        }
