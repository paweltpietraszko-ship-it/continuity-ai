"""Retained-analysis persistence boundary.

Owns serialization, strict structural validation, and newest-entry restore policy
for a `SavedAnalysis` retained in the encrypted vault. Semantic `AnalysisResult`
rules are never reimplemented here: restoration always delegates to the same
canonical validator that checks fresh reasoning-provider output, so a restored
analysis is held to exactly the same contract as one produced moments ago.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from continuity_ai.domain import EvidenceSnapshot, PROVENANCE_VALUES, SavedAnalysis
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import is_valid_timestamp
from continuity_ai.reasoning_pipeline import SUPPORTED_SCHEMA_VERSION, validate_analysis_payload

_SHA256_HEX_ALPHABET = frozenset("0123456789abcdef")
_SHA256_HEX_LENGTH = 64

_SNAPSHOT_KEYS = {"analysis_id", "created_at", "records", "spans", "prompt_version", "schema_version", "provider_id"}
_RECORD_KEYS = {"evidence_id", "provenance", "title", "author_or_actor", "timestamp", "source_type", "canonical_content_sha256", "artifact_sha256"}
_SPAN_KEYS = {"span_id", "evidence_id", "exact_text"}
_UNIT_KEYS = {"analysis_id", "created_at", "question", "result", "evidence_snapshot"}

RETAINED_ANALYSIS_NONE = "none"
RETAINED_ANALYSIS_VALID = "valid"
RETAINED_ANALYSIS_INVALID = "invalid"


class InvalidSavedAnalysisError(ValueError):
    """A retained saved-analysis payload is malformed, incomplete, or semantically
    invalid. Raised only at the decrypted-vault-payload trust boundary; never
    exposes payload content or the wrapped cause to callers."""


@dataclass(frozen=True)
class RetainedAnalysisRestoration:
    """Outcome of inspecting the newest vault-retained analysis entry only.

    A malformed newest entry is deliberately never skipped in favor of an older,
    still-valid one: that would silently present stale history as current."""
    status: str
    saved: SavedAnalysis | None


def _require(condition: bool) -> None:
    if not condition:
        raise InvalidSavedAnalysisError()


def _is_sha256_hex(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA256_HEX_LENGTH and set(value) <= _SHA256_HEX_ALPHABET


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def saved_analysis_to_payload(saved: SavedAnalysis) -> dict[str, Any]:
    """Serialize a complete retained analysis unit into a JSON-safe vault payload record."""
    r = saved.result
    snap = saved.evidence_snapshot

    def grounded(gs: Any) -> dict[str, Any] | None:
        return None if gs is None else {"statement": gs.statement, "span_ids": list(gs.span_ids)}

    return {
        "analysis_id": saved.analysis_id,
        "created_at": saved.created_at,
        "question": saved.question,
        "result": {
            "schema_version": r.schema_version,
            "analysis_status": r.analysis_status,
            "continuity_break_kind": r.continuity_break_kind,
            "current_state": grounded(r.current_state),
            "semantic_annotations": [
                {"evidence_id": a.evidence_id, "propagation_role": a.propagation_role, "context_tags": list(a.context_tags)}
                for a in r.semantic_annotations
            ],
            "continuity_break": grounded(r.continuity_break),
            "next_action": grounded(r.next_action),
        },
        "evidence_snapshot": {
            "analysis_id": snap.analysis_id,
            "created_at": snap.created_at,
            "records": [dict(rec) for rec in snap.records],
            "spans": [dict(sp) for sp in snap.spans],
            "prompt_version": snap.prompt_version,
            "schema_version": snap.schema_version,
            "provider_id": snap.provider_id,
        },
    }


def _validate_record(record: Any, seen_ids: set[str]) -> dict[str, Any]:
    _require(isinstance(record, dict) and set(record) == _RECORD_KEYS)
    eid = record["evidence_id"]
    _require(_non_empty_str(eid) and eid not in seen_ids)
    _require(_non_empty_str(record["title"]))
    _require(_non_empty_str(record["author_or_actor"]))
    _require(_non_empty_str(record["source_type"]))
    _require(is_valid_timestamp(record["timestamp"]))
    _require(record["provenance"] in PROVENANCE_VALUES)
    _require(_is_sha256_hex(record["canonical_content_sha256"]))
    artifact_hash = record["artifact_sha256"]
    _require(artifact_hash is None or _is_sha256_hex(artifact_hash))
    seen_ids.add(eid)
    return dict(record)


def _validate_span(span: Any, record_ids: set[str], seen_ids: set[str]) -> dict[str, Any]:
    _require(isinstance(span, dict) and set(span) == _SPAN_KEYS)
    sid = span["span_id"]
    _require(_non_empty_str(sid) and sid not in seen_ids)
    _require(span["evidence_id"] in record_ids)
    _require(_non_empty_str(span["exact_text"]))
    seen_ids.add(sid)
    return dict(span)


def _validate_snapshot_structure(data: Any) -> EvidenceSnapshot:
    """Structural validation only: field shapes, typing, hash formats, and internal
    span/record ownership. Carries no opinion about the analysis semantics that
    will later reference this snapshot as authoritative evidence/span identity."""
    _require(isinstance(data, dict) and set(data) == _SNAPSHOT_KEYS)
    _require(_non_empty_str(data["analysis_id"]))
    _require(is_valid_timestamp(data["created_at"]))
    _require(_non_empty_str(data["prompt_version"]))
    _require(data["schema_version"] == SUPPORTED_SCHEMA_VERSION)
    _require(_non_empty_str(data["provider_id"]))

    records, spans = data["records"], data["spans"]
    _require(isinstance(records, list) and bool(records))
    _require(isinstance(spans, list) and bool(spans))

    record_ids: set[str] = set()
    norm_records = tuple(_validate_record(r, record_ids) for r in records)
    span_ids: set[str] = set()
    norm_spans = tuple(_validate_span(s, record_ids, span_ids) for s in spans)

    return EvidenceSnapshot(
        data["analysis_id"], data["created_at"], norm_records, norm_spans,
        data["prompt_version"], data["schema_version"], data["provider_id"],
    )


def _snapshot_authority(snapshot: EvidenceSnapshot) -> tuple[set[str], dict[str, str]]:
    evidence_ids = {str(r["evidence_id"]) for r in snapshot.records}
    span_owner = {str(s["span_id"]): str(s["evidence_id"]) for s in snapshot.spans}
    return evidence_ids, span_owner


def saved_analysis_from_payload(data: Any) -> SavedAnalysis:
    """Reconstruct and validate one complete retained analysis unit: strict snapshot
    structure, the exact canonical semantic rules fresh provider output is held to,
    and binding between the top-level identity and the snapshot's own identity."""
    try:
        _require(isinstance(data, dict) and set(data) == _UNIT_KEYS)
        analysis_id, created_at, question = data["analysis_id"], data["created_at"], data["question"]
        _require(_non_empty_str(analysis_id))
        _require(is_valid_timestamp(created_at))
        _require(_non_empty_str(question))

        snapshot = _validate_snapshot_structure(data["evidence_snapshot"])
        evidence_ids, span_owner = _snapshot_authority(snapshot)
        result = validate_analysis_payload(data["result"], evidence_ids, span_owner)

        _require(analysis_id == snapshot.analysis_id)
        _require(created_at == snapshot.created_at)
        _require(result.schema_version == snapshot.schema_version)

        return SavedAnalysis(analysis_id, created_at, result, snapshot, question)
    except InvalidSavedAnalysisError:
        raise
    except (ValidationError, KeyError, TypeError, ValueError) as exc:
        raise InvalidSavedAnalysisError() from exc


def restore_latest(saved_analyses: list[Any]) -> RetainedAnalysisRestoration:
    """Inspect the newest retained entry only. Never scans backward past a
    malformed newest entry to display an older one as current (F-03)."""
    if not saved_analyses:
        return RetainedAnalysisRestoration(RETAINED_ANALYSIS_NONE, None)
    try:
        saved = saved_analysis_from_payload(saved_analyses[-1])
    except InvalidSavedAnalysisError:
        return RetainedAnalysisRestoration(RETAINED_ANALYSIS_INVALID, None)
    return RetainedAnalysisRestoration(RETAINED_ANALYSIS_VALID, saved)
