"""Canonical evidence adapters, spans, snapshots, and citations."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from continuity_ai.domain import AuthenticatedUserAttestation, CitationCard, EvidenceSnapshot, ReasoningEvidence, EvidenceSpan, SavedAnalysis, utc_now
from continuity_ai.models import EvidenceRecord

SNAPSHOT_SOURCE_STATUS = "snapshot"
SOURCE_CHANGED_STATUS = "source_changed_since_analysis"

def _norm_ts(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def is_valid_timestamp(ts: object) -> bool:
    if not isinstance(ts, str):
        return False
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False

def artifact_to_reasoning(record: EvidenceRecord) -> ReasoningEvidence:
    return ReasoningEvidence(record.evidence_id, record.source_type, record.author, _norm_ts(record.timestamp), record.title, record.content, "artifact", record.uri, record.artifact_sha256)

def attestation_to_reasoning(a: AuthenticatedUserAttestation) -> ReasoningEvidence:
    return ReasoningEvidence(a.evidence_id, "authenticated_user_attestation", a.actor_display_name, _norm_ts(a.asserted_at), "Authenticated user attestation", a.statement, "authenticated_user_attestation")

def order_evidence(records: list[ReasoningEvidence] | tuple[ReasoningEvidence, ...]) -> tuple[ReasoningEvidence, ...]:
    return tuple(sorted(records, key=lambda r: (_norm_ts(r.timestamp), r.evidence_id)))

def content_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def build_spans(records: tuple[ReasoningEvidence, ...]) -> tuple[EvidenceSpan, ...]:
    spans: list[EvidenceSpan] = []
    for rec in records:
        idx = 1
        for line in rec.content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if not line.strip():
                continue
            spans.append(EvidenceSpan(f"{rec.evidence_id}:L{idx:03d}", rec.evidence_id, line, idx))
            idx += 1
    return tuple(spans)

def span_lookup(spans: tuple[EvidenceSpan, ...]) -> dict[str, EvidenceSpan]:
    return {s.span_id: s for s in spans}

def make_snapshot(analysis_id: str, records: tuple[ReasoningEvidence, ...], spans: tuple[EvidenceSpan, ...], prompt_version: str, schema_version: str, provider_id: str) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        analysis_id, utc_now(),
        tuple({"evidence_id": r.evidence_id, "provenance": r.provenance, "title": r.title, "author_or_actor": r.author_or_actor, "timestamp": r.timestamp, "source_type": r.source_type, "canonical_content_sha256": content_sha256(r.content), "artifact_sha256": r.artifact_sha256} for r in records),
        tuple({"span_id": s.span_id, "evidence_id": s.evidence_id, "exact_text": s.text} for s in spans),
        prompt_version, schema_version, provider_id,
    )

def hydrate_citations(span_ids: tuple[str, ...], records: tuple[ReasoningEvidence, ...], spans: tuple[EvidenceSpan, ...], status: str = "current") -> tuple[CitationCard, ...]:
    by_rec = {r.evidence_id: r for r in records}; by_span = span_lookup(spans); cards=[]
    for sid in span_ids:
        sp = by_span[sid]; r = by_rec[sp.evidence_id]
        cards.append(CitationCard(r.evidence_id, sid, sp.text, r.title, r.author_or_actor, r.timestamp, r.source_type, r.provenance, status))
    return tuple(cards)

def snapshot_citation_statuses(evidence_snapshot_records: tuple[dict, ...], live: tuple[ReasoningEvidence, ...]) -> dict[str, str]:
    """Per-evidence-id source status for retained citations, computed against
    whatever live evidence is currently loaded.

    When no live evidence is loaded at all, no comparison is honestly possible, so
    every record keeps the neutral retained status rather than a fabricated claim."""
    if not live:
        return {str(r["evidence_id"]): SNAPSHOT_SOURCE_STATUS for r in evidence_snapshot_records}
    live_hash = {r.evidence_id: content_sha256(r.content) for r in live}
    statuses: dict[str, str] = {}
    for r in evidence_snapshot_records:
        eid = str(r["evidence_id"])
        matches = live_hash.get(eid) == r["canonical_content_sha256"]
        statuses[eid] = SNAPSHOT_SOURCE_STATUS if matches else SOURCE_CHANGED_STATUS
    return statuses

def hydrate_snapshot_citations(saved: SavedAnalysis, span_ids: tuple[str, ...], status_by_evidence_id: dict[str, str] | None = None) -> tuple[CitationCard, ...]:
    records = {str(r["evidence_id"]): r for r in saved.evidence_snapshot.records}
    spans = {s["span_id"]: s for s in saved.evidence_snapshot.spans}
    cards = []
    for sid in span_ids:
        if sid not in spans: raise ValueError("incomplete snapshot")
        sp = spans[sid]; rec = records[sp["evidence_id"]]
        status = SNAPSHOT_SOURCE_STATUS if status_by_evidence_id is None else status_by_evidence_id.get(str(rec["evidence_id"]), SNAPSHOT_SOURCE_STATUS)
        cards.append(CitationCard(str(rec["evidence_id"]), sid, sp["exact_text"], str(rec["title"]), str(rec["author_or_actor"]), str(rec["timestamp"]), str(rec["source_type"]), rec["provenance"], status))
    return tuple(cards)

def compare_live_to_snapshot(saved: SavedAnalysis, live: tuple[ReasoningEvidence, ...]) -> str:
    live_hash = {r.evidence_id: content_sha256(r.content) for r in live}
    for r in saved.evidence_snapshot.records:
        if live_hash.get(str(r["evidence_id"])) != r["canonical_content_sha256"]:
            return SOURCE_CHANGED_STATUS
    return "current"
