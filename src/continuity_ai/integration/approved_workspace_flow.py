"""Orchestrate INCLUDE-only materialization of an approved workspace.

This module is the only glue that turns a human-approved Source Scoping
decision into an Approved-only materialization request. It never reads
EXCLUDE or ambiguous evidence, and it never infers a source path from a
filename or evidence_id: every artifact's location and expected file hash
comes from an explicit registry supplied by the caller. Whether a registry
entry's declared hash actually matches the file on disk is verified byte-for-
byte by the Approved-only materializer itself (fail-closed, before any
destination path is published); this module only enforces that every approved
evidence_id has a registry entry at all.
"""
from __future__ import annotations

from pathlib import Path

from continuity_ai.approved_workspace.contracts import (
    ApprovedArtifactSelection,
    ApprovedHumanAttestation,
    ApprovedWorkspaceRequest,
    MaterializationReceipt,
)
from continuity_ai.approved_workspace.materializer import materialize_approved_workspace
from continuity_ai.errors import ValidationError
from continuity_ai.integration.source_scope_binding import (
    SourceRegistry,
    compute_source_scope_binding,
)
from continuity_ai.source_scoping.domain import ApprovedSourceScope


def build_approved_workspace_request(
    original_workspace_root: Path,
    approved_scope: ApprovedSourceScope,
    source_registry: SourceRegistry,
    destination_workspace_root: Path,
    *,
    approved_attestations: tuple[ApprovedHumanAttestation, ...] = (),
) -> ApprovedWorkspaceRequest:
    """Build one materialization request covering exactly the INCLUDE evidence.

    Every artifact is looked up by evidence_id in `source_registry`, an
    explicit evidence_id -> SourceRegistryEntry map supplied by the caller.
    An approved evidence_id with no registry entry at all is rejected
    fail-closed before anything is staged; a registry entry whose declared
    hash disagrees with the real file on disk is caught by the Approved-only
    materializer's own byte-for-byte verification during copy.
    """
    artifacts: list[ApprovedArtifactSelection] = []
    for evidence_id in approved_scope.approved_evidence_ids:
        entry = source_registry.get(evidence_id)
        if entry is None:
            raise ValidationError()
        artifacts.append(
            ApprovedArtifactSelection(
                evidence_id=evidence_id,
                source_relative_path=entry.relative_path,
                expected_sha256=entry.sha256,
                expected_byte_size=entry.byte_size,
            )
        )
    binding = compute_source_scope_binding(approved_scope, source_registry)
    return ApprovedWorkspaceRequest(
        original_workspace_root=original_workspace_root,
        approved_artifacts=tuple(artifacts),
        approved_attestations=approved_attestations,
        destination_workspace_root=destination_workspace_root,
        source_scope_binding=binding,
    )


def materialize_approved_scope(
    original_workspace_root: Path,
    approved_scope: ApprovedSourceScope,
    source_registry: SourceRegistry,
    destination_workspace_root: Path,
    *,
    approved_attestations: tuple[ApprovedHumanAttestation, ...] = (),
) -> MaterializationReceipt:
    """Build and materialize one approved-only workspace for a human-approved scope."""
    request = build_approved_workspace_request(
        original_workspace_root,
        approved_scope,
        source_registry,
        destination_workspace_root,
        approved_attestations=approved_attestations,
    )
    return materialize_approved_workspace(request)
