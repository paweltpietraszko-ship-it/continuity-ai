"""Phase-transition orchestration for one Codex controller session across the
Source Scoping investigation-through-approved-report lifecycle.

Each function here maps directly onto CodexSessionController transitions
already defined and tested in `codex_session.py`; splitting them lets a
caller (Bridge, once wired) pause for asynchronous human review between
`record_scope_awaiting_review` and `bind_and_report_on_approved_workspace`,
rather than forcing the whole flow into one blocking call.

No step here can open a replacement Codex thread: `bind_approved_workspace`
never invokes Codex at all, and `start_reporting` requires and resumes the
exact retained `codex_session_id` from the investigation, failing closed if
it is absent or if Codex ever returns a different id.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from continuity_ai.codex_session import (
    CodexControllerSession,
    CodexOperationRequest,
    CodexSessionController,
    CodexSessionMismatch,
    InvocationReceipt,
)
from continuity_ai.integration.codex_source_scoping_provider import (
    CodexSourceScopingProvider,
)
from continuity_ai.source_scoping.domain import SourceScopingResult
from continuity_ai.source_scoping.service import run_source_scoping


@dataclass(frozen=True)
class InvestigationOutcome:
    controller_session_id: str
    codex_session_id: str
    scoping_result: SourceScopingResult
    session: CodexControllerSession


@dataclass(frozen=True)
class ReportingOutcome:
    controller_session_id: str
    codex_session_id: str
    session: CodexControllerSession
    receipt: InvocationReceipt
    structured_output: object


def start_mixed_workspace_investigation(
    controller: CodexSessionController,
    mixed_workspace_root: Path,
    target_project: str,
    evidence: tuple[Any, ...],
    spans: tuple[Any, ...],
    *,
    timeout_seconds: float = 300.0,
) -> InvestigationOutcome:
    """Create one controller session and classify evidence through the same
    Codex thread that will later resume on the approved-only workspace."""
    created = controller.create_session(mixed_workspace_root)
    provider = CodexSourceScopingProvider(
        controller,
        created.controller_session_id,
        mixed_workspace_root,
        timeout_seconds=timeout_seconds,
    )
    scoping_result = run_source_scoping(target_project, evidence, spans, provider)
    investigated = controller.get_session(created.controller_session_id)
    if investigated.codex_session_id is None:
        raise CodexSessionMismatch(
            "Investigation did not yield a retained genuine Codex session ID."
        )
    return InvestigationOutcome(
        controller_session_id=investigated.controller_session_id,
        codex_session_id=investigated.codex_session_id,
        scoping_result=scoping_result,
        session=investigated,
    )


def record_scope_awaiting_review(
    controller: CodexSessionController, controller_session_id: str
) -> CodexControllerSession:
    return controller.record_awaiting_human_review(controller_session_id)


def bind_and_report_on_approved_workspace(
    controller: CodexSessionController,
    controller_session_id: str,
    approved_workspace_root: Path,
    approved_workspace_fingerprint: str,
    request: CodexOperationRequest,
) -> ReportingOutcome:
    """Bind the approved-only workspace, then resume the same retained Codex
    session id on it."""
    controller.bind_approved_workspace(
        controller_session_id, approved_workspace_root, approved_workspace_fingerprint
    )
    result = controller.start_reporting(
        controller_session_id, approved_workspace_root, request
    )
    return ReportingOutcome(
        controller_session_id=result.session.controller_session_id,
        codex_session_id=result.session.codex_session_id,
        session=result.session,
        receipt=result.receipt,
        structured_output=result.structured_output,
    )
