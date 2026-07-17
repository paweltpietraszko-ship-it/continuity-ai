"""Immutable domain models for the vertical skeleton."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

Provenance = Literal["artifact", "authenticated_user_attestation"]
Role = Literal["approved_decision", "reflects_decision", "conflicts_with_decision", "none"]
Status = Literal["break_found", "no_material_break_found"]
BreakKind = Literal["propagation_break", "decision_provenance_not_found"]

@dataclass(frozen=True)
class ReasoningEvidence:
    evidence_id: str; source_type: str; author_or_actor: str; timestamp: str; title: str; content: str; provenance: Provenance
    uri: str | None = None; artifact_sha256: str | None = None
    def __post_init__(self) -> None:
        if not all([self.evidence_id.strip(), self.source_type.strip(), self.author_or_actor.strip(), self.title.strip(), self.content.strip()]):
            raise ValueError("reasoning evidence fields must be non-empty")
        datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))

@dataclass(frozen=True)
class EvidenceSpan:
    span_id: str; evidence_id: str; text: str; index: int

@dataclass(frozen=True)
class AuthenticatedUserAttestation:
    evidence_id: str; actor_id: str; actor_display_name: str; asserted_at: str; channel: Literal["text"]; statement: str; supersedes_evidence_id: str | None = None
    def __post_init__(self) -> None:
        stmt = self.statement.strip()
        if not stmt or len(stmt) > 4000:
            raise ValueError("attestation statement is invalid")

@dataclass(frozen=True)
class AttestationProposal:
    proposal_id: str; statement: str; session_id: str; created_at: str; channel: Literal["text"] = "text"; supersedes_evidence_id: str | None = None
    def __post_init__(self) -> None:
        stmt = self.statement.strip()
        if not stmt or len(stmt) > 4000:
            raise ValueError("attestation proposal statement is invalid")

@dataclass(frozen=True)
class GroundedStatement:
    statement: str; span_ids: tuple[str, ...]

@dataclass(frozen=True)
class SemanticAnnotation:
    evidence_id: str; propagation_role: Role; context_tags: tuple[Literal["urgency"], ...] = ()

@dataclass(frozen=True)
class AnalysisResult:
    schema_version: str; analysis_status: Status; continuity_break_kind: BreakKind | None; current_state: GroundedStatement; semantic_annotations: tuple[SemanticAnnotation, ...]; continuity_break: GroundedStatement | None; next_action: GroundedStatement | None

@dataclass(frozen=True)
class AnalysisRevisionProposal:
    proposal_id: str; candidate: AnalysisResult; session_id: str; created_at: str

@dataclass(frozen=True)
class CitationCard:
    evidence_id: str; span_id: str; exact_text: str; title: str; author_or_actor: str; timestamp: str; source_type: str; provenance: Provenance; source_status: str = "current"

@dataclass(frozen=True)
class EvidenceSnapshot:
    analysis_id: str; created_at: str; records: tuple[dict[str, str | None], ...]; spans: tuple[dict[str, str], ...]; prompt_version: str; schema_version: str; provider_id: str

@dataclass(frozen=True)
class SavedAnalysis:
    analysis_id: str; created_at: str; result: AnalysisResult; evidence_snapshot: EvidenceSnapshot

@dataclass(frozen=True)
class OwnerProfile:
    actor_id: str; display_name: str; created_at: str

@dataclass
class VaultSession:
    owner_id: str; vault_id: str; session_id: str; unlocked: bool; key_buffer: bytearray

@dataclass(frozen=True)
class AuditEvent:
    event_id: str; event_type: str; actor_id: str; timestamp: str; object_id: str; success: bool

@dataclass(frozen=True)
class ConversationResponse:
    kind: Literal["general", "project_grounded", "insufficient_evidence", "attestation_proposal", "analysis_revision_proposal"]
    message: str; citation_cards: tuple[CitationCard, ...] = (); attestation_proposal: AttestationProposal | None = None; analysis_revision_proposal: AnalysisRevisionProposal | None = None

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
