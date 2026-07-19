"""Immutable public contracts for approved-only workspace publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias


JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | Sequence["JsonValue"]


class AttestationApprovalStatus(str, Enum):
    """Explicit caller state; only ``APPROVED`` can cross this boundary."""

    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class PublicationStatus(str, Enum):
    """Publication outcome represented by a successful receipt."""

    PUBLISHED = "published"


class FailureCategory(str, Enum):
    """Sanitized failure categories that never contain evidence details."""

    INVALID_INPUT = "invalid_input"
    UNSAFE_PATH = "unsafe_path"
    PATH_COLLISION = "path_collision"
    SOURCE_MISSING = "source_missing"
    SOURCE_NOT_REGULAR = "source_not_regular"
    SOURCE_LINK = "source_link_or_reparse_point"
    SOURCE_FINGERPRINT_MISMATCH = "source_fingerprint_mismatch"
    SOURCE_MUTATED = "source_mutated"
    DESTINATION_OVERLAP = "destination_overlap"
    DESTINATION_EXISTS = "destination_exists"
    DESTINATION_PARENT_UNSAFE = "destination_parent_unsafe"
    PUBLICATION_FAILED = "publication_failed"


@dataclass(frozen=True, slots=True)
class ApprovedArtifactSelection:
    """One and only one explicitly approved source file."""

    evidence_id: str
    source_relative_path: str
    expected_sha256: str
    expected_byte_size: int | None = None


@dataclass(frozen=True, slots=True)
class ApprovedHumanAttestation:
    """Explicitly reviewed downstream data with human provenance."""

    attestation_id: str
    downstream_data: Mapping[str, JsonValue]
    human_actor_id: str
    approval_reference: str
    approval_status: AttestationApprovalStatus


@dataclass(frozen=True, slots=True)
class SourceScopeBinding:
    """Opaque hashes supplied by Source Scoping without source names or paths."""

    binding_sha256: str
    expected_source_fingerprints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ApprovedWorkspaceRequest:
    """Complete immutable request accepted by the materialization boundary."""

    original_workspace_root: Path
    approved_artifacts: tuple[ApprovedArtifactSelection, ...]
    approved_attestations: tuple[ApprovedHumanAttestation, ...]
    destination_workspace_root: Path
    source_scope_binding: SourceScopeBinding | None = None


@dataclass(frozen=True, slots=True)
class MaterializationReceipt:
    """Sanitized immutable proof of one successful atomic publication."""

    schema_version: str
    approved_workspace_id: str
    destination_root: Path
    final_workspace_fingerprint: str
    manifest_fingerprint: str
    approved_artifact_count: int
    approved_attestation_count: int
    source_scope_binding: SourceScopeBinding | None
    publication_status: PublicationStatus
    failure_category: FailureCategory | None = None


class ApprovedWorkspaceMaterializationError(RuntimeError):
    """A fail-closed error carrying only a stable, sanitized category."""

    def __init__(self, category: FailureCategory) -> None:
        self.category = category
        super().__init__(f"Approved workspace materialization failed: {category.value}.")
