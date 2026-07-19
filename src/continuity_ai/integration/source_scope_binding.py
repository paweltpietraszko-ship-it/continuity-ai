"""Derive the opaque Approved-only binding for one human-approved Source Scoping scope.

Source Scoping and Approved-only are independent contracts, developed and
audited separately: Source Scoping owns evidence classification and human
review, Approved-only owns fail-closed file materialization and never learns
source names, paths, or the reviewed decision graph. This module is the one
normative place that derives Approved-only's opaque `SourceScopeBinding` from
Source Scoping's `ApprovedSourceScope`, so both tracks can evolve independently
without duplicating hashing logic or silently drifting apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from continuity_ai.approved_workspace.canonical import canonical_json_bytes, sha256_bytes
from continuity_ai.approved_workspace.contracts import SourceScopeBinding
from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import ApprovedSourceScope
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


def compute_source_scope_binding(
    scope: ApprovedSourceScope,
    source_registry: SourceRegistry,
) -> SourceScopeBinding:
    """Derive the opaque Approved-only binding for one human-approved scope.

    `binding_sha256` is a pure hash of the entire approved scope payload,
    including excluded and user-resolved decisions, so a workspace publication
    can never be replayed against a scope whose exclusions were silently
    altered after human review.

    `expected_source_fingerprints` carries only the real file-content SHA-256
    of *approved* (INCLUDE) evidence, looked up in `source_registry` — never
    Source Scoping's own `evidence_fingerprints` (a fingerprint of the
    reviewed evidence *record*, not of file bytes) and never a value inferred
    from an evidence_id or filename. Approved-only cross-checks this exact
    field against the file hashes it is asked to copy, so a mismatch here
    fails the materialization closed before any byte is staged. An approved
    evidence_id absent from the registry fails closed the same way.
    """
    wrapper = {
        "binding_schema_version": BINDING_SCHEMA_VERSION,
        "approved_source_scope": approved_scope_to_payload(scope),
    }
    binding_sha256 = sha256_bytes(canonical_json_bytes(wrapper))
    fingerprints: list[str] = []
    for evidence_id in scope.approved_evidence_ids:
        entry = source_registry.get(evidence_id)
        if entry is None:
            raise ValidationError()
        fingerprints.append(entry.sha256)
    return SourceScopeBinding(
        binding_sha256=binding_sha256,
        expected_source_fingerprints=tuple(fingerprints),
    )
