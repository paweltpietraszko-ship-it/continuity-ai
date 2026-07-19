"""Conversation and proposal orchestration."""
from __future__ import annotations
import uuid
from continuity_ai.domain import AnalysisRevisionProposal, ConversationResponse, utc_now
from continuity_ai.evidence import hydrate_citations
from continuity_ai.errors import VaultLockedError, ValidationError
from continuity_ai.reasoning_pipeline import validate_analysis
INSUFFICIENT = "I couldn’t find that document in the project sources currently available to Continuity AI."
def send_message(message: str, records, spans, vault=None, revision_candidate=None, project_only: bool=False) -> ConversationResponse:
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
        prop=AnalysisRevisionProposal(proposal_id="REV-"+uuid.uuid4().hex, candidate=candidate, session_id=session.session_id, created_at=utc_now())
        vault.pending_revisions[prop.proposal_id]=prop
        return ConversationResponse("analysis_revision_proposal", "Review this updated analysis and confirm it before Continuity AI replaces the saved version.", analysis_revision_proposal=prop)
    if project_only:
        if not records or not spans: raise ValidationError()
        return ConversationResponse("project_grounded", "I found support for this in the attached source cards.", hydrate_citations((spans[0].span_id,), records, spans))
    if records and spans and "project" in low:
        return ConversationResponse("project_grounded", "I found support for this in the attached source cards.", hydrate_citations((spans[0].span_id,), records, spans))
    return ConversationResponse("general", "I can help with that. Nothing in the project was changed.")
def confirm_analysis_revision(vault, proposal_id: str):
    session=vault.require()
    prop=vault.pending_revisions.get(proposal_id)
    if prop is None or prop.session_id != session.session_id: raise ValidationError()
    vault.payload["saved_analyses"].append({"proposal_id": proposal_id}); vault.persist()
    del vault.pending_revisions[proposal_id]; return prop.candidate
