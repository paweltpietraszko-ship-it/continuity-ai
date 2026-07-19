"""Contract tests for project identity (schema 3.0): `project` flowing through
load_project/get_workspace_state/retained persistence, atomic project_mismatch
protection, the neutral evidence_records projection, and owner-name privacy.
"""
from __future__ import annotations
import json
from pathlib import Path
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.bridge import Bridge
from continuity_ai.reasoning_pipeline import DeterministicOfflineReasoningProvider
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider

_ARTIFACT_ROOT = "fixtures/project_aurora/generated/artifacts"
_EVIDENCE_RECORD_FIELDS = {
    "source_id", "evidence_id", "author", "timestamp", "source_type", "title", "uri", "artifact_sha256", "content",
}


def _init_and_load(tmp_path: Path, provider=None):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = str(tmp_path / _ARTIFACT_ROOT)
    vault_path = str(tmp_path / "vault.bin")
    # This module tests project identity/report persistence, not Source
    # Scoping; the fake provider keeps analyze_project on the legacy
    # unscoped path these tests were written against.
    bridge = Bridge(
        provider=provider if provider is not None else DeterministicOfflineReasoningProvider(),
        source_scoping_provider=FakeSourceScopingProvider(),
    )
    bridge.handle({"command": "initialize_vault", "path": vault_path, "password": "secret", "owner_name": "Paweł"})
    bridge.handle({"command": "load_project", "artifact_root": artifact_root})
    return bridge, vault_path, artifact_root


class _FailIfCalledProvider:
    provider_id = "fail-if-called-project-identity"
    def analyze(self, evidence, spans, question):
        raise AssertionError("reasoning provider must not be called to restore retained history")


def test_load_project_returns_project_and_neutral_evidence_records(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    resp = bridge.handle({"command": "load_project", "artifact_root": artifact_root})
    assert resp["ok"] is True
    data = resp["data"]

    assert data["project"] == "Project Aurora"
    assert data["artifact_evidence_count"] == 5
    assert data["evidence_count"] == 5

    records = data["evidence_records"]
    assert len(records) == 5
    for record in records:
        assert set(record) == _EVIDENCE_RECORD_FIELDS
        assert record["content"].strip()
        assert record["artifact_sha256"]
        assert record["evidence_id"].strip()


def test_get_workspace_state_always_exposes_project_and_evidence_records(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["project"] == "Project Aurora"
    assert len(state["evidence_records"]) == 5
    assert state["project_report"] is None  # no analysis has run yet


def test_project_and_project_report_persist_and_restore_after_lock_and_unlock(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "what changed?"})
    assert analyze_resp["ok"] is True
    original_report = analyze_resp["data"]["project_report"]

    bridge.handle({"command": "lock_vault"})
    bridge.provider = _FailIfCalledProvider()
    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["project"] == "Project Aurora"
    assert state["retained_analysis_status"] == "valid"
    assert state["project_report"] == original_report


def test_project_mismatch_rejected_atomically_preserving_previous_state(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "what changed?"})

    other_root = tmp_path / "other"
    other_artifact_root = other_root / _ARTIFACT_ROOT
    generate_project_aurora_fixture(other_root)
    manifest_path = other_artifact_root / "evidence_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["project"] = "A Completely Different Project"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    before_project = bridge.project
    before_records = bridge.records
    before_artifact_evidence_records = bridge.artifact_evidence_records
    before_analysis = bridge.analysis
    before_snapshot = bridge.snapshot

    resp = bridge.handle({"command": "load_project", "artifact_root": str(other_artifact_root)})
    assert resp["ok"] is False
    assert resp["command"] == "load_project"
    assert resp["error"] == {
        "code": "project_mismatch",
        "message": "The selected project does not match the retained analysis.",
        "object_id": None,
    }

    assert bridge.project == before_project == "Project Aurora"
    assert bridge.records == before_records
    assert bridge.artifact_evidence_records == before_artifact_evidence_records
    assert bridge.analysis is before_analysis
    assert bridge.snapshot is before_snapshot

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["project"] == "Project Aurora"
    assert state["has_analysis"] is True
    assert state["retained_analysis_status"] == "valid"


def test_owner_display_name_available_when_unlocked_and_null_when_locked(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    unlocked_state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert unlocked_state["owner_display_name"] == "Paweł"

    bridge.handle({"command": "lock_vault"})
    locked_state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert locked_state["owner_display_name"] is None


def test_initialize_and_unlock_vault_return_owner_display_name(tmp_path: Path):
    vault_path = str(tmp_path / "vault.bin")
    bridge = Bridge(provider=DeterministicOfflineReasoningProvider())
    init_resp = bridge.handle({
        "command": "initialize_vault", "path": vault_path, "password": "secret", "owner_name": "Zażółć",
    })
    assert init_resp["ok"] is True
    assert init_resp["data"]["owner_display_name"] == "Zażółć"
    assert isinstance(init_resp["data"]["session_id"], str) and init_resp["data"]["session_id"]

    bridge.handle({"command": "lock_vault"})
    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True
    assert unlock_resp["data"]["owner_display_name"] == "Zażółć"


def test_citation_cards_include_project_report_spans_and_are_all_backend_known(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    resp = bridge.handle({"command": "analyze_project", "question": "what changed?"})
    data = resp["data"]
    cited_span_ids = {c["span_id"] for c in data["citation_cards"]}

    report_span_ids = set(data["project_report"]["summary"]["span_ids"])
    for section in data["project_report"]["sections"]:
        report_span_ids |= set(section["span_ids"])

    assert report_span_ids  # sanity: the fixture's report actually cites spans
    assert report_span_ids <= cited_span_ids

    known_span_ids = {s.span_id for s in bridge.spans}
    assert cited_span_ids <= known_span_ids


def test_owner_name_never_appears_in_the_plaintext_vault_envelope(tmp_path: Path):
    vault_path = tmp_path / "vault.bin"
    bridge = Bridge(provider=DeterministicOfflineReasoningProvider())
    bridge.handle({
        "command": "initialize_vault", "path": str(vault_path), "password": "secret", "owner_name": "Zażółć Gęślą",
    })

    envelope = json.loads(vault_path.read_text("utf-8"))
    assert set(envelope) == {"format", "version", "kdf", "salt", "encryption", "nonce", "ciphertext"}
    raw = vault_path.read_bytes()
    assert "Zażółć Gęślą".encode("utf-8") not in raw
