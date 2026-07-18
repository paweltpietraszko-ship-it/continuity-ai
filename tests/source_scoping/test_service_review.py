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


def test_approved_handoff_preserves_input_order(workspace):
    records, result = _result(workspace)
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    scope = approve_source_scope(result, records, overrides)
    selected = select_approved_evidence(scope, records)
    assert tuple(record.evidence_id for record in selected) == scope.approved_evidence_ids


def test_changed_source_invalidates_approved_scope(workspace):
    records, result = _result(workspace)
    overrides = {
        evidence_id: "excluded" for evidence_id in result.ambiguous_evidence_ids
    }
    scope = approve_source_scope(result, records, overrides)
    changed = (
        replace(records[0], content=records[0].content + " changed"),
        *records[1:],
    )
    with pytest.raises(ValidationError):
        select_approved_evidence(scope, tuple(changed))
