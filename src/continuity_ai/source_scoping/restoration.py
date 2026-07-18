"""Restoration rules for encrypted approved-scope history."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from continuity_ai.source_scoping.domain import ApprovedSourceScope
from continuity_ai.source_scoping.review import select_approved_evidence
from continuity_ai.source_scoping.serialization import approved_scope_from_payload

RESTORATION_NONE = "none"
RESTORATION_VALID = "valid"
RESTORATION_INVALID = "invalid"


@dataclass(frozen=True)
class ApprovedScopeRestoration:
    status: str
    scope: ApprovedSourceScope | None = None


def restore_latest_approved_scope(
    payloads: Any,
    target_project: str,
    evidence: tuple[Any, ...],
) -> ApprovedScopeRestoration:
    if not isinstance(payloads, list):
        return ApprovedScopeRestoration(RESTORATION_INVALID)
    matching = [
        item
        for item in payloads
        if isinstance(item, dict) and item.get("target_project") == target_project
    ]
    if not matching:
        return ApprovedScopeRestoration(RESTORATION_NONE)
    try:
        scope = approved_scope_from_payload(matching[-1])
        select_approved_evidence(scope, evidence)
    except Exception:
        return ApprovedScopeRestoration(RESTORATION_INVALID)
    return ApprovedScopeRestoration(RESTORATION_VALID, scope)
