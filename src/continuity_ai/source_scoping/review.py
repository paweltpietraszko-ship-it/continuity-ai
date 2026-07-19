"""Human review gate between model scoping and downstream analysis."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from continuity_ai.errors import ValidationError
from continuity_ai.evidence import build_spans
from continuity_ai.source_scoping.domain import (
    ApprovedSourceScope,
    ReviewedSourceDecision,
    SCHEMA_VERSION,
    SourceScopingResult,
)

_FINAL_STATUSES = frozenset({"included", "excluded"})
_FINGERPRINT_FIELDS = (
    "evidence_id",
    "source_type",
    "author_or_actor",
    "timestamp",
    "title",
    "content",
    "provenance",
    "uri",
    "artifact_sha256",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _record_fingerprint(record: Any) -> str:
    try:
        payload = {field: getattr(record, field) for field in _FINGERPRINT_FIELDS}
    except AttributeError:
        raise ValidationError() from None
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprints(evidence: tuple[Any, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (record.evidence_id, _record_fingerprint(record)) for record in evidence
    )


def approve_source_scope(
    result: SourceScopingResult,
    evidence: tuple[Any, ...],
    overrides: Mapping[str, str],
) -> ApprovedSourceScope:
    """Apply explicit human corrections and require every ambiguity to be resolved."""
    if not isinstance(overrides, Mapping):
        raise ValidationError()
    decisions = {decision.evidence_id: decision for decision in result.decisions}
    evidence_ids = tuple(record.evidence_id for record in evidence)
    if evidence_ids != tuple(decisions):
        raise ValidationError()
    if any(evidence_id not in decisions for evidence_id in overrides):
        raise ValidationError()
    if any(status not in _FINAL_STATUSES for status in overrides.values()):
        raise ValidationError()
    if any(
        evidence_id not in overrides
        for evidence_id in result.ambiguous_evidence_ids
    ):
        raise ValidationError()

    reviewed: list[ReviewedSourceDecision] = []
    approved: list[str] = []
    excluded: list[str] = []
    resolved: list[str] = []
    for decision in result.decisions:
        if decision.evidence_id in overrides:
            final_status = overrides[decision.evidence_id]
        elif decision.association_status == "ambiguous":
            raise ValidationError()
        else:
            final_status = decision.association_status
        user_overridden = (
            decision.association_status == "ambiguous"
            or final_status != decision.association_status
        )
        if decision.association_status == "ambiguous":
            resolved.append(decision.evidence_id)
        reviewed.append(
            ReviewedSourceDecision(
                evidence_id=decision.evidence_id,
                final_status=final_status,
                model_status=decision.association_status,
                basis=decision.basis,
                rationale=decision.rationale,
                span_ids=decision.span_ids,
                related_evidence_ids=decision.related_evidence_ids,
                user_overridden=user_overridden,
            )
        )
        (approved if final_status == "included" else excluded).append(
            decision.evidence_id
        )

    scope = ApprovedSourceScope(
        schema_version=SCHEMA_VERSION,
        scope_id="SCOPE-" + uuid.uuid4().hex,
        target_project=result.target_project,
        reviewed_decisions=tuple(reviewed),
        approved_evidence_ids=tuple(approved),
        excluded_evidence_ids=tuple(excluded),
        user_resolved_evidence_ids=tuple(resolved),
        evidence_fingerprints=_fingerprints(evidence),
        created_at=_utc_now(),
    )
    validate_approved_scope_evidence(scope, evidence)
    return scope


def validate_approved_scope_evidence(
    scope: ApprovedSourceScope,
    evidence: tuple[Any, ...],
) -> None:
    """Bind reviewed decisions and spans to the exact evidence snapshot."""
    evidence_ids = tuple(record.evidence_id for record in evidence)
    if tuple(item.evidence_id for item in scope.reviewed_decisions) != evidence_ids:
        raise ValidationError()
    if scope.evidence_fingerprints != _fingerprints(evidence):
        raise ValidationError()

    span_owner = {
        span.span_id: span.evidence_id for span in build_spans(evidence)
    }
    evidence_id_set = set(evidence_ids)
    for decision in scope.reviewed_decisions:
        if (
            not decision.span_ids
            or len(set(decision.span_ids)) != len(decision.span_ids)
            or any(
                span_owner.get(span_id) != decision.evidence_id
                for span_id in decision.span_ids
            )
        ):
            raise ValidationError()
        if (
            len(set(decision.related_evidence_ids))
            != len(decision.related_evidence_ids)
            or any(
                related not in evidence_id_set or related == decision.evidence_id
                for related in decision.related_evidence_ids
            )
        ):
            raise ValidationError()


def select_approved_evidence(
    scope: ApprovedSourceScope,
    evidence: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Return approved records only when the reviewed snapshot still matches."""
    validate_approved_scope_evidence(scope, evidence)
    approved = set(scope.approved_evidence_ids)
    return tuple(record for record in evidence if record.evidence_id in approved)
