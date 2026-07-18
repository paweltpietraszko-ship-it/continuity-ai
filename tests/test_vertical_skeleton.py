from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
import pytest
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.evidence import artifact_to_reasoning, order_evidence, build_spans, make_snapshot, hydrate_snapshot_citations, compare_live_to_snapshot, content_sha256
from continuity_ai.reasoning_pipeline import FakeAuroraProvider, run_analysis, validate_analysis
from continuity_ai.vault import Vault
from continuity_ai.errors import VaultAuthError, VaultLockedError, ValidationError, VaultAlreadyExistsError
from continuity_ai.domain import AuthenticatedUserAttestation, SavedAnalysis
from continuity_ai.prompts import prompt_snapshots, assert_prompts_clean
from continuity_ai.bridge import Bridge, encode_response, decode_command
from continuity_ai.openai_provider import OpenAIReasoningProvider
from continuity_ai.conversation import send_message, confirm_analysis_revision

def aurora(tmp_path: Path):
    generate_project_aurora_fixture(tmp_path)
    return order_evidence(tuple(artifact_to_reasoning(r) for r in ingest_artifacts(tmp_path/"fixtures/project_aurora/generated/artifacts")))

def test_spans_snapshot_and_changed_source(tmp_path: Path):
    records=aurora(tmp_path); spans=build_spans(records)
    assert spans and spans[0].span_id.endswith("L001")
    result, spans, snap=run_analysis(records,"q",FakeAuroraProvider())
    saved=SavedAnalysis(snap.analysis_id, snap.created_at, result, snap)
    cards=hydrate_snapshot_citations(saved, result.current_state.span_ids)
    assert cards[0].exact_text
    mutated=list(records); r=mutated[0]; mutated[0]=type(r)(r.evidence_id,r.source_type,r.author_or_actor,r.timestamp,r.title,r.content+" changed",r.provenance,r.uri,r.artifact_sha256)
    assert compare_live_to_snapshot(saved, tuple(mutated)) == "source_changed_since_analysis"

def test_validator_rejects_bad_ids_and_status_rules(tmp_path: Path):
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    bad=dict(candidate); bad["current_state"]={"statement":"x","span_ids":["missing:L001"]}
    with pytest.raises(ValidationError): validate_analysis(bad,records,spans)
    bad=dict(candidate); bad["semantic_annotations"]=[dict(a, propagation_role="none") for a in candidate["semantic_annotations"]]
    with pytest.raises(ValidationError): validate_analysis(bad,records,spans)

def test_vault_encryption_lock_and_attestation(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); s=v.initialize("Paweł","secret")
    p=v.propose_attestation(" Zażółć gęślą jaźń ")
    a=v.confirm_attestation(p.proposal_id)
    assert a.statement.startswith(" Zażółć")
    raw=path.read_bytes(); assert b"secret" not in raw and "Zażółć".encode() not in raw
    nonce1=json.loads(raw.decode())["nonce"]
    p2=v.propose_attestation("second"); v.confirm_attestation(p2.proposal_id); nonce2=json.loads(path.read_text())["nonce"]
    assert nonce1 != nonce2
    v.lock(); assert set(s.key_buffer) == {0}
    with pytest.raises(VaultLockedError): v.confirm_attestation("nope")
    with pytest.raises(VaultAuthError): Vault(path).unlock("wrong")

def test_initialize_rejects_existing_vault_and_preserves_bytes(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret")
    original=path.read_bytes(); blocked=Vault(path)
    with pytest.raises(VaultAlreadyExistsError):
        blocked.initialize("Someone Else","different")
    assert path.read_bytes() == original
    assert blocked.payload is None and blocked.session is None
    assert list(tmp_path.iterdir()) == [path]

def test_initialize_rejects_empty_owner_name(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path)
    with pytest.raises(ValidationError): v.initialize("", "secret")
    assert not path.exists()
    assert v.payload is None and v.session is None
    assert list(tmp_path.iterdir()) == []

def test_initialize_rejects_whitespace_only_owner_name(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path)
    with pytest.raises(ValidationError): v.initialize("   ", "secret")
    assert not path.exists()
    assert v.payload is None and v.session is None
    assert list(tmp_path.iterdir()) == []

def test_initialize_rejects_empty_password(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path)
    with pytest.raises(ValidationError): v.initialize("Paweł", "")
    assert not path.exists()
    assert v.payload is None and v.session is None
    assert list(tmp_path.iterdir()) == []

def test_initialize_rejects_whitespace_only_password(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path)
    with pytest.raises(ValidationError): v.initialize("Paweł", "   ")
    assert not path.exists()
    assert v.payload is None and v.session is None
    assert list(tmp_path.iterdir()) == []

def test_attestation_proposal_stores_creating_session_id(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); s=v.initialize("Paweł","secret")
    p=v.propose_attestation("note")
    assert p.session_id == s.session_id
    datetime.fromisoformat(p.created_at)

def test_revision_proposal_stores_creating_session_id(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); s=v.initialize("Paweł","secret")
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    resp=send_message("update analysis", records, spans, vault=v, revision_candidate=candidate)
    assert resp.analysis_revision_proposal.session_id == s.session_id
    assert resp.analysis_revision_proposal.proposal_id in v.pending_revisions
    datetime.fromisoformat(resp.analysis_revision_proposal.created_at)

def test_lock_invalidates_attestation_proposals(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret")
    v.propose_attestation("note")
    v.lock()
    assert v.pending_attestations == {}

def test_lock_invalidates_revision_proposals(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret")
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    send_message("update analysis", records, spans, vault=v, revision_candidate=candidate)
    v.lock()
    assert v.pending_revisions == {}

def test_successful_unlock_invalidates_both_proposal_types(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); old=v.initialize("Paweł","secret")
    v.propose_attestation("note")
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    send_message("update analysis", records, spans, vault=v, revision_candidate=candidate)
    assert v.pending_attestations and v.pending_revisions
    v.unlock("secret")
    assert v.pending_attestations == {} and v.pending_revisions == {}
    assert v.session.session_id != old.session_id
    assert old.unlocked is False
    assert set(old.key_buffer) == {0}

def test_attestation_from_session_a_cannot_be_confirmed_in_session_b(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret")
    p=v.propose_attestation("note")
    v.unlock("secret")
    v.pending_attestations[p.proposal_id]=p
    with pytest.raises(ValidationError):
        v.confirm_attestation(p.proposal_id)

def test_attestation_proposal_cannot_be_confirmed_twice(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret")
    p=v.propose_attestation("note")
    v.confirm_attestation(p.proposal_id)
    with pytest.raises(ValidationError):
        v.confirm_attestation(p.proposal_id)

def test_revision_proposal_cannot_be_confirmed_twice(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret")
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    resp=send_message("update analysis", records, spans, vault=v, revision_candidate=candidate)
    proposal_id=resp.analysis_revision_proposal.proposal_id
    confirm_analysis_revision(v, proposal_id)
    with pytest.raises(ValidationError):
        confirm_analysis_revision(v, proposal_id)

def test_revision_proposal_requires_unlocked_vault(tmp_path: Path):
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    with pytest.raises(VaultLockedError):
        send_message("update analysis", records, spans, vault=None, revision_candidate=candidate)
    path=tmp_path/"vault.bin"; v=Vault(path); v.initialize("Paweł","secret"); v.lock()
    with pytest.raises(VaultLockedError):
        send_message("update analysis", records, spans, vault=v, revision_candidate=candidate)

def test_failed_unlock_does_not_create_replacement_session(tmp_path: Path):
    path=tmp_path/"vault.bin"; v=Vault(path); s=v.initialize("Paweł","secret")
    p=v.propose_attestation("note")
    original_key_bytes=bytes(s.key_buffer)
    with pytest.raises(VaultAuthError):
        v.unlock("wrong")
    assert v.session is s
    assert s.unlocked is True
    assert bytes(s.key_buffer) == original_key_bytes
    assert any(b != 0 for b in s.key_buffer)
    assert p.proposal_id in v.pending_attestations

def test_vault_write_succeeds_without_o_directory(tmp_path: Path, monkeypatch):
    import os
    monkeypatch.delattr(os, "O_DIRECTORY", raising=False)
    path=tmp_path/"vault.bin"; v=Vault(path); s=v.initialize("Paweł","secret")
    assert path.read_bytes()
    p=v.propose_attestation("still works"); a=v.confirm_attestation(p.proposal_id)
    assert a.statement == "still works"
    assert path.read_bytes()

def test_attestation_validation_and_hash():
    with pytest.raises(ValueError): AuthenticatedUserAttestation("e","a","n","2026-01-01T00:00:00Z","text","   ")
    with pytest.raises(ValueError): AuthenticatedUserAttestation("e","a","n","2026-01-01T00:00:00Z","text","x"*4001)
    a=AuthenticatedUserAttestation("EV-UA-1","a","n","2026-01-01T00:00:00Z","text","owner statement")
    from continuity_ai.evidence import attestation_to_reasoning
    assert len(content_sha256(attestation_to_reasoning(a).content)) == 64

def test_prompts_are_versioned_and_clean():
    snaps=prompt_snapshots(); assert {"g03_reasoning_v2","g03_conversation_v1","g03_analysis_revision_v1","g03_attestation_proposal_v1"} <= set(snaps)
    assert_prompts_clean()

def test_bridge_utf8_roundtrip(tmp_path: Path):
    cmd={"command":"initialize_vault","path":str(tmp_path/"v"),"password":"sekret","owner_name":"Paweł"}
    assert decode_command(json.dumps(cmd, ensure_ascii=False).encode("utf-8")) == cmd
    out=encode_response(Bridge().handle(cmd)).decode("utf-8")
    assert "ok" in out

CITATION_CARD_FIELDS = {
    "evidence_id", "span_id", "exact_text", "title", "author_or_actor", "timestamp", "source_type", "provenance", "source_status",
}

def _init_and_load(tmp_path: Path, provider=None):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = str(tmp_path / "fixtures/project_aurora/generated/artifacts")
    vault_path = str(tmp_path / "vault.bin")
    bridge = Bridge(provider=provider)
    bridge.handle({"command": "initialize_vault", "path": vault_path, "password": "secret", "owner_name": "Paweł"})
    bridge.handle({"command": "load_project", "artifact_root": artifact_root})
    return bridge, vault_path, artifact_root

def test_bridge_complete_offline_aurora_flow_with_attestation_confirmation(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)

    analyze_resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    assert analyze_resp["ok"] is True
    data = analyze_resp["data"]
    assert data["analysis_status"] == "break_found"
    cards = data["citation_cards"]
    assert cards
    span_texts = {s.span_id: s.text for s in bridge.spans}
    for card in cards:
        assert set(card.keys()) == CITATION_CARD_FIELDS
        assert card["exact_text"] == span_texts[card["span_id"]]

    before_bytes = Path(vault_path).read_bytes()
    before_state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert before_state["evidence_count"] == 5

    propose_resp = bridge.handle({"command": "send_message", "message": "I attest the location change is now confirmed operationally"})
    assert propose_resp["ok"] is True
    assert propose_resp["data"]["kind"] == "attestation_proposal"
    proposal_id = propose_resp["data"]["attestation_proposal"]["proposal_id"]

    assert Path(vault_path).read_bytes() == before_bytes
    unchanged_state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert unchanged_state["evidence_count"] == 5

    confirm_resp = bridge.handle({"command": "confirm_attestation", "proposal_id": proposal_id})
    assert confirm_resp["ok"] is True
    confirm_data = confirm_resp["data"]
    assert confirm_data["evidence_count"] == 6
    assert set(confirm_data["citation_cards"][0].keys()) == CITATION_CARD_FIELDS
    annotated_ids = {a["evidence_id"] for a in confirm_data["semantic_annotations"]}
    assert confirm_data["evidence_id"] in annotated_ids

    after_bytes = Path(vault_path).read_bytes()
    assert after_bytes != before_bytes
    assert b"I attest the location change is now confirmed operationally" not in after_bytes

    workspace_resp = bridge.handle({"command": "get_workspace_state"})
    assert workspace_resp["data"]["evidence_count"] == 6
    assert workspace_resp["data"]["has_analysis"] is True

def test_new_bridge_recovers_confirmed_attestation_into_combined_evidence(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    propose_resp = bridge.handle({"command": "send_message", "message": "I attest this is resolved"})
    proposal_id = propose_resp["data"]["attestation_proposal"]["proposal_id"]
    bridge.handle({"command": "confirm_attestation", "proposal_id": proposal_id})

    recovered = Bridge()
    unlock_resp = recovered.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True
    load_resp = recovered.handle({"command": "load_project", "artifact_root": artifact_root})
    assert load_resp["data"]["evidence_count"] == 6
    analyze_resp = recovered.handle({"command": "analyze_project", "question": "q2"})
    assert analyze_resp["ok"] is True

def test_locking_through_bridge_clears_attestations_and_analysis(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    propose_resp = bridge.handle({"command": "send_message", "message": "I attest this needs review"})
    proposal_id = propose_resp["data"]["attestation_proposal"]["proposal_id"]
    bridge.handle({"command": "confirm_attestation", "proposal_id": proposal_id})
    assert len(bridge.records) == 6

    bridge.handle({"command": "send_message", "message": "I attest another note"})
    assert bridge.vault.pending_attestations

    lock_resp = bridge.handle({"command": "lock_vault"})
    assert lock_resp["ok"] is True
    assert bridge.vault.pending_attestations == {}
    assert len(bridge.records) == 5
    assert bridge.analysis is None
    assert bridge.snapshot is None

def test_analysis_revision_flow_through_bridge(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "q"})
    assert analyze_resp["ok"] is True
    original_status = bridge.analysis.analysis_status

    candidate = FakeAuroraProvider().analyze(bridge.records, bridge.spans, "q")
    candidate["next_action"] = dict(candidate["next_action"], statement="Escalate the studio move discrepancy immediately.")

    revise_resp = bridge.handle({"command": "send_message", "message": "please update the analysis", "revision_candidate": candidate})
    assert revise_resp["ok"] is True
    assert revise_resp["data"]["kind"] == "analysis_revision_proposal"
    proposal_id = revise_resp["data"]["analysis_revision_proposal"]["proposal_id"]

    assert bridge.analysis.analysis_status == original_status
    assert bridge.analysis.next_action.statement != candidate["next_action"]["statement"]

    confirm_resp = bridge.handle({"command": "confirm_analysis_revision", "proposal_id": proposal_id})
    assert confirm_resp["ok"] is True
    assert confirm_resp["data"]["confirmed"] is True
    assert confirm_resp["data"]["proposal_id"] == proposal_id
    assert confirm_resp["data"]["next_action"]["statement"] == candidate["next_action"]["statement"]
    assert bridge.analysis.next_action.statement == candidate["next_action"]["statement"]

    second_resp = bridge.handle({"command": "confirm_analysis_revision", "proposal_id": proposal_id})
    assert second_resp["ok"] is False

def test_send_message_project_grounded_uses_backend_hydrated_citations(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    resp = bridge.handle({"command": "send_message", "message": "tell me about the project status"})
    assert resp["ok"] is True
    assert resp["data"]["kind"] == "project_grounded"
    cards = resp["data"]["citation_cards"]
    assert cards
    span_texts = {s.span_id: s.text for s in bridge.spans}
    for card in cards:
        assert set(card.keys()) == CITATION_CARD_FIELDS
        assert card["exact_text"] == span_texts[card["span_id"]]

def test_analyze_before_load_returns_controlled_error(tmp_path: Path):
    bridge = Bridge()
    resp = bridge.handle({"command": "analyze_project", "question": "q"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"
    assert set(resp["error"].keys()) == {"code", "message", "object_id"}
    assert resp["error"]["object_id"] is None

def test_confirm_attestation_without_active_vault_returns_controlled_error(tmp_path: Path):
    bridge = Bridge()
    resp = bridge.handle({"command": "confirm_attestation", "proposal_id": "PROP-doesnotexist"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "vault_locked"

def test_confirm_attestation_with_locked_vault_returns_controlled_error(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "lock_vault"})
    resp = bridge.handle({"command": "confirm_attestation", "proposal_id": "PROP-doesnotexist"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "vault_locked"

def test_failed_unlock_does_not_replace_active_bridge_vault(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    original_vault = bridge.vault
    original_session = bridge.vault.session
    resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "wrong"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "vault_auth_failed"
    assert bridge.vault is original_vault
    assert bridge.vault.session is original_session

def test_failed_project_load_preserves_previous_state_and_leaks_nothing(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    previous_records = bridge.records
    previous_count = len(bridge.artifact_records)
    missing_path = str(tmp_path / "does-not-exist-at-all")
    resp = bridge.handle({"command": "load_project", "artifact_root": missing_path})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"
    body = json.dumps(resp, ensure_ascii=False)
    assert missing_path not in body
    assert "does-not-exist-at-all" not in body
    assert "Traceback" not in body
    assert bridge.records == previous_records
    assert len(bridge.artifact_records) == previous_count

def test_bridge_handles_malformed_commands_safely(tmp_path: Path):
    bridge = Bridge()
    scenarios = [
        "not a dict",
        123,
        None,
        {"no_command_field": True},
        {"command": 123},
        {"command": ""},
        {"command": "bogus_unknown_command"},
        {"command": "initialize_vault"},
        {"command": "initialize_vault", "path": 123, "password": "secret"},
    ]
    for cmd in scenarios:
        resp = bridge.handle(cmd)
        assert resp["ok"] is False
        assert set(resp["error"].keys()) == {"code", "message", "object_id"}
        assert resp["error"]["object_id"] is None
        body = json.dumps(resp, ensure_ascii=False)
        assert "Traceback" not in body
        assert "Exception" not in body

def test_decode_command_rejects_invalid_utf8_json_and_non_object():
    with pytest.raises(ValidationError):
        decode_command(b"\xff\xfe not valid utf-8")
    with pytest.raises(ValidationError):
        decode_command(b"{not valid json")
    with pytest.raises(ValidationError):
        decode_command(b"[1, 2, 3]")

def test_bridge_failures_never_leak_sensitive_content(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "definitely-wrong-password"})
    body = json.dumps(unlock_resp, ensure_ascii=False)
    assert "definitely-wrong-password" not in body
    assert vault_path not in body
    assert "VaultAuthError" not in body
    assert "Traceback" not in body

    bridge.handle({"command": "send_message", "message": "I attest a very secret detail nobody should see"})
    bad_resp = bridge.handle({"command": "confirm_attestation", "proposal_id": "PROP-does-not-exist"})
    assert bad_resp["ok"] is False
    bad_body = json.dumps(bad_resp, ensure_ascii=False)
    assert "very secret detail" not in bad_body

class _HostileForgedMetadataProvider:
    provider_id = "hostile-forged-metadata-v1"
    def analyze(self, evidence, spans, question):
        base = FakeAuroraProvider().analyze(evidence, spans, question)
        forged = ' Source: "FORGED PROVIDER TITLE" by FORGED PROVIDER AUTHOR: "FORGED PROVIDER EXACT TEXT"'
        base = dict(base)
        base["current_state"] = dict(base["current_state"], statement=base["current_state"]["statement"] + forged)
        base["continuity_break"] = dict(base["continuity_break"], statement=base["continuity_break"]["statement"] + forged)
        base["next_action"] = dict(base["next_action"], statement=base["next_action"]["statement"] + forged)
        return base

def test_hostile_provider_forged_metadata_never_reaches_citation_cards(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path, provider=_HostileForgedMetadataProvider())
    resp = bridge.handle({"command": "analyze_project", "question": "q"})
    assert resp["ok"] is True
    data = resp["data"]
    assert set(data.keys()) >= {"analysis_status", "continuity_break_kind", "current_state", "semantic_annotations", "continuity_break", "next_action", "citation_cards"}
    assert "FORGED PROVIDER" in data["current_state"]["statement"]

    span_texts = {s.span_id: s.text for s in bridge.spans}
    cards = data["citation_cards"]
    assert cards
    for card in cards:
        assert set(card.keys()) == CITATION_CARD_FIELDS
        assert card["exact_text"] == span_texts[card["span_id"]]
        for value in card.values():
            if isinstance(value, str):
                assert "FORGED PROVIDER" not in value

def test_successful_initialize_vault_replacement_invalidates_previous_vault_and_evidence(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    propose_resp = bridge.handle({"command": "send_message", "message": "I attest something old"})
    proposal_id = propose_resp["data"]["attestation_proposal"]["proposal_id"]
    confirm_resp = bridge.handle({"command": "confirm_attestation", "proposal_id": proposal_id})
    old_evidence_id = confirm_resp["data"]["evidence_id"]
    assert len(bridge.records) == 6

    old_vault = bridge.vault
    old_session = old_vault.session
    old_key_buffer = old_session.key_buffer
    pending_resp = bridge.handle({"command": "send_message", "message": "I attest something pending"})
    assert pending_resp["data"]["kind"] == "attestation_proposal"
    assert old_vault.pending_attestations

    new_vault_path = str(tmp_path / "vault2.bin")
    init_resp = bridge.handle({"command": "initialize_vault", "path": new_vault_path, "password": "other-secret", "owner_name": "Ktoś"})
    assert init_resp["ok"] is True

    assert old_session.unlocked is False
    assert set(old_key_buffer) == {0}
    assert old_vault.pending_attestations == {}
    assert bridge.vault is not old_vault
    assert len(bridge.artifact_records) == 5
    assert len(bridge.records) == 5
    assert all(r.evidence_id != old_evidence_id for r in bridge.records)
    assert bridge.analysis is None
    assert bridge.snapshot is None
    assert bridge.last_question is None

def test_initialize_vault_composition_failure_preserves_previous_active_vault(tmp_path: Path, monkeypatch):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    original_vault = bridge.vault
    original_session = bridge.vault.session
    previous_records = bridge.records
    previous_spans = bridge.spans
    previous_analysis = bridge.analysis
    previous_snapshot = bridge.snapshot
    previous_question = bridge.last_question

    monkeypatch.setattr("continuity_ai.bridge.build_spans", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    new_vault_path = str(tmp_path / "vault2.bin")
    resp = bridge.handle({"command": "initialize_vault", "path": new_vault_path, "password": "other-secret", "owner_name": "Ktoś"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"
    assert bridge.vault is original_vault
    assert bridge.vault.session is original_session
    assert original_session.unlocked is True
    assert bridge.records == previous_records
    assert bridge.spans == previous_spans
    assert bridge.analysis is previous_analysis
    assert bridge.snapshot is previous_snapshot
    assert bridge.last_question == previous_question

def test_unlock_composition_failure_preserves_previous_active_vault_and_pending_state(tmp_path: Path, monkeypatch):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    original_vault = bridge.vault
    original_session = bridge.vault.session
    previous_records = bridge.records
    previous_spans = bridge.spans
    previous_analysis = bridge.analysis
    previous_snapshot = bridge.snapshot
    previous_question = bridge.last_question
    propose_resp = bridge.handle({"command": "send_message", "message": "I attest something pending"})
    proposal_id = propose_resp["data"]["attestation_proposal"]["proposal_id"]
    assert bridge.vault.pending_attestations

    monkeypatch.setattr("continuity_ai.bridge.build_spans", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"
    assert bridge.vault is original_vault
    assert bridge.vault.session is original_session
    assert original_session.unlocked is True
    assert bridge.records == previous_records
    assert bridge.spans == previous_spans
    assert bridge.analysis is previous_analysis
    assert bridge.snapshot is previous_snapshot
    assert bridge.last_question == previous_question
    assert proposal_id in bridge.vault.pending_attestations

def test_load_project_composition_failure_preserves_previous_complete_state(tmp_path: Path, monkeypatch):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    previous_artifact_records = bridge.artifact_records
    previous_records = bridge.records
    previous_spans = bridge.spans
    previous_analysis = bridge.analysis
    previous_snapshot = bridge.snapshot
    previous_question = bridge.last_question

    monkeypatch.setattr("continuity_ai.bridge.build_spans", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = bridge.handle({"command": "load_project", "artifact_root": artifact_root})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"
    assert bridge.artifact_records == previous_artifact_records
    assert bridge.records == previous_records
    assert bridge.spans == previous_spans
    assert bridge.analysis is previous_analysis
    assert bridge.snapshot is previous_snapshot
    assert bridge.last_question == previous_question

def test_successful_unlock_replacement_invalidates_old_session_and_refreshes_attestations(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    propose_resp = bridge.handle({"command": "send_message", "message": "attest one"})
    proposal_id = propose_resp["data"]["attestation_proposal"]["proposal_id"]
    bridge.handle({"command": "confirm_attestation", "proposal_id": proposal_id})
    assert len(bridge.records) == 6

    old_vault = bridge.vault
    old_session = old_vault.session

    direct = Vault(Path(vault_path))
    direct.unlock("secret")
    p2 = direct.propose_attestation("attest two, added out of band")
    direct.confirm_attestation(p2.proposal_id)

    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True
    assert old_session.unlocked is False
    assert set(old_session.key_buffer) == {0}
    assert old_vault.pending_attestations == {}
    assert bridge.vault is not old_vault
    assert len(bridge.records) == 7
    assert bridge.analysis is None
    assert bridge.snapshot is None
    assert bridge.last_question is None

class _FailIfCalledProvider:
    provider_id = "fail-if-called-v1"
    def analyze(self, evidence, spans, question):
        raise AssertionError("provider must not be called for a non-string question")

def test_analyze_project_rejects_non_string_question_before_calling_provider(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path, provider=_FailIfCalledProvider())
    resp = bridge.handle({"command": "analyze_project", "question": 123})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_error"

def test_openai_adapter_uses_fake_client(monkeypatch):
    class Responses:
        def create(self, **kwargs):
            assert kwargs["store"] is False and kwargs["tools"] == []
            return type("R",(),{"output_parsed":{"schema_version":"2.0"}})()
    monkeypatch.setenv("CONTINUITY_OPENAI_MODEL","fake-model")
    provider=OpenAIReasoningProvider(type("C",(),{"responses":Responses()})())
    assert provider.analyze((),(),"q")["schema_version"] == "2.0"

def test_project_aurora_remains_propagation_break(tmp_path: Path):
    records=aurora(tmp_path)
    result, spans, snap=run_analysis(records,"q",FakeAuroraProvider())
    assert result.analysis_status == "break_found"
    assert result.continuity_break_kind == "propagation_break"

def test_decision_provenance_break_requires_two_records_and_no_approval():
    from continuity_ai.domain import ReasoningEvidence
    records=(
        ReasoningEvidence("EV-GEN-001","note","Alex","2026-01-01T00:00:00Z","Earlier scope","Feature Relay is included.","artifact"),
        ReasoningEvidence("EV-GEN-002","note","Blair","2026-01-02T00:00:00Z","Later scope","Feature Relay is removed.","artifact"),
    )
    from continuity_ai.reasoning_pipeline import FakeDecisionProvenanceProvider
    result, spans, snap=run_analysis(records,"what changed",FakeDecisionProvenanceProvider())
    assert result.continuity_break_kind == "decision_provenance_not_found"
    assert "couldn’t find an approval, decision, or note" in result.continuity_break.statement
    assert "There is no decision" not in result.continuity_break.statement
    assert "Add or link the decision" in result.next_action.statement
    bad=FakeDecisionProvenanceProvider().analyze(records,spans,"q")
    bad["semantic_annotations"][0]["propagation_role"]="approved_decision"
    with pytest.raises(ValidationError): validate_analysis(bad,records,spans)
    bad=FakeDecisionProvenanceProvider().analyze(records,spans,"q")
    bad["continuity_break"]["span_ids"]=[spans[0].span_id]
    with pytest.raises(ValidationError): validate_analysis(bad,records,spans)

def test_public_messages_are_human_and_bridge_does_not_leak_internal_names(tmp_path: Path):
    from continuity_ai.errors import InsufficientEvidenceError, VaultLockedError, ProviderError, ValidationError, ExternalInformationUnavailableError
    errors=[InsufficientEvidenceError(), VaultLockedError(), ProviderError(), ValidationError(), ExternalInformationUnavailableError()]
    messages=[e.to_dict()["message"] for e in errors]
    assert "I couldn’t find that document in the project sources currently available to Continuity AI." in messages
    assert "Unlock the project vault to continue." in messages
    assert "I can’t check current external information because web access is not available in this version." in messages
    prohibited=["EvidenceSet","insufficient_evidence","decision_provenance_not_found","active unlocked owner session","reasoning provider error","validation failed","object_id","material change detected","No matching source exists","VaultLockedError","ValidationError","traceback"]
    for msg in messages:
        for phrase in prohibited:
            assert phrase not in msg
    # Every controlled error must serialize to exactly {code, message, object_id},
    # with object_id null when not supplied, and no path/password/owner/traceback/class leakage.
    for e in errors:
        serialized=e.to_dict()
        assert set(serialized.keys()) == {"code", "message", "object_id"}
        assert serialized["object_id"] is None
    assert ValidationError().to_dict()["code"] == "validation_error"
    assert VaultAlreadyExistsError().to_dict()["code"] == "vault_already_exists"
    resp=Bridge().handle({"command":"unlock_vault","path":str(tmp_path/"missing"),"password":"wrong"})
    body=json.dumps(resp, ensure_ascii=False)
    assert resp["ok"] is False
    assert set(resp["error"].keys()) == {"code", "message", "object_id"}
    assert resp["error"]["object_id"] is None
    assert resp["error"]["code"] == "vault_auth_failed"
    prohibited_in_body=[phrase for phrase in prohibited if phrase != "object_id"]
    for phrase in prohibited_in_body:
        assert phrase not in body
    assert "wrong" not in body
    assert str(tmp_path) not in body
    assert "VaultAuthError" not in body
    assert "Traceback" not in body

def test_no_break_requires_null_break_kind(tmp_path: Path):
    records=aurora(tmp_path); spans=build_spans(records); candidate=FakeAuroraProvider().analyze(records,spans,"q")
    candidate["analysis_status"]="no_material_break_found"
    candidate["continuity_break_kind"]=None
    candidate["continuity_break"]=None
    candidate["next_action"]=None
    for ann in candidate["semantic_annotations"]:
        ann["propagation_role"]="none"
    result=validate_analysis(candidate,records,spans)
    assert result.continuity_break_kind is None
    candidate["continuity_break_kind"]="propagation_break"
    with pytest.raises(ValidationError): validate_analysis(candidate,records,spans)
