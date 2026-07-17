"""Shared typed models for deterministic Project Aurora artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactDefinition:
    """Fixed definition for one synthetic Project Aurora artifact."""

    source_id: str
    evidence_id: str
    author: str
    timestamp: str
    source_type: str
    timeline_position: int
    business_purpose: str
    relative_path: str
    title: str


@dataclass(frozen=True)
class EvidenceRecord:
    """Typed, normalized evidence extracted from one production artifact."""

    source_id: str
    evidence_id: str
    author: str
    timestamp: str
    source_type: str
    timeline_position: int
    business_purpose: str
    title: str
    uri: str
    artifact_sha256: str
    content: str
