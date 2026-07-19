"""End-to-end orchestration of the frozen mixed -> review -> approved-only ->
same-session resume flow:

    mixed workspace
      -> create controller session
      -> Codex start_investigation
      -> validated SourceScopingResult
      -> record_awaiting_human_review
      -> human approval
      -> approved-only materialization
      -> bind_approved_workspace
      -> start_reporting
      -> same codex_session_id on approved workspace.

This is the single place, outside Bridge, that enforces this exact step
ordering by construction: each step's output is the only input the next step
accepts, so no step can be skipped or reordered by a caller. `overrides`
represents the human review decision already made (the same shape Source
Scoping's own `approve_source_scope` and Bridge's `confirm_source_scope`
command already accept) — this module does not itself implement any UI or
Bridge command, nor any asynchronous wait for a human; splitting the
synchronous call into two Bridge-facing steps is Bridge's job once wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from continuity_ai.approved_workspace.contracts import MaterializationReceipt
from continuity_ai.codex_process import workspace_fingerprint
from continuity_ai.codex_session import CodexOperationRequest, CodexSessionController
from continuity_ai.evidence import build_spans
from continuity_ai.integration.approved_workspace_flow import materialize_approved_scope
from continuity_ai.integration.codex_session_flow import (
    ReportingOutcome,
    bind_and_report_on_approved_workspace,
    record_scope_awaiting_review,
    start_mixed_workspace_investigation,
)
from continuity_ai.integration.source_scope_binding import SourceRegistry
from continuity_ai.source_scoping.domain import ApprovedSourceScope
from continuity_ai.source_scoping.review import approve_source_scope


@dataclass(frozen=True)
class MixedToApprovedPipelineResult:
    controller_session_id: str
    codex_session_id: str
    approved_scope: ApprovedSourceScope
    materialization: MaterializationReceipt
    reporting: ReportingOutcome


def run_mixed_to_approved_pipeline(
    controller: CodexSessionController,
    mixed_workspace_root: Path,
    target_project: str,
    evidence: tuple[Any, ...],
    overrides: Mapping[str, str],
    source_registry: SourceRegistry,
    destination_workspace_root: Path,
    reporting_request: CodexOperationRequest,
    *,
    investigation_timeout_seconds: float = 300.0,
) -> MixedToApprovedPipelineResult:
    """Run the entire frozen flow against one mixed workspace, returning the
    same Codex session id used throughout and the materialized approved
    workspace it was resumed on.

    Any step failing (Codex investigation, human-review evidence mismatch,
    materialization, binding, or reporting) raises immediately: nothing later
    in the sequence runs, and no approved workspace is ever partially
    published or bound.
    """
    spans = build_spans(evidence)
    investigation = start_mixed_workspace_investigation(
        controller,
        mixed_workspace_root,
        target_project,
        evidence,
        spans,
        timeout_seconds=investigation_timeout_seconds,
    )
    record_scope_awaiting_review(controller, investigation.controller_session_id)
    approved_scope = approve_source_scope(
        investigation.scoping_result, evidence, overrides
    )
    materialization = materialize_approved_scope(
        mixed_workspace_root,
        approved_scope,
        evidence,
        source_registry,
        destination_workspace_root,
    )
    reporting = bind_and_report_on_approved_workspace(
        controller,
        investigation.controller_session_id,
        materialization.destination_root,
        workspace_fingerprint(materialization.destination_root),
        reporting_request,
    )
    return MixedToApprovedPipelineResult(
        controller_session_id=investigation.controller_session_id,
        codex_session_id=investigation.codex_session_id,
        approved_scope=approved_scope,
        materialization=materialization,
        reporting=reporting,
    )
