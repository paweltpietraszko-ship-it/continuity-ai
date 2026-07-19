"""Neutral unseen-workspace generation, ingestion, and evaluation contracts."""

from continuity_ai.unseen_workspace.codex_workspace_spike import (
    CodexWorkspaceSpikeArtifacts,
    CodexWorkspaceSpikeError,
    classify_workspace_with_codex,
)
from continuity_ai.unseen_workspace.evaluator import (
    ScopeEvaluationError,
    evaluate_generated_run,
    evaluate_scope,
    load_classification_result,
)
from continuity_ai.unseen_workspace.generator import (
    UnseenWorkspaceGenerationError,
    generate_unseen_workspace,
)
from continuity_ai.unseen_workspace.ingestion import (
    RawWorkspaceIngestionError,
    load_workspace,
)
from continuity_ai.unseen_workspace.models import (
    ClassificationDecision,
    ClassificationResult,
    EvaluationReport,
    HumanOverride,
    OracleExposureStatus,
    ProjectReference,
    ProofClaim,
    ProofStatus,
    RawWorkspaceRecord,
    ScopeStatus,
    WorkspaceInput,
)
from continuity_ai.unseen_workspace.proof_claims import PROOF_CLAIM_NAMES
from continuity_ai.unseen_workspace.reporting import (
    EvaluationReportArtifacts,
    EvaluationReportWriteError,
    render_evaluation_json,
    render_evaluation_markdown,
    write_evaluation_reports,
)

__all__ = [
    "ClassificationDecision",
    "ClassificationResult",
    "CodexWorkspaceSpikeArtifacts",
    "CodexWorkspaceSpikeError",
    "EvaluationReport",
    "EvaluationReportArtifacts",
    "EvaluationReportWriteError",
    "HumanOverride",
    "OracleExposureStatus",
    "PROOF_CLAIM_NAMES",
    "ProjectReference",
    "ProofClaim",
    "ProofStatus",
    "RawWorkspaceIngestionError",
    "RawWorkspaceRecord",
    "ScopeEvaluationError",
    "ScopeStatus",
    "UnseenWorkspaceGenerationError",
    "WorkspaceInput",
    "classify_workspace_with_codex",
    "evaluate_generated_run",
    "evaluate_scope",
    "generate_unseen_workspace",
    "load_classification_result",
    "load_workspace",
    "render_evaluation_json",
    "render_evaluation_markdown",
    "write_evaluation_reports",
]
