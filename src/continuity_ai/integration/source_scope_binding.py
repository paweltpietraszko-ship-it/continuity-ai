"""Derive the opaque Approved-only binding for one human-approved Source Scoping scope.

Source Scoping and Approved-only are independent contracts, developed and
audited separately: Source Scoping owns evidence classification and human
review, Approved-only owns fail-closed file materialization and never learns
source names, paths, or the reviewed decision graph. This module is the one
normative place that derives Approved-only's opaque `SourceScopeBinding` from
Source Scoping's `ApprovedSourceScope`, so both tracks can evolve independently
without duplicating hashing logic or silently drifting apart.

An `ApprovedSourceScope` is only meaningful relative to the exact evidence
snapshot it was reviewed against (`evidence_fingerprints`). Every function
here therefore also takes the caller's *current* evidence tuple and re-proves
the scope is still bound to it before trusting any registry entry — a scope
approved against an older, different, or reordered evidence snapshot must
never be treated as approval for whatever evidence happens to be loaded now.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from continuity_ai.approved_workspace.canonical import canonical_json_bytes, sha256_bytes
from continuity_ai.approved_workspace.contracts import SourceScopeBinding
from continuity_ai.domain import ReasoningEvidence
from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import ApprovedSourceScope
from continuity_ai.source_scoping.review import validate_approved_scope_evidence
from continuity_ai.source_scoping.serialization import approved_scope_to_payload

BINDING_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class SourceRegistryEntry:
    """One explicit, human-registered source location for one piece of evidence.

    Never constructed by inferring a path from an evidence_id or filename:
    every entry must come from whatever authoritative ingestion registry
    recorded the evidence_id -> relative_path -> SHA-256 mapping at the time
    the source was ingested.
    """

    relative_path: str
    sha256: str
    byte_size: int | None = None


SourceRegistry = Mapping[str, SourceRegistryEntry]


def _evidence_by_id(
    evidence: tuple[ReasoningEvidence, ...]
) -> dict[str, ReasoningEvidence]:
    by_id: dict[str, ReasoningEvidence] = {}
    for record in evidence:
        if record.evidence_id in by_id:
            raise ValidationError()
        by_id[record.evidence_id] = record
    return by_id


def resolve_approved_registry_entries(
    scope: ApprovedSourceScope,
    evidence: tuple[ReasoningEvidence, ...],
    source_registry: SourceRegistry,
) -> tuple[tuple[str, SourceRegistryEntry], ...]:
    """Validate the scope against the current evidence snapshot and resolve
    exactly one registry entry per approved (INCLUDE) evidence_id.

    Fails closed if: the scope is stale relative to `evidence` (added,
    removed, reordered, or content-changed records —
    `validate_approved_scope_evidence` rejects all of these); an approved
    evidence_id has no exactly-matching current evidence record; that
    evidence_id has no `source_registry` entry; or the registry entry's
    declared SHA-256 disagrees with the current record's own
    `artifact_sha256` — i.e. the registry does not describe the same
    reviewed file the scope was actually approved against.
    """
    validate_approved_scope_evidence(scope, evidence)
    by_id = _evidence_by_id(evidence)
    resolved: list[tuple[str, SourceRegistryEntry]] = []
    for evidence_id in scope.approved_evidence_ids:
        record = by_id.get(evidence_id)
        if record is None:
            raise ValidationError()
        entry = source_registry.get(evidence_id)
        if entry is None:
            raise ValidationError()
        if entry.sha256 != record.artifact_sha256:
            raise ValidationError()
        resolved.append((evidence_id, entry))
    return tuple(resolved)


def compute_source_scope_binding(
    scope: ApprovedSourceScope,
    evidence: tuple[ReasoningEvidence, ...],
    source_registry: SourceRegistry,
) -> SourceScopeBinding:
    """Derive the opaque Approved-only binding for one human-approved scope.

    `binding_sha256` is a pure hash of the entire approved scope payload,
    including excluded and user-resolved decisions, so a workspace publication
    can never be replayed against a scope whose exclusions were silently
    altered after human review.

    `expected_source_fingerprints` carries only the real file-content SHA-256
    of *approved* (INCLUDE) evidence — never Source Scoping's own
    `evidence_fingerprints` (a fingerprint of the reviewed evidence *record*,
    not of file bytes) and never a value inferred from an evidence_id or
    filename. Approved-only cross-checks this exact field against the file
    hashes it is asked to copy, so a mismatch fails the materialization closed
    before any byte is staged. Before any of that, this function itself
    fails closed if `evidence` is not the exact snapshot `scope` was approved
    against, or if a registry entry disagrees with that snapshot
    (`resolve_approved_registry_entries`).
    """
    resolved = resolve_approved_registry_entries(scope, evidence, source_registry)
    wrapper = {
        "binding_schema_version": BINDING_SCHEMA_VERSION,
        "approved_source_scope": approved_scope_to_payload(scope),
    }
    binding_sha256 = sha256_bytes(canonical_json_bytes(wrapper))
    expected_source_fingerprints = tuple(entry.sha256 for _, entry in resolved)
    return SourceScopeBinding(
        binding_sha256=binding_sha256,
        expected_source_fingerprints=expected_source_fingerprints,
    )
