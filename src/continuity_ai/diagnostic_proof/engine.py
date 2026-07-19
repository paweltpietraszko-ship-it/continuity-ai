"""Oracle-blind execution of the production mixed-to-approved lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from continuity_ai.codex_process import workspace_fingerprint
from continuity_ai.codex_session import CodexOperationRequest, CodexSessionController
from continuity_ai.diagnostic_proof.models import CompletedDiagnosticRun
from continuity_ai.diagnostic_proof.preparation import _oracle_artifacts_absent
from continuity_ai.domain import ReasoningEvidence
from continuity_ai.evidence import build_spans
from continuity_ai.integration.approved_workspace_flow import materialize_approved_scope
from continuity_ai.integration.codex_session_flow import (
    bind_and_report_on_approved_workspace,
    record_scope_awaiting_review,
    start_mixed_workspace_investigation,
)
from continuity_ai.integration.codex_source_scoping_provider import CodexSourceScopingProvider
from continuity_ai.integration.source_scope_binding import SourceRegistryEntry
from continuity_ai.source_scoping.domain import SourceScopingResult
from continuity_ai.source_scoping.review import approve_source_scope
from continuity_ai.unseen_workspace import load_workspace

ReviewCallback = Callable[[SourceScopingResult], Mapping[str, str]]

_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relative_paths"],
    "properties": {
        "relative_paths": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        }
    },
}


class DiagnosticEngineError(RuntimeError):
    """Raised when an engine result cannot form a completed proof submission."""


def run_diagnostic_engine(
    controller: CodexSessionController,
    input_root: Path,
    approved_workspace_root: Path,
    review: ReviewCallback,
    *,
    timeout_seconds: float = 300.0,
) -> CompletedDiagnosticRun:
    """Run production functions with only a standalone engine input root.

    No seed, run root, oracle path, or oracle data is accepted by this boundary.
    The returned value exists only after the approved-workspace reporting call
    has completed successfully.
    """

    engine_root = Path(input_root).resolve(strict=True)
    diagnostic_run_root = _require_oracle_free_run(engine_root)
    approved_root = Path(approved_workspace_root)
    workspace = load_workspace(engine_root)
    evidence, registry = _adapt_engine_input(workspace.records, engine_root)
    spans = build_spans(evidence)
    original_fingerprint = workspace_fingerprint(engine_root)

    investigation = start_mixed_workspace_investigation(
        controller,
        engine_root,
        workspace.target_project.name,
        evidence,
        spans,
        timeout_seconds=timeout_seconds,
    )
    _require_oracle_free_run(engine_root, expected_run_root=diagnostic_run_root)
    record_scope_awaiting_review(controller, investigation.controller_session_id)
    overrides = dict(review(investigation.scoping_result))
    approved_scope = approve_source_scope(
        investigation.scoping_result,
        evidence,
        overrides,
    )
    materialization = materialize_approved_scope(
        engine_root,
        approved_scope,
        evidence,
        registry,
        approved_root,
    )
    _require_oracle_free_run(engine_root, expected_run_root=diagnostic_run_root)
    reporting = bind_and_report_on_approved_workspace(
        controller,
        investigation.controller_session_id,
        materialization.destination_root,
        workspace_fingerprint(materialization.destination_root),
        CodexOperationRequest(
            (
                "List every non-.continuity regular file visible in the current "
                "approved-only workspace. Return sorted POSIX relative paths and "
                "do not infer or mention files that are not visible."
            ),
            _REPORT_SCHEMA,
            timeout_seconds,
        ),
    )
    _require_oracle_free_run(engine_root, expected_run_root=diagnostic_run_root)
    reported_paths = _reported_paths(reporting.structured_output)
    return CompletedDiagnosticRun(
        input_root=engine_root,
        input_fingerprint=original_fingerprint,
        oracle_absent_during_engine_execution=True,
        approved_workspace_root=materialization.destination_root,
        controller_session_id=investigation.controller_session_id,
        investigation_codex_session_id=investigation.codex_session_id,
        reporting_codex_session_id=reporting.codex_session_id,
        provider_identity=CodexSourceScopingProvider.provider_id,
        automatic_decisions=tuple(
            (decision.evidence_id, decision.association_status)
            for decision in investigation.scoping_result.decisions
        ),
        human_overrides=tuple(sorted(overrides.items())),
        approved_evidence_ids=approved_scope.approved_evidence_ids,
        excluded_evidence_ids=approved_scope.excluded_evidence_ids,
        evidence_paths=tuple((record.evidence_id, str(record.uri)) for record in evidence),
        reported_relative_paths=reported_paths,
        materialization=materialization,
    )


def _require_oracle_free_run(
    input_root: Path, *, expected_run_root: Path | None = None
) -> Path:
    """Fail closed unless standalone input is the only published run tree."""

    engine_root = input_root.parent
    run_root = engine_root.parent.resolve(strict=True)
    if (
        input_root.name != "input"
        or engine_root.name != "engine"
        or (expected_run_root is not None and run_root != expected_run_root)
        or {path.name for path in run_root.iterdir()} != {"engine"}
        or {path.name for path in engine_root.iterdir()} != {"input"}
        or not _oracle_artifacts_absent(run_root)
    ):
        raise DiagnosticEngineError(
            "Diagnostic engine requires an oracle-free standalone run root."
        )
    return run_root


def _adapt_engine_input(records: tuple[Any, ...], root: Path) -> tuple[
    tuple[ReasoningEvidence, ...], dict[str, SourceRegistryEntry]
]:
    evidence: list[ReasoningEvidence] = []
    registry: dict[str, SourceRegistryEntry] = {}
    for index, record in enumerate(records, start=1):
        relative_path = record.relative_path
        item = ReasoningEvidence(
            evidence_id=record.evidence_id,
            source_type=f"workspace_{record.source_format}",
            author_or_actor="Workspace record",
            timestamp="2026-01-01T00:00:00Z",
            title=f"Workspace record {index}",
            content=record.content,
            provenance="artifact",
            uri=relative_path,
            artifact_sha256=record.sha256,
        )
        evidence.append(item)
        registry[item.evidence_id] = SourceRegistryEntry(
            relative_path=relative_path,
            sha256=record.sha256,
            byte_size=(root / Path(*relative_path.split("/"))).stat().st_size,
        )
    return tuple(evidence), registry


def _reported_paths(value: object) -> tuple[str, ...]:
    if not isinstance(value, dict) or set(value) != {"relative_paths"}:
        raise DiagnosticEngineError("Reporting output must contain only relative_paths.")
    paths = value["relative_paths"]
    if not isinstance(paths, list) or any(
        not isinstance(path, str) or not path.strip() or path != path.strip()
        for path in paths
    ):
        raise DiagnosticEngineError("Reported relative paths are invalid.")
    return tuple(paths)
