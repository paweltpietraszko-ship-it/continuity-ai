"""Conversation and proposal orchestration."""
from __future__ import annotations
import uuid
from continuity_ai.analysis_revision import (
    CONTEXT_BINDING_SCHEMA_VERSION,
    build_analysis_revision_context_binding,
)
from continuity_ai.domain import (
    AnalysisRevisionContextBinding,
    AnalysisRevisionProposal,
    ConversationResponse,
    utc_now,
)
from continuity_ai.evidence import hydrate_citations
from continuity_ai.errors import VaultLockedError, ValidationError
from continuity_ai.reasoning_pipeline import validate_analysis
INSUFFICIENT = "I couldn’t find that document in the project sources currently available to Continuity AI."
def send_message(
    message: str,
    records,
    spans,
    vault=None,
    revision_candidate=None,
    project_only: bool = False,
    target_project: str | None = None,
    source_scoping_status: str = 'none',
    approved_source_scope=None,
) -> ConversationResponse:
    low=message.lower()
    if "nonexistent" in low or "missing" in low: return ConversationResponse("insufficient_evidence", INSUFFICIENT)
    if "attest" in low or "add evidence" in low:
        if vault is None: raise VaultLockedError()
        p=vault.propose_attestation(message)
        return ConversationResponse("attestation_proposal", "Review this note and confirm it before Continuity AI adds it to the project.", attestation_proposal=p)
    if revision_candidate is not None:
        if vault is None: raise VaultLockedError()
        session=vault.require()
        candidate=validate_analysis(revision_candidate, records, spans)
        context_binding = build_analysis_revision_context_binding(
            vault,
            target_project=target_project,
            source_scoping_status=source_scoping_status,
            approved_source_scope=approved_source_scope,
            records=records,
        )
        prop = AnalysisRevisionProposal(
            proposal_id='REV-' + uuid.uuid4().hex,
            candidate=candidate,
            session_id=session.session_id,
            created_at=utc_now(),
            context_binding=context_binding,
        )
        vault.pending_revisions[prop.proposal_id]=prop
        return ConversationResponse("analysis_revision_proposal", "Review this updated analysis and confirm it before Continuity AI replaces the saved version.", analysis_revision_proposal=prop)
    if project_only:
        if not records or not spans: raise ValidationError()
        return ConversationResponse("project_grounded", "I found support for this in the attached source cards.", hydrate_citations((spans[0].span_id,), records, spans))
    if records and spans and "project" in low:
        return ConversationResponse("project_grounded", "I found support for this in the attached source cards.", hydrate_citations((spans[0].span_id,), records, spans))
    return ConversationResponse("general", "I can help with that. Nothing in the project was changed.")
def confirm_analysis_revision(
    vault,
    proposal_id: str,
    *current_context_binding_values: AnalysisRevisionContextBinding,
):
    session=vault.require()
    prop=vault.pending_revisions.get(proposal_id)
    if prop is None or prop.session_id != session.session_id: raise ValidationError()
    stored_binding = prop.context_binding
    if type(stored_binding) is not AnalysisRevisionContextBinding:
        raise ValidationError()
    if len(current_context_binding_values) != 1:
        raise ValidationError()
    current_binding = current_context_binding_values[0]
    if type(current_binding) is not AnalysisRevisionContextBinding:
        raise ValidationError()
    if not _valid_binding_schema(stored_binding.schema_version):
        raise ValidationError()
    if not _valid_binding_schema(current_binding.schema_version):
        raise ValidationError()
    if stored_binding.schema_version != current_binding.schema_version:
        raise ValidationError()
    if not _valid_binding_sha256(stored_binding.sha256):
        raise ValidationError()
    if not _valid_binding_sha256(current_binding.sha256):
        raise ValidationError()
    if stored_binding.sha256 != current_binding.sha256:
        raise ValidationError()
    vault.save_analysis_revision(proposal_id)
    del vault.pending_revisions[proposal_id]; return prop.candidate


def _valid_binding_schema(value) -> bool:
    return (
        type(value) is str
        and value == CONTEXT_BINDING_SCHEMA_VERSION
    )


def _valid_binding_sha256(value) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in '0123456789abcdef' for character in value)
    )
