"""The one narrow bridge-facing coordinator for the real Codex vertical flow:

    mixed workspace
      -> create controller session
      -> real Codex Source Scoping investigation
      -> AWAITING_HUMAN_REVIEW (nothing approved automatically)
      -> human review (explicit overrides)
      -> approved-only materialization
      -> bind_approved_workspace (no new Codex thread)
      -> same-session report resume

Bridge stays a thin NDJSON dispatch boundary: it holds this coordinator's
per-project state (`VerticalFlowState`) as a plain instance attribute and
calls exactly the functions below from its `scope_project_sources`,
`confirm_source_scope`, and `analyze_project` command handlers. No
controller, materialization, or Codex-session lifecycle logic lives in
`bridge.py` itself.

There is no OpenAI or fake automatic fallback anywhere in this module: a
Codex failure at any step (unavailable, workspace changed, invalid output,
session mismatch, ...) propagates as-is; it is never silently retried
against another provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from continuity_ai.codex_process import workspace_fingerprint
from continuity_ai.codex_session import (
    CodexOperation,
    CodexSessionController,
    JsonSessionStore,
    SessionPhase,
)
from continuity_ai.domain import ReasoningEvidence
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import build_spans
from continuity_ai.integration.approved_workspace_flow import materialize_approved_scope
from continuity_ai.integration.codex_reasoning_provider import run_codex_reporting_analysis
from continuity_ai.integration.codex_session_flow import (
    record_scope_awaiting_review,
    start_mixed_workspace_investigation,
)
from continuity_ai.integration.source_scope_binding import (
    SourceRegistry,
    SourceRegistryEntry,
)
from continuity_ai.models import EvidenceRecord
from continuity_ai.source_scoping.domain import ApprovedSourceScope, SourceScopingResult
from continuity_ai.source_scoping.review import approve_source_scope

CONTROLLER_STORE_FILENAME = ".continuity_codex_sessions.json"


def build_source_registry(
    artifact_evidence_records: tuple[EvidenceRecord, ...]
) -> SourceRegistry:
    """The explicit evidence_id -> relative_path -> SHA-256 registry
    materialization needs, sourced only from ingestion's own
    already-verified manifest fields (`uri`, `artifact_sha256`) -- never
    inferred from a filename or evidence_id."""
    return {
        record.evidence_id: SourceRegistryEntry(
            relative_path=record.uri, sha256=record.artifact_sha256
        )
        for record in artifact_evidence_records
    }


@dataclass
class VerticalFlowState:
    """Per-project, in-memory state for the real Codex vertical flow.

    Reset whenever a project or vault boundary changes (mirroring
    `SourceScopingSession.reset()`): a controller session from a previous
    project or a previous vault must never be resumed for a different one.
    """

    controller: CodexSessionController | None = None
    controller_session_id: str | None = None
    scoping_result: SourceScopingResult | None = None
    approved_scope: ApprovedSourceScope | None = None
    approved_workspace_root: Path | None = None

    def reset(self) -> None:
        self.controller = None
        self.controller_session_id = None
        self.scoping_result = None
        self.approved_scope = None
        self.approved_workspace_root = None


@dataclass(frozen=True)
class RunIdentity:
    """Safe, non-secret run-observability metadata for a competition/demo
    audience. Every field is read directly from the controller's own
    retained session and receipt state (never fabricated, never supplied by
    a caller or the frontend) and none of them can ever contain a local
    path, prompt, stderr, password, evidence/oracle content, or internal
    exception -- `codex_session_id`/`controller_session_id` are opaque
    UUIDs and both fingerprints are SHA-256 hex digests of workspace
    content, not paths.
    """

    controller_session_id: str
    codex_session_id: str | None
    mixed_workspace_fingerprint: str
    approved_workspace_fingerprint: str | None
    reporting_resumed_retained_session: bool


def build_run_identity(state: VerticalFlowState) -> RunIdentity | None:
    """Return `None` when no real controller session is active (including
    every existing test path that injects an explicit
    `source_scoping_provider`), so callers can omit this metadata entirely
    rather than publish a fabricated or empty value."""
    if state.controller is None or state.controller_session_id is None:
        return None
    session = state.controller.get_session(state.controller_session_id)
    receipt = session.last_successful_invocation_receipt
    reporting_resumed_retained_session = bool(
        receipt is not None
        and receipt.operation_type is CodexOperation.REPORT
        and receipt.resume_attempted
        and not receipt.new_codex_session_created
    )
    return RunIdentity(
        controller_session_id=session.controller_session_id,
        codex_session_id=session.codex_session_id,
        mixed_workspace_fingerprint=session.workspace_fingerprint,
        approved_workspace_fingerprint=session.approved_workspace_fingerprint,
        reporting_resumed_retained_session=reporting_resumed_retained_session,
    )


def start_real_scoping_investigation(
    state: VerticalFlowState,
    artifact_root: Path,
    target_project: str,
    evidence: tuple[ReasoningEvidence, ...],
) -> SourceScopingResult:
    """Create a fresh controller session bound to the mixed workspace and run
    one real Codex-backed Source Scoping investigation on it, ending in
    AWAITING_HUMAN_REVIEW. Approves nothing automatically."""
    controller = CodexSessionController.with_local_codex(
        JsonSessionStore(artifact_root.parent / CONTROLLER_STORE_FILENAME)
    )
    spans = build_spans(evidence)
    investigation = start_mixed_workspace_investigation(
        controller, artifact_root, target_project, evidence, spans
    )
    record_scope_awaiting_review(controller, investigation.controller_session_id)
    state.controller = controller
    state.controller_session_id = investigation.controller_session_id
    state.scoping_result = investigation.scoping_result
    state.approved_scope = None
    state.approved_workspace_root = None
    return investigation.scoping_result


def confirm_and_materialize_approved_workspace(
    state: VerticalFlowState,
    artifact_root: Path,
    evidence: tuple[ReasoningEvidence, ...],
    overrides: Mapping[str, str],
    source_registry: SourceRegistry,
) -> ApprovedSourceScope:
    """Apply the human's explicit overrides, materialize a physically
    separate approved-only workspace, and bind it to the same controller
    session. `bind_approved_workspace` never invokes Codex, so this step can
    never open a replacement Codex thread."""
    if (
        state.controller is None
        or state.controller_session_id is None
        or state.scoping_result is None
    ):
        raise ValidationError()
    approved_scope = approve_source_scope(state.scoping_result, evidence, overrides)
    destination = artifact_root.parent / f"approved_workspace_{approved_scope.scope_id}"
    receipt = materialize_approved_scope(
        artifact_root, approved_scope, evidence, source_registry, destination
    )
    state.controller.bind_approved_workspace(
        state.controller_session_id,
        receipt.destination_root,
        workspace_fingerprint(receipt.destination_root),
    )
    state.approved_scope = approved_scope
    state.approved_workspace_root = receipt.destination_root
    return approved_scope


def vertical_flow_ready_for_reporting(state: VerticalFlowState) -> bool:
    """True only when every prerequisite for resuming the real Codex
    vertical flow's reporting step is satisfied: an active controller
    session, a materialized approved-only workspace, a retained Codex
    session ID from the investigation, and the session's own APPROVED
    phase. Bridge's production `analyze_project` handler uses this to fail
    closed instead of silently falling back to a local, OpenAI, or
    deterministic provider when any one of these is missing."""
    if (
        state.controller is None
        or state.controller_session_id is None
        or state.approved_workspace_root is None
    ):
        return False
    session = state.controller.get_session(state.controller_session_id)
    return session.codex_session_id is not None and session.phase is SessionPhase.APPROVED


def report_on_approved_workspace(
    state: VerticalFlowState,
    records: tuple[ReasoningEvidence, ...],
    question: str,
):
    """Resume the retained Codex session on the approved-only workspace to
    produce one Project Report, matching `run_analysis`'s
    `(result, spans, snapshot)` contract."""
    if (
        state.controller is None
        or state.controller_session_id is None
        or state.approved_workspace_root is None
    ):
        raise ValidationError()
    return run_codex_reporting_analysis(
        state.controller,
        state.controller_session_id,
        state.approved_workspace_root,
        records,
        question,
    )
