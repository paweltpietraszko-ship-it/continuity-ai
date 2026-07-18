from dataclasses import replace

import pytest

from continuity_ai.errors import ProviderError, ValidationError
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.review import (
    approve_source_scope,
    select_approved_evidence,
)
from continuity_ai.source_scoping.service import run_source_scoping


class ExplodingProvider:
    provider_id = "exploding"

    def classify(self, target_project, evidence, spans):
        raise RuntimeError("provider unavailable")


def _result(workspace):
    target, records, spans = workspace
    return records, run_source_scoping(
        target, records, spans, FakeSourceScopingProvider()
    )


def _approve_all_ambiguous_as_excluded(workspace):
    records, result = _result(workspace)
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    return records, result, approve_source_scope(result, records, overrides)


def test_provider_failure_is_fail_closed(workspace):
    target, records, spans = workspace
    with pytest.raises(ProviderError):
        run_source_scoping(target, records, spans, ExplodingProvider())


def test_review_requires_resolution_for_every_ambiguous_record(workspace):
    records, result = _result(workspace)
    with pytest.raises(ValidationError):
        approve_source_scope(result, records, {})


def test_review_can_correct_any_model_decision(workspace):
    records, result = _result(workspace)
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    overrides["EV-MIX-003"] = "excluded"
    scope = approve_source_scope(result, records, overrides)
    assert "EV-MIX-003" not in scope.approved_evidence_ids
    assert "EV-MIX-003" in scope.excluded_evidence_ids
    assert set(scope.user_resolved_evidence_ids) == set(
        result.ambiguous_evidence_ids
    )


def test_review_preserves_model_grounding_for_later_display(workspace):
    _, result, scope = _approve_all_ambiguous_as_excluded(workspace)
    reviewed = scope.reviewed_decisions[0]
    original = result.decisions[0]
    assert reviewed.model_basis == original.basis
    assert reviewed.model_rationale == original.rationale
    assert reviewed.span_ids == original.span_ids
    assert reviewed.related_evidence_ids == original.related_evidence_ids


def test_approved_handoff_preserves_input_order(workspace):
    records, _, scope = _approve_all_ambiguous_as_excluded(workspace)
    selected = select_approved_evidence(scope, records)
    assert tuple(record.evidence_id for record in selected) == scope.approved_evidence_ids


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("content", "changed content"),
        ("title", "Changed title"),
        ("author_or_actor", "Different actor"),
        ("timestamp", "2026-12-31T23:59:59Z"),
        ("source_type", "different_type"),
        ("uri", "synthetic://changed"),
        ("artifact_sha256", "f" * 64),
    ],
)
def test_any_neutral_record_change_invalidates_approved_scope(
    workspace, field, replacement
):
    records, _, scope = _approve_all_ambiguous_as_excluded(workspace)
    changed_record = replace(records[0], **{field: replacement})
    changed = (changed_record, *records[1:])
    with pytest.raises(ValidationError):
        select_approved_evidence(scope, tuple(changed))


def test_reordered_source_set_invalidates_approved_scope(workspace):
    records, _, scope = _approve_all_ambiguous_as_excluded(workspace)
    reordered = (records[1], records[0], *records[2:])
    with pytest.raises(ValidationError):
        select_approved_evidence(scope, tuple(reordered))
