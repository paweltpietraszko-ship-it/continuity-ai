"""Stateful integration seam used by Bridge without coupling the core to Bridge."""
from __future__ import annotations

from typing import Any, Mapping

from continuity_ai.errors import ValidationError, VaultLockedError
from continuity_ai.evidence import build_spans, hydrate_citations
from continuity_ai.source_scoping.provider_selection import create_source_scoping_provider
from continuity_ai.source_scoping.restoration import (
    RESTORATION_INVALID,
    RESTORATION_VALID,
    restore_latest_approved_scope,
)
from continuity_ai.source_scoping.review import (
    approve_source_scope,
    select_approved_evidence,
)
from continuity_ai.source_scoping.service import run_source_scoping

STATUS_NONE = "none"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_APPROVED = "approved"
STATUS_INVALID = "invalid"


class SourceScopingSession:
    def __init__(self, provider=None) -> None:
        self.provider = provider
        self.result = None
        self.approved_scope = None
        self.status = STATUS_NONE
        self.persisted = False

    def reset(self) -> None:
        self.result = None
        self.approved_scope = None
        self.status = STATUS_NONE
        self.persisted = False

    def classify(
        self,
        target_project: str,
        evidence: tuple[Any, ...],
        *,
        precomputed_result: Any | None = None,
    ) -> dict[str, Any]:
        spans = build_spans(evidence)
        if precomputed_result is not None:
            candidate = precomputed_result
        else:
            provider = (
                self.provider
                if self.provider is not None
                else create_source_scoping_provider()
            )
            candidate = run_source_scoping(target_project, evidence, spans, provider)
        self.result = candidate
        self.approved_scope = None
        self.status = STATUS_PENDING_REVIEW
        self.persisted = False
        return {
            "source_scope": candidate,
            "citation_cards": hydrate_citations(
                self._ordered_scope_span_ids(candidate), evidence, spans
            ),
        }

    def approve(
        self,
        evidence: tuple[Any, ...],
        overrides: Mapping[str, str],
        vault=None,
        *,
        precomputed_scope: Any | None = None,
    ) -> dict[str, Any]:
        if self.result is None or self.status != STATUS_PENDING_REVIEW:
            raise ValidationError()
        scope = (
            precomputed_scope
            if precomputed_scope is not None
            else approve_source_scope(self.result, evidence, overrides)
        )
        persisted = False
        if vault is not None:
            try:
                vault.require()
            except VaultLockedError:
                pass
            else:
                vault.save_approved_source_scope(scope)
                persisted = True
        self.approved_scope = scope
        self.status = STATUS_APPROVED
        self.persisted = persisted
        return {"approved_source_scope": scope, "persisted": persisted}

    def active_evidence(self, evidence: tuple[Any, ...]) -> tuple[Any, ...]:
        if self.status in {STATUS_PENDING_REVIEW, STATUS_INVALID}:
            raise ValidationError()
        if self.approved_scope is None:
            return evidence
        return select_approved_evidence(self.approved_scope, evidence)

    def restore(
        self, target_project: str, evidence: tuple[Any, ...], vault
    ) -> None:
        self.reset()
        if vault is None:
            return
        try:
            vault.require()
        except VaultLockedError:
            return
        restoration = restore_latest_approved_scope(
            vault.payload.get("approved_source_scopes", []),
            target_project,
            evidence,
        )
        if restoration.status == RESTORATION_VALID:
            self.approved_scope = restoration.scope
            self.status = STATUS_APPROVED
            self.persisted = True
        elif restoration.status == RESTORATION_INVALID:
            self.status = STATUS_INVALID

    def state_payload(self) -> dict[str, Any]:
        return {
            "source_scoping_status": self.status,
            "source_scope": self.result,
            "approved_source_scope": self.approved_scope,
            "source_scope_persisted": self.persisted,
        }

    @staticmethod
    def _ordered_scope_span_ids(result) -> tuple[str, ...]:
        seen: set[str] = set()
        ordered: list[str] = []
        for decision in result.decisions:
            for span_id in decision.span_ids:
                if span_id not in seen:
                    seen.add(span_id)
                    ordered.append(span_id)
        return tuple(ordered)
