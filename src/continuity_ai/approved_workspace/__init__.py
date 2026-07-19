"""Approved-only workspace materialization boundary."""

from continuity_ai.approved_workspace.contracts import (
    ApprovedArtifactSelection,
    ApprovedHumanAttestation,
    ApprovedWorkspaceMaterializationError,
    ApprovedWorkspaceRequest,
    AttestationApprovalStatus,
    FailureCategory,
    MaterializationReceipt,
    PublicationStatus,
    SourceScopeBinding,
)
from continuity_ai.approved_workspace.materializer import (
    APPROVED_ATTESTATIONS_RELATIVE_PATH,
    APPROVED_MANIFEST_RELATIVE_PATH,
    compute_workspace_fingerprint,
    materialize_approved_workspace,
)

__all__ = [
    "APPROVED_ATTESTATIONS_RELATIVE_PATH",
    "APPROVED_MANIFEST_RELATIVE_PATH",
    "ApprovedArtifactSelection",
    "ApprovedHumanAttestation",
    "ApprovedWorkspaceMaterializationError",
    "ApprovedWorkspaceRequest",
    "AttestationApprovalStatus",
    "FailureCategory",
    "MaterializationReceipt",
    "PublicationStatus",
    "SourceScopeBinding",
    "compute_workspace_fingerprint",
    "materialize_approved_workspace",
]
