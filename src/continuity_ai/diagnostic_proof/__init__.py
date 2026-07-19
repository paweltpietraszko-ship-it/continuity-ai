"""Isolated Diagnostic Proof Core v0.1 public API."""

from continuity_ai.diagnostic_proof.engine import (
    DiagnosticEngineError,
    run_diagnostic_engine,
)
from continuity_ai.diagnostic_proof.evaluator import (
    DiagnosticEvaluationError,
    apply_controlled_workspace_tamper,
    evaluate_completed_diagnostic_run,
    render_diagnostic_json,
    render_diagnostic_markdown,
    write_diagnostic_reports,
)
from continuity_ai.diagnostic_proof.models import (
    CompletedDiagnosticRun,
    DiagnosticClaim,
    DiagnosticEvaluationWorkspace,
    DiagnosticProofArtifacts,
    DiagnosticProofReport,
    DiagnosticWorkspace,
)
from continuity_ai.diagnostic_proof.preparation import (
    prepare_diagnostic_workspace,
    regenerate_diagnostic_evaluation,
)

__all__ = [
    "CompletedDiagnosticRun",
    "DiagnosticClaim",
    "DiagnosticEngineError",
    "DiagnosticEvaluationError",
    "DiagnosticEvaluationWorkspace",
    "DiagnosticProofArtifacts",
    "DiagnosticProofReport",
    "DiagnosticWorkspace",
    "apply_controlled_workspace_tamper",
    "evaluate_completed_diagnostic_run",
    "prepare_diagnostic_workspace",
    "regenerate_diagnostic_evaluation",
    "render_diagnostic_json",
    "render_diagnostic_markdown",
    "run_diagnostic_engine",
    "write_diagnostic_reports",
]
