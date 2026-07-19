import pytest

from continuity_ai.errors import ValidationError
from continuity_ai.source_scoping.validator import validate_source_scoping_payload


def _rejects(payload, workspace):
    target, records, spans = workspace
    with pytest.raises(ValidationError):
        validate_source_scoping_payload(payload, target, records, spans)


def test_valid_mixed_workspace_is_accepted(workspace, valid_payload):
    target, records, spans = workspace
    result = validate_source_scoping_payload(valid_payload, target, records, spans)
    assert len(result.decisions) == 18
    assert result.anchor_evidence_ids == ("EV-MIX-001", "EV-MIX-016")
    assert "EV-MIX-013" in result.ambiguous_evidence_ids
    assert "EV-MIX-011" in result.selected_evidence_ids


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "target_project",
        "anchor_evidence_ids",
        "decisions",
        "selected_evidence_ids",
        "ambiguous_evidence_ids",
        "excluded_evidence_ids",
    ],
)
def test_missing_result_field_fails_closed(workspace, mutate, field):
    payload = mutate()
    del payload[field]
    _rejects(payload, workspace)


def test_extra_result_field_fails_closed(workspace, mutate):
    payload = mutate()
    payload["unexpected"] = True
    _rejects(payload, workspace)


def test_provider_cannot_change_target_project(workspace, mutate):
    payload = mutate()
    payload["target_project"] = "Project Meridian"
    _rejects(payload, workspace)


def test_decision_order_must_match_input(workspace, mutate):
    payload = mutate()
    payload["decisions"][0], payload["decisions"][1] = (
        payload["decisions"][1],
        payload["decisions"][0],
    )
    _rejects(payload, workspace)


def test_each_evidence_must_appear_exactly_once(workspace, mutate):
    payload = mutate()
    payload["decisions"][1] = payload["decisions"][0]
    _rejects(payload, workspace)


@pytest.mark.parametrize("span_id", ["EV-MIX-002:L001", "EV-MIX-001:L999"])
def test_foreign_or_invented_span_fails_closed(workspace, mutate, span_id):
    payload = mutate()
    payload["decisions"][0]["span_ids"] = [span_id]
    _rejects(payload, workspace)


def test_duplicate_span_fails_closed(workspace, mutate):
    payload = mutate()
    span_id = payload["decisions"][0]["span_ids"][0]
    payload["decisions"][0]["span_ids"] = [span_id, span_id]
    _rejects(payload, workspace)


def test_ambiguous_cannot_be_selected(workspace, mutate):
    payload = mutate()
    payload["selected_evidence_ids"].append(payload["ambiguous_evidence_ids"][0])
    _rejects(payload, workspace)


def test_status_basis_matrix_is_strict(workspace, mutate):
    payload = mutate()
    payload["decisions"][0]["association_status"] = "excluded"
    _rejects(payload, workspace)


def test_contextual_decision_requires_related_evidence(workspace, mutate):
    payload = mutate()
    decision = next(
        item
        for item in payload["decisions"]
        if item["basis"] == "corroborated_context"
    )
    decision["related_evidence_ids"] = []
    _rejects(payload, workspace)


def test_contextual_cycle_without_explicit_anchor_fails(workspace, mutate):
    payload = mutate()
    first = next(
        item for item in payload["decisions"] if item["evidence_id"] == "EV-MIX-002"
    )
    second = next(
        item for item in payload["decisions"] if item["evidence_id"] == "EV-MIX-003"
    )
    first["related_evidence_ids"] = [second["evidence_id"]]
    second["related_evidence_ids"] = [first["evidence_id"]]
    _rejects(payload, workspace)


def test_anchor_list_is_derived_not_model_discretion(workspace, mutate):
    payload = mutate()
    payload["anchor_evidence_ids"] = ["EV-MIX-002"]
    _rejects(payload, workspace)
