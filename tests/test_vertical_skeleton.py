from __future__ import annotations
import json
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
