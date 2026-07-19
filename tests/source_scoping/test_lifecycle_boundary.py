import continuity_ai.bridge as bridge_module
from continuity_ai import conversation as conversation_module
from continuity_ai.bridge import Bridge
from continuity_ai.evidence import (
    attestation_to_reasoning,
    build_spans,
    order_evidence,
)
from continuity_ai.reasoning_pipeline import FakeDecisionProvenanceProvider
from continuity_ai.source_scoping.bridge_adapter import (
    STATUS_APPROVED,
    STATUS_INVALID,
    STATUS_PENDING_REVIEW,
)
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.vault import Vault
import pytest


PASSWORD = "correct horse battery staple"


class RecordingAnalysisProvider:
    provider_id = "recording-lifecycle-provider"

    def __init__(self):
        self.evidence_id_calls = []

    def analyze(self, evidence, spans, question):
        self.evidence_id_calls.append(
            tuple(record.evidence_id for record in evidence)
        )
        return FakeDecisionProvenanceProvider().analyze(
            evidence,
            spans,
            question,
        )


def _install_project(bridge, target, records, vault_record=None):
    artifacts = order_evidence(records)
    active = artifacts
    if vault_record is not None:
        active = order_evidence((*artifacts, vault_record))
    bridge.project = target
    bridge.artifact_records = artifacts
    bridge.records = active
    bridge.spans = build_spans(active)
    return artifacts


def _vault_with_attestation(tmp_path, filename):
    path = tmp_path / filename
    vault = Vault(path)
    vault.initialize("Owner", PASSWORD)
    proposal = vault.propose_attestation(
        "Owner confirms a vault-only project note."
    )
    attestation = vault.confirm_attestation(proposal.proposal_id)
    return vault, path, attestation_to_reasoning(attestation)


def _approved_bridge(tmp_path, workspace):
    target, records, _ = workspace
    vault, path, vault_record = _vault_with_attestation(
        tmp_path,
        "approved-lifecycle.vault",
    )
    provider = RecordingAnalysisProvider()
    bridge = Bridge(
        provider=provider,
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    bridge.vault = vault
    artifacts = _install_project(
        bridge,
        target,
        records,
        vault_record=vault_record,
    )
    bridge.source_scoping.classify(target, artifacts)
    result = bridge.source_scoping.result
    ambiguous_ids = result.ambiguous_evidence_ids
    bridge.source_scoping.approve(
        artifacts,
        {
            evidence_id: "excluded"
            for evidence_id in ambiguous_ids
        },
        vault=vault,
    )
    active_records, active_spans, scoped = (
        bridge._prepare_downstream_project_evidence()
    )
    assert scoped is True
    assert active_records == bridge.records
    assert active_spans == bridge.spans
    scope = bridge.source_scoping.approved_scope
    return {
        "bridge": bridge,
        "provider": provider,
        "vault": vault,
        "path": path,
        "target": target,
        "artifacts": artifacts,
        "vault_record": vault_record,
        "approved_ids": scope.approved_evidence_ids,
        "excluded_ids": scope.excluded_evidence_ids,
        "ambiguous_ids": ambiguous_ids,
    }


def _blocked_bridge(tmp_path, workspace, status):
    target, records, _ = workspace
    vault, _, vault_record = _vault_with_attestation(
        tmp_path,
        f"{status}.vault",
    )
    bridge = Bridge(
        provider=RecordingAnalysisProvider(),
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    bridge.vault = vault
    artifacts = _install_project(
        bridge,
        target,
        records,
        vault_record=vault_record,
    )
    if status == STATUS_PENDING_REVIEW:
        bridge.source_scoping.classify(target, artifacts)
    else:
        bridge.source_scoping.status = STATUS_INVALID
    return bridge


def _analysis_candidate(records, spans):
    return FakeDecisionProvenanceProvider().analyze(
        records,
        spans,
        "Candidate",
    )


def test_approved_scope_survives_lock_without_widening_and_analysis_uses_survivors(
    tmp_path,
    workspace,
):
    state = _approved_bridge(tmp_path, workspace)
    bridge = state["bridge"]
    bridge.analysis = object()
    bridge.snapshot = object()
    bridge.last_question = "Previous question"

    before_lock_ids = {
        record.evidence_id
        for record in bridge.records
    }
    assert state["vault_record"].evidence_id in before_lock_ids

    response = bridge.handle({"command": "lock_vault"})

    assert response["ok"] is True
    assert bridge.source_scoping.status == STATUS_APPROVED
    active_ids = tuple(record.evidence_id for record in bridge.records)
    assert active_ids == state["approved_ids"]
    assert state["vault_record"].evidence_id not in active_ids
    assert set(state["excluded_ids"]).isdisjoint(active_ids)
    assert set(state["ambiguous_ids"]).isdisjoint(active_ids)
    assert bridge.analysis is None
    assert bridge.snapshot is None
    assert bridge.last_question is None

    analyzed = bridge.handle(
        {
            "command": "analyze_project",
            "question": "What is the current project state?",
        }
    )
    assert analyzed["ok"] is True
    assert state["provider"].evidence_id_calls[-1] == state["approved_ids"]


@pytest.mark.parametrize(
    "status",
    [STATUS_PENDING_REVIEW, STATUS_INVALID],
)
def test_pending_and_invalid_survive_lock_and_block_all_project_consumers(
    tmp_path,
    workspace,
    status,
):
    bridge = _blocked_bridge(tmp_path, workspace, status)

    locked = bridge.handle({"command": "lock_vault"})

    assert locked["ok"] is True
    assert bridge.source_scoping.status == status
    assert bridge.records == ()
    assert bridge.spans == ()

    analyzed = bridge.handle(
        {
            "command": "analyze_project",
            "question": "Project state?",
        }
    )
    grounded = bridge.handle(
        {
            "command": "send_message",
            "message": "Tell me about the project.",
        }
    )
    revision = bridge.handle(
        {
            "command": "send_message",
            "message": "Revise the analysis.",
            "revision_candidate": {},
        }
    )

    for response in (analyzed, grounded, revision):
        assert response["ok"] is False
        assert response["error"]["code"] == "validation_error"


def test_unlock_and_reload_restore_persisted_scope_without_stale_records(
    tmp_path,
    workspace,
    monkeypatch,
):
    state = _approved_bridge(tmp_path, workspace)
    bridge = state["bridge"]
    bridge.handle({"command": "lock_vault"})

    monkeypatch.setattr(
        bridge_module,
        "ingest_artifacts",
        lambda root: state["artifacts"],
    )
    monkeypatch.setattr(
        bridge_module,
        "read_project_name",
        lambda root: state["target"],
    )
    monkeypatch.setattr(
        bridge_module,
        "artifact_to_reasoning",
        lambda record: record,
    )

    unlocked = bridge.handle(
        {
            "command": "unlock_vault",
            "path": str(state["path"]),
            "password": PASSWORD,
        }
    )
    assert unlocked["ok"] is True

    loaded = bridge.handle(
        {
            "command": "load_project",
            "artifact_root": "unused",
        }
    )
    assert loaded["ok"] is True
    assert bridge.source_scoping.status == STATUS_APPROVED

    expected_ids = set(state["approved_ids"]) | {
        state["vault_record"].evidence_id
    }
    live_ids = {
        record.evidence_id
        for record in bridge.records
    }
    assert live_ids == expected_ids
    assert set(state["excluded_ids"]).isdisjoint(live_ids)
    assert set(state["ambiguous_ids"]).isdisjoint(live_ids)


def test_approved_conversation_and_revision_use_only_bounded_evidence(
    tmp_path,
    workspace,
):
    state = _approved_bridge(tmp_path, workspace)
    bridge = state["bridge"]
    expected_ids = {
        record.evidence_id
        for record in bridge.records
    }

    grounded = bridge.handle(
        {
            "command": "send_message",
            "message": "Hello.",
        }
    )
    assert grounded["ok"] is True
    assert grounded["data"]["kind"] == "project_grounded"
    citation_ids = {
        card["evidence_id"]
        for card in grounded["data"]["citation_cards"]
    }
    assert citation_ids <= expected_ids
    assert set(state["excluded_ids"]).isdisjoint(citation_ids)
    assert set(state["ambiguous_ids"]).isdisjoint(citation_ids)

    valid_candidate = _analysis_candidate(
        bridge.records,
        bridge.spans,
    )
    proposed = bridge.handle(
        {
            "command": "send_message",
            "message": "Revise the analysis.",
            "revision_candidate": valid_candidate,
        }
    )
    assert proposed["ok"] is True
    assert proposed["data"]["kind"] == "analysis_revision_proposal"
    proposal_id = proposed["data"]["analysis_revision_proposal"][
        "proposal_id"
    ]
    stored_candidate = state["vault"].pending_revisions[
        proposal_id
    ].candidate
    assert {
        annotation.evidence_id
        for annotation in stored_candidate.semantic_annotations
    } == expected_ids

    all_records = order_evidence(
        (*state["artifacts"], state["vault_record"])
    )
    excluded_candidate = _analysis_candidate(
        all_records,
        build_spans(all_records),
    )
    pending_before = set(state["vault"].pending_revisions)
    rejected = bridge.handle(
        {
            "command": "send_message",
            "message": "Revise the analysis.",
            "revision_candidate": excluded_candidate,
        }
    )
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "validation_error"
    assert set(state["vault"].pending_revisions) == pending_before


def test_analysis_conversation_and_revision_share_identical_evidence_ids(
    tmp_path,
    workspace,
    monkeypatch,
):
    state = _approved_bridge(tmp_path, workspace)
    bridge = state["bridge"]
    expected_ids = tuple(
        record.evidence_id
        for record in bridge.records
    )
    conversation_calls = []
    original_send_message = conversation_module.send_message

    def capture_send_message(message, records, spans, **kwargs):
        conversation_calls.append(
            tuple(record.evidence_id for record in records)
        )
        return original_send_message(
            message,
            records,
            spans,
            **kwargs,
        )

    monkeypatch.setattr(
        conversation_module,
        "send_message",
        capture_send_message,
    )

    analyzed = bridge.handle(
        {
            "command": "analyze_project",
            "question": "Current project state?",
        }
    )
    assert analyzed["ok"] is True

    grounded = bridge.handle(
        {
            "command": "send_message",
            "message": "Project status?",
        }
    )
    assert grounded["ok"] is True

    candidate = _analysis_candidate(
        bridge.records,
        bridge.spans,
    )
    revision = bridge.handle(
        {
            "command": "send_message",
            "message": "Revise the analysis.",
            "revision_candidate": candidate,
        }
    )
    assert revision["ok"] is True

    assert state["provider"].evidence_id_calls[-1] == expected_ids
    assert conversation_calls == [expected_ids, expected_ids]


def test_status_none_preserves_direct_injection_for_conversation(workspace):
    target, records, _ = workspace
    artifacts = order_evidence(records)
    injected = artifacts[:2]
    bridge = Bridge(
        provider=RecordingAnalysisProvider(),
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    bridge.project = target
    bridge.artifact_records = artifacts
    bridge.records = injected
    bridge.spans = build_spans(injected)

    response = bridge.handle(
        {
            "command": "send_message",
            "message": "Project status?",
        }
    )

    assert response["ok"] is True
    assert response["data"]["kind"] == "project_grounded"
    assert bridge.records is injected
    assert {
        card["evidence_id"]
        for card in response["data"]["citation_cards"]
    } <= {
        record.evidence_id
        for record in injected
    }
