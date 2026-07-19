"""Orchestrate INCLUDE-only materialization of an approved workspace.

This module is the only glue that turns a human-approved Source Scoping
decision into an Approved-only materialization request. It never reads
EXCLUDE or ambiguous evidence, and it never infers a source path from a
filename or evidence_id: every artifact's location and expected file hash
comes from an explicit registry supplied by the caller, and that registry is
only trusted once `resolve_approved_registry_entries` has proven it describes
the exact evidence snapshot the scope was approved against (fail-closed on a
stale, altered, or reordered snapshot, or on a registry entry whose hash
disagrees with that snapshot). Whether a registry entry's declared hash
actually matches the file on disk is verified byte-for-byte by the
Approved-only materializer itself during copy.
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
from continuity_ai.domain import ReasoningEvidence
from continuity_ai.integration.source_scope_binding import (
    SourceRegistry,
    compute_source_scope_binding,
    resolve_approved_registry_entries,
)
from continuity_ai.source_scoping.domain import ApprovedSourceScope


def build_approved_workspace_request(
    original_workspace_root: Path,
    approved_scope: ApprovedSourceScope,
    evidence: tuple[ReasoningEvidence, ...],
    source_registry: SourceRegistry,
    destination_workspace_root: Path,
    *,
    approved_attestations: tuple[ApprovedHumanAttestation, ...] = (),
) -> ApprovedWorkspaceRequest:
    """Build one materialization request covering exactly the INCLUDE evidence.

    `evidence` must be the caller's current, ordered evidence snapshot.
    `resolve_approved_registry_entries` first re-proves `approved_scope` is
    still bound to that exact snapshot, then resolves exactly one validated
    `source_registry` entry per approved evidence_id — any staleness, missing
    entry, or registry/evidence hash disagreement fails closed before a
    single `ApprovedArtifactSelection` is built.
    """
    resolved = resolve_approved_registry_entries(
        approved_scope, evidence, source_registry
    )
    artifacts = tuple(
        ApprovedArtifactSelection(
            evidence_id=evidence_id,
            source_relative_path=entry.relative_path,
            expected_sha256=entry.sha256,
            expected_byte_size=entry.byte_size,
        )
        for evidence_id, entry in resolved
    )
    binding = compute_source_scope_binding(approved_scope, evidence, source_registry)
    return ApprovedWorkspaceRequest(
        original_workspace_root=original_workspace_root,
        approved_artifacts=artifacts,
        approved_attestations=approved_attestations,
        destination_workspace_root=destination_workspace_root,
        source_scope_binding=binding,
    )


def materialize_approved_scope(
    original_workspace_root: Path,
    approved_scope: ApprovedSourceScope,
    evidence: tuple[ReasoningEvidence, ...],
    source_registry: SourceRegistry,
    destination_workspace_root: Path,
    *,
    approved_attestations: tuple[ApprovedHumanAttestation, ...] = (),
) -> MaterializationReceipt:
    """Build and materialize one approved-only workspace for a human-approved scope."""
    request = build_approved_workspace_request(
        original_workspace_root,
        approved_scope,
        evidence,
        source_registry,
        destination_workspace_root,
        approved_attestations=approved_attestations,
    )
    return materialize_approved_workspace(request)
