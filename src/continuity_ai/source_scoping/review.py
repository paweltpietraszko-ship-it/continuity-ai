"""Human review gate between model scoping and downstream analysis."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.domain import (
    ApprovedSourceScope,
    ReviewedSourceDecision,
    SCHEMA_VERSION,
    SourceScopingResult,
)

_FINAL_STATUSES = frozenset({"included", "excluded"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _content_fingerprint(record: Any) -> str:
    return hashlib.sha256(record.content.encode("utf-8")).hexdigest()


def approve_source_scope(
    result: SourceScopingResult,
    evidence: tuple[Any, ...],
    overrides: Mapping[str, str],
) -> ApprovedSourceScope:
    """Apply explicit human corrections and require every ambiguous record to be resolved."""
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
            user_overridden = final_status != decision.association_status
            if decision.association_status == "ambiguous":
                resolved.append(decision.evidence_id)
                user_overridden = True
        else:
            if decision.association_status == "ambiguous":
                raise ValidationError()
            final_status = decision.association_status
            user_overridden = False
        reviewed.append(
            ReviewedSourceDecision(
                evidence_id=decision.evidence_id,
                final_status=final_status,
                model_status=decision.association_status,
                user_overridden=user_overridden,
            )
        )
        (approved if final_status == "included" else excluded).append(
            decision.evidence_id
        )

    return ApprovedSourceScope(
        schema_version=SCHEMA_VERSION,
        scope_id="SCOPE-" + uuid.uuid4().hex,
        target_project=result.target_project,
        reviewed_decisions=tuple(reviewed),
        approved_evidence_ids=tuple(approved),
        excluded_evidence_ids=tuple(excluded),
        user_resolved_evidence_ids=tuple(resolved),
        evidence_fingerprints=tuple(
            (record.evidence_id, _content_fingerprint(record)) for record in evidence
        ),
        created_at=_utc_now(),
    )


def select_approved_evidence(
    scope: ApprovedSourceScope,
    evidence: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Return approved records only when the reviewed snapshot still matches."""
    live_fingerprints = tuple(
        (record.evidence_id, _content_fingerprint(record)) for record in evidence
    )
    if live_fingerprints != scope.evidence_fingerprints:
        raise ValidationError()
    approved = set(scope.approved_evidence_ids)
    return tuple(record for record in evidence if record.evidence_id in approved)
