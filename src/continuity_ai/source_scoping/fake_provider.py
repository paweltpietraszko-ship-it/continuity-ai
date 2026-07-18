"""Deterministic generic provider used for tests and offline demonstrations.

This is deliberately not the production semantic provider. It contains no fixture
names or expected IDs and operates on arbitrary target names and evidence records.
"""
from __future__ import annotations

from typing import Any

from continuity_ai.source_scoping.reference_signals import (
    PROJECT_MENTION,
    fold,
    signals,
    spans_by_evidence,
)


class FakeSourceScopingProvider:
    """Generic graph-building test double; never selected implicitly in production."""

    provider_id = "fake-source-scoping-generic-v1"
    minimum_shared_signals = 2

    def classify(
        self,
        target_project: str,
        evidence: tuple[Any, ...],
        spans: tuple[Any, ...],
    ) -> dict[str, Any]:
        grouped_spans = spans_by_evidence(spans)
        target_folded = fold(target_project)
        records: dict[str, dict[str, Any]] = {}
        for item in evidence:
            evidence_spans = grouped_spans[item.evidence_id]
            combined = "\n".join(
                [
                    item.title,
                    item.author_or_actor,
                    *(span.text for span in evidence_spans),
                ]
            )
            project_mentions = {
                f"project {name}".casefold()
                for name in PROJECT_MENTION.findall(combined)
            }
            has_target = target_folded in project_mentions
            other_mentions = sorted(
                mention for mention in project_mentions if mention != target_folded
            )
            records[item.evidence_id] = {
                "item": item,
                "spans": evidence_spans,
                "signals": signals(combined, target_project),
                "has_target": has_target,
                "other_mentions": other_mentions,
            }

        decisions: dict[str, dict[str, Any]] = {}
        included_nodes: list[str] = []
        excluded_nodes: list[str] = []
        unresolved: list[str] = []

        for item in evidence:
            record = records[item.evidence_id]
            span_ids = [span.span_id for span in record["spans"][:2]]
            if record["has_target"] and record["other_mentions"]:
                decisions[item.evidence_id] = self._decision(
                    item.evidence_id,
                    "ambiguous",
                    "conflicting_context",
                    "The record explicitly references the target and at least one other project.",
                    span_ids,
                )
            elif record["has_target"]:
                decisions[item.evidence_id] = self._decision(
                    item.evidence_id,
                    "included",
                    "explicit_target",
                    "The record explicitly names the authoritative target project.",
                    span_ids,
                )
                included_nodes.append(item.evidence_id)
            elif record["other_mentions"]:
                decisions[item.evidence_id] = self._decision(
                    item.evidence_id,
                    "excluded",
                    "explicit_other_project",
                    "The record explicitly names a project other than the authoritative target.",
                    span_ids,
                )
                excluded_nodes.append(item.evidence_id)
            else:
                unresolved.append(item.evidence_id)

        changed = True
        while changed and unresolved:
            changed = False
            remaining: list[str] = []
            for evidence_id in unresolved:
                inc = self._best_relation(evidence_id, included_nodes, records)
                exc = self._best_relation(evidence_id, excluded_nodes, records)
                inc_score = inc[0] if inc else 0
                exc_score = exc[0] if exc else 0
                span_ids = [
                    span.span_id for span in records[evidence_id]["spans"][:2]
                ]
                if (
                    inc_score >= self.minimum_shared_signals
                    and exc_score >= self.minimum_shared_signals
                    and abs(inc_score - exc_score) <= 1
                ):
                    related = [inc[1], exc[1]] if inc and exc else []
                    decisions[evidence_id] = self._decision(
                        evidence_id,
                        "ambiguous",
                        "conflicting_context",
                        "The record has similarly strong contextual links to target and other-project evidence.",
                        span_ids,
                        related,
                    )
                    changed = True
                elif (
                    inc_score >= self.minimum_shared_signals
                    and inc_score > exc_score
                ):
                    decisions[evidence_id] = self._decision(
                        evidence_id,
                        "included",
                        "corroborated_context",
                        "Multiple distinctive signals connect the record to target-project evidence.",
                        span_ids,
                        [inc[1]],
                    )
                    included_nodes.append(evidence_id)
                    changed = True
                elif (
                    exc_score >= self.minimum_shared_signals
                    and exc_score > inc_score
                ):
                    decisions[evidence_id] = self._decision(
                        evidence_id,
                        "excluded",
                        "corroborated_other_project",
                        "Multiple distinctive signals connect the record to other-project evidence.",
                        span_ids,
                        [exc[1]],
                    )
                    excluded_nodes.append(evidence_id)
                    changed = True
                else:
                    remaining.append(evidence_id)
            unresolved = remaining

        for evidence_id in unresolved:
            span_ids = [span.span_id for span in records[evidence_id]["spans"][:2]]
            decisions[evidence_id] = self._decision(
                evidence_id,
                "ambiguous",
                "insufficient_context",
                "The supplied evidence does not establish a reliable project association.",
                span_ids,
            )

        ordered = [decisions[item.evidence_id] for item in evidence]
        return {
            "schema_version": "1.0",
            "target_project": target_project,
            "anchor_evidence_ids": [
                decision["evidence_id"]
                for decision in ordered
                if decision["basis"] == "explicit_target"
            ],
            "decisions": ordered,
            "selected_evidence_ids": [
                decision["evidence_id"]
                for decision in ordered
                if decision["association_status"] == "included"
            ],
            "ambiguous_evidence_ids": [
                decision["evidence_id"]
                for decision in ordered
                if decision["association_status"] == "ambiguous"
            ],
            "excluded_evidence_ids": [
                decision["evidence_id"]
                for decision in ordered
                if decision["association_status"] == "excluded"
            ],
        }

    @staticmethod
    def _decision(
        evidence_id: str,
        status: str,
        basis: str,
        rationale: str,
        span_ids: list[str],
        related: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "evidence_id": evidence_id,
            "association_status": status,
            "basis": basis,
            "rationale": rationale,
            "span_ids": span_ids,
            "related_evidence_ids": related or [],
        }

    @staticmethod
    def _best_relation(
        evidence_id: str,
        candidates: list[str],
        records: dict[str, dict[str, Any]],
    ) -> tuple[int, str] | None:
        if not candidates:
            return None
        own = records[evidence_id]["signals"]
        scored = [
            (len(own & records[candidate]["signals"]), candidate)
            for candidate in candidates
        ]
        return max(scored, key=lambda item: (item[0], item[1]))
