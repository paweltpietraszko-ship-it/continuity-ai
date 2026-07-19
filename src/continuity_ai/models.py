"""Shared typed models for deterministic artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactDefinition:
    """Fixed definition for one synthetic artifact."""

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
    """Typed, normalized evidence extracted from one production artifact.

    Deliberately excludes interpretive fixture fields such as timeline
    position or business purpose: production ingestion must carry only
    facts the artifact itself attests to, plus its normalized content.
    """

    source_id: str
    evidence_id: str
    author: str
    timestamp: str
    source_type: str
    title: str
    uri: str
    artifact_sha256: str
    content: str
