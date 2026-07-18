"""Deterministic fingerprints for complete neutral evidence records."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def evidence_fingerprint(record: Any) -> str:
    payload = {
        "evidence_id": record.evidence_id,
        "source_type": record.source_type,
        "author_or_actor": record.author_or_actor,
        "timestamp": record.timestamp,
        "title": record.title,
        "content": record.content,
        "provenance": record.provenance,
        "uri": record.uri,
        "artifact_sha256": record.artifact_sha256,
    }
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
