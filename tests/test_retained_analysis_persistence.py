"""Contract tests for Retained Analysis Persistence and Snapshot Fidelity.

Covers F-01 (restoration must have semantic parity with initial validation),
F-02 (top-level identity/timestamp/schema binding), F-03 (fail-closed newest-entry
restore policy), F-04 (live-source drift exposed as source_changed_since_analysis),
F-05 (load_project after unlock must not discard a restored analysis), and the
original F-PERSIST-01 / F-CITE-01 persistence and snapshot-hydration guarantees.
"""
from __future__ import annotations
import copy
import uuid
from pathlib import Path
import pytest
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.bridge import Bridge
from continuity_ai.domain import ReasoningEvidence, SavedAnalysis
from continuity_ai.evidence import build_spans, make_snapshot
from continuity_ai.reasoning_pipeline import FakeAuroraProvider, SUPPORTED_SCHEMA_VERSION, validate_analysis
from continuity_ai.retained_analysis import (
    RETAINED_ANALYSIS_INVALID,
    RETAINED_ANALYSIS_NONE,
    RETAINED_ANALYSIS_VALID,
    InvalidSavedAnalysisError,
    restore_latest,
    saved_analysis_from_payload,
    saved_analysis_to_payload,
)
from continuity_ai.vault import Vault


# ---------------------------------------------------------------------------
# Bridge-level integration fixtures (Project Aurora, real vault, real bridge)
# ---------------------------------------------------------------------------

def _init_and_load(tmp_path: Path, provider=None):
    generate_project_aurora_fixture(tmp_path)
    artifact_root = str(tmp_path / "fixtures/project_aurora/generated/artifacts")
    vault_path = str(tmp_path / "vault.bin")
    selected_provider = provider if provider is not None else FakeAuroraProvider()
    bridge = Bridge(provider=selected_provider)
    bridge.handle({"command": "initialize_vault", "path": vault_path, "password": "secret", "owner_name": "Paweł"})
    bridge.handle({"command": "load_project", "artifact_root": artifact_root})
    return bridge, vault_path, artifact_root


class _FailIfCalledProvider:
    provider_id = "fail-if-called-restore-v1"
    def analyze(self, evidence, spans, question):
        raise AssertionError("reasoning provider must not be called to restore retained history")


# ---------------------------------------------------------------------------
# Small explicit worlds for unit-level validator-parity contract examples.
# Deliberately independent of FakeAuroraProvider's positional evidence ordering.
# ---------------------------------------------------------------------------

def _propagation_world() -> tuple[tuple[ReasoningEvidence, ...], tuple]:
    records = (
        ReasoningEvidence("EV-A", "decision", "Alex", "2026-01-01T00:00:00Z", "Approval", "The team approves the location change.", "artifact", "file:///a", "a" * 64),
        ReasoningEvidence("EV-B", "runbook", "Blair", "2026-01-02T00:00:00Z", "Runbook", "The runbook still lists the old location.", "artifact", None, None),
    )
    return records, build_spans(records)


_SECTION_NAMES = ("decision", "budget", "schedule", "operations", "readiness", "casting", "agreements")


def _evidence_gap_section(section: str) -> dict:
    return {
        "section": section,
        "status": "evidence_gap",
        "headline": "No verified status available",
        "statement": f"No available project source establishes the current {section} status.",
        "span_ids": [],
    }


def _project_report_with_one_attention(summary_span_ids: list, attention_span_ids: list) -> dict:
    sections = [
        {
            "section": "decision",
            "status": "attention",
            "headline": "Needs attention",
            "statement": "The approved change has not fully propagated.",
            "span_ids": attention_span_ids,
        },
        *[_evidence_gap_section(name) for name in _SECTION_NAMES[1:]],
    ]
    return {
        "summary": {"statement": "Summary of the current project state.", "span_ids": summary_span_ids},
        "sections": sections,
    }


def _propagation_candidate(records, spans) -> dict:
    span_a, span_b = spans[0].span_id, spans[1].span_id
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "analysis_status": "break_found",
        "continuity_break_kind": "propagation_break",
        "current_state": {"statement": "The approved change has not reached the runbook.", "span_ids": [span_a, span_b]},
        "semantic_annotations": [
            {"evidence_id": "EV-A", "propagation_role": "approved_decision", "context_tags": []},
            {"evidence_id": "EV-B", "propagation_role": "conflicts_with_decision", "context_tags": []},
        ],
        "continuity_break": {"statement": "Approved but not propagated to the runbook.", "span_ids": [span_a, span_b]},
        "next_action": {"statement": "Update the runbook.", "span_ids": [span_b]},
        "project_report": _project_report_with_one_attention([span_a], [span_a, span_b]),
    }


def _decision_provenance_world() -> tuple[tuple[ReasoningEvidence, ...], tuple]:
    records = (
        ReasoningEvidence("EV-X", "note", "Alex", "2026-02-01T00:00:00Z", "Earlier scope", "Feature Relay is included.", "artifact"),
        ReasoningEvidence("EV-Y", "note", "Blair", "2026-02-02T00:00:00Z", "Later scope", "Feature Relay is removed.", "artifact"),
    )
    return records, build_spans(records)


def _decision_provenance_candidate(records, spans) -> dict:
    span_x, span_y = spans[0].span_id, spans[1].span_id
    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "analysis_status": "break_found",
        "continuity_break_kind": "decision_provenance_not_found",
        "current_state": {"statement": "A project item changed and no approval was found.", "span_ids": [span_x, span_y]},
        "semantic_annotations": [
            {"evidence_id": "EV-X", "propagation_role": "none", "context_tags": []},
            {"evidence_id": "EV-Y", "propagation_role": "none", "context_tags": []},
        ],
        "continuity_break": {"statement": "No decision found for this change.", "span_ids": [span_x, span_y]},
        "next_action": {"statement": "Add or link the decision that approved this change.", "span_ids": [span_x, span_y]},
        "project_report": _project_report_with_one_attention([span_x], [span_x, span_y]),
    }


def _build_saved_analysis(records, spans, candidate: dict, question: str = "what changed?", project: str = "Test Project") -> SavedAnalysis:
    result = validate_analysis(candidate, records, spans)
    snapshot = make_snapshot("AN-TEST-" + uuid.uuid4().hex, records, spans, "g03_reasoning_v3", SUPPORTED_SCHEMA_VERSION, "test-provider-v1")
    return SavedAnalysis(snapshot.analysis_id, snapshot.created_at, result, snapshot, question, project)


def _valid_propagation_payload() -> dict:
    records, spans = _propagation_world()
    return saved_analysis_to_payload(_build_saved_analysis(records, spans, _propagation_candidate(records, spans)))


def _valid_decision_provenance_payload() -> dict:
    records, spans = _decision_provenance_world()
    return saved_analysis_to_payload(_build_saved_analysis(records, spans, _decision_provenance_candidate(records, spans)))


def _assert_rejected(raw: dict) -> None:
    with pytest.raises(InvalidSavedAnalysisError):
        saved_analysis_from_payload(raw)


# ---------------------------------------------------------------------------
# F-01 / F-06: restoration has exact semantic parity with initial validation,
# because it calls the same canonical validator (reasoning_pipeline.validate_analysis_payload).
# ---------------------------------------------------------------------------

def test_valid_retained_unit_restores_cleanly():
    raw = _valid_propagation_payload()
    restored = saved_analysis_from_payload(raw)
    assert restored.result.analysis_status == "break_found"
    assert restored.result.continuity_break_kind == "propagation_break"


def test_schema_3_0_round_trip_preserves_project_and_project_report():
    """Full SavedAnalysis schema 3.0 round-trip: project identity and the
    complete project_report (summary + all seven sections) survive
    serialize -> deserialize unchanged."""
    records, spans = _propagation_world()
    saved = _build_saved_analysis(records, spans, _propagation_candidate(records, spans), project="Round Trip Project")
    restored = saved_analysis_from_payload(saved_analysis_to_payload(saved))

    assert restored.project == "Round Trip Project"
    assert restored.result.schema_version == "3.0"
    assert restored.result.project_report.summary == saved.result.project_report.summary
    assert restored.result.project_report.sections == saved.result.project_report.sections
    assert [s.section for s in restored.result.project_report.sections] == list(_SECTION_NAMES)


def test_schema_2_0_retained_analysis_is_rejected_as_invalid():
    """A retained analysis from the superseded schema 2.0 contract (no
    project_report, no top-level project) must be rejected outright rather
    than migrated or partially accepted."""
    raw = copy.deepcopy(_valid_propagation_payload())
    del raw["project"]
    del raw["result"]["project_report"]
    raw["result"]["schema_version"] = "2.0"
    raw["evidence_snapshot"]["schema_version"] = "2.0"
    _assert_rejected(raw)

    outcome = restore_latest([raw])
    assert outcome.status == RETAINED_ANALYSIS_INVALID
    assert outcome.saved is None


def test_wrong_result_schema_version_rejected_on_restore():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["schema_version"] = "1.0"
    _assert_rejected(raw)


def test_break_found_without_continuity_break_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["continuity_break"] = None
    _assert_rejected(raw)


def test_break_found_without_next_action_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["next_action"] = None
    _assert_rejected(raw)


def test_no_material_break_found_with_break_fields_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["analysis_status"] = "no_material_break_found"
    raw["result"]["continuity_break_kind"] = None
    # continuity_break/next_action deliberately left populated: contradicts the status.
    _assert_rejected(raw)


def test_annotation_with_unknown_evidence_id_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["semantic_annotations"][0]["evidence_id"] = "EV-GHOST"
    _assert_rejected(raw)


def test_duplicate_annotation_evidence_id_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["semantic_annotations"][1]["evidence_id"] = raw["result"]["semantic_annotations"][0]["evidence_id"]
    _assert_rejected(raw)


def test_incomplete_annotation_coverage_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["result"]["semantic_annotations"] = raw["result"]["semantic_annotations"][:1]
    _assert_rejected(raw)


def test_invalid_status_role_combination_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    # propagation_break requires at least one approved_decision role; remove it.
    raw["result"]["semantic_annotations"][0]["propagation_role"] = "reflects_decision"
    _assert_rejected(raw)


def test_invalid_decision_provenance_role_combination_rejected():
    raw = copy.deepcopy(_valid_decision_provenance_payload())
    # decision_provenance_not_found forbids an approved_decision role.
    raw["result"]["semantic_annotations"][0]["propagation_role"] = "approved_decision"
    _assert_rejected(raw)


# ---------------------------------------------------------------------------
# F-02: top-level identity/timestamp/schema binding between SavedAnalysis and
# its EvidenceSnapshot, plus strict snapshot structural validation.
# ---------------------------------------------------------------------------

def test_top_level_analysis_id_mismatch_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["analysis_id"] = "AN-DIFFERENT-FROM-SNAPSHOT"
    _assert_rejected(raw)


def test_top_level_created_at_mismatch_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["created_at"] = "2099-01-01T00:00:00Z"
    _assert_rejected(raw)


def test_result_snapshot_schema_mismatch_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["schema_version"] = "9.9"
    _assert_rejected(raw)


def test_empty_prompt_version_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["prompt_version"] = "   "
    _assert_rejected(raw)


def test_empty_provider_id_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["provider_id"] = ""
    _assert_rejected(raw)


def test_invalid_provenance_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["records"][0]["provenance"] = "bogus_provenance"
    _assert_rejected(raw)


def test_empty_span_exact_text_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["spans"][0]["exact_text"] = ""
    _assert_rejected(raw)


def test_span_whose_owner_is_absent_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["spans"][0]["evidence_id"] = "EV-GHOST"
    _assert_rejected(raw)


def test_non_hash_shaped_canonical_content_hash_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    raw["evidence_snapshot"]["records"][0]["canonical_content_sha256"] = "not-a-hash"
    _assert_rejected(raw)


def test_missing_or_incomplete_snapshot_rejected():
    missing = copy.deepcopy(_valid_propagation_payload())
    del missing["evidence_snapshot"]
    _assert_rejected(missing)

    incomplete = copy.deepcopy(_valid_propagation_payload())
    incomplete["evidence_snapshot"]["spans"] = []
    _assert_rejected(incomplete)


# ---------------------------------------------------------------------------
# F-03: fail-closed newest-entry-only restore policy.
# ---------------------------------------------------------------------------

def test_restore_latest_reports_none_for_empty_history():
    outcome = restore_latest([])
    assert outcome.status == RETAINED_ANALYSIS_NONE
    assert outcome.saved is None


def test_restore_latest_never_falls_back_to_an_older_valid_entry():
    good = _valid_propagation_payload()
    malformed = {"garbage": True}

    outcome = restore_latest([good, malformed])
    assert outcome.status == RETAINED_ANALYSIS_INVALID
    assert outcome.saved is None

    only_good = restore_latest([good])
    assert only_good.status == RETAINED_ANALYSIS_VALID
    assert only_good.saved is not None


def test_invalid_newest_entry_exposes_safe_invalid_status_without_crashing_vault(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    assert len(bridge.vault.payload["saved_analyses"]) == 1

    bridge.vault.payload["saved_analyses"].append({"garbage": True})
    bridge.vault.persist()

    bridge.handle({"command": "lock_vault"})
    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["retained_analysis_status"] == RETAINED_ANALYSIS_INVALID
    assert state["has_analysis"] is False
    assert "citation_cards" not in state
    assert "analysis_status" not in state


# ---------------------------------------------------------------------------
# F-04: historical citation text is snapshot-owned; drift is exposed as a
# status label, never by rewriting the retained quotation.
# ---------------------------------------------------------------------------

def test_unchanged_current_evidence_reports_snapshot_status(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    resp = bridge.handle({"command": "analyze_project", "question": "q"})
    assert resp["data"]["citation_cards"]
    for card in resp["data"]["citation_cards"]:
        assert card["source_status"] == "snapshot"

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    for card in state["citation_cards"]:
        assert card["source_status"] == "snapshot"


def test_changed_current_evidence_preserves_historical_text_and_flags_change(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    original_cards = analyze_resp["data"]["citation_cards"]
    assert original_cards

    mutated = tuple(
        ReasoningEvidence(r.evidence_id, r.source_type, r.author_or_actor, r.timestamp, r.title, r.content + " MUTATED LIVE CONTENT", r.provenance, r.uri, r.artifact_sha256)
        for r in bridge.records
    )
    bridge.records = mutated
    bridge.spans = build_spans(mutated)

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert len(state["citation_cards"]) == len(original_cards)
    for card, original in zip(state["citation_cards"], original_cards):
        assert card["exact_text"] == original["exact_text"]
        assert "MUTATED LIVE CONTENT" not in card["exact_text"]
        assert card["source_status"] == "source_changed_since_analysis"


def test_removed_current_evidence_preserves_historical_text_and_flags_change(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "q"})
    original_cards = analyze_resp["data"]["citation_cards"]
    removed_evidence_id = original_cards[0]["evidence_id"]

    bridge.records = tuple(r for r in bridge.records if r.evidence_id != removed_evidence_id)
    bridge.spans = build_spans(bridge.records)

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    original_by_span = {c["span_id"]: c for c in original_cards}
    for card in state["citation_cards"]:
        original = original_by_span[card["span_id"]]
        assert card["exact_text"] == original["exact_text"]
        if card["evidence_id"] == removed_evidence_id:
            assert card["source_status"] == "source_changed_since_analysis"
        else:
            assert card["source_status"] == "snapshot"


def test_no_live_evidence_loaded_does_not_falsely_claim_a_comparison(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    del bridge

    recovered = Bridge(provider=_FailIfCalledProvider())
    recovered.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    # No load_project on the new instance: no live evidence basis for comparison.
    assert recovered.records == ()

    state = recovered.handle({"command": "get_workspace_state"})["data"]
    for card in state["citation_cards"]:
        assert card["source_status"] == "snapshot"


# ---------------------------------------------------------------------------
# F-05: load_project after unlock must not discard a restored analysis.
# ---------------------------------------------------------------------------

def test_unlock_then_load_project_retains_restored_analysis(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    original_cards = analyze_resp["data"]["citation_cards"]

    bridge.handle({"command": "lock_vault"})
    bridge.provider = _FailIfCalledProvider()
    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True
    assert bridge.analysis is not None

    reload_resp = bridge.handle({"command": "load_project", "artifact_root": artifact_root})
    assert reload_resp["ok"] is True

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["has_analysis"] is True
    assert state["retained_analysis_status"] == RETAINED_ANALYSIS_VALID
    assert state["citation_cards"] == original_cards


# ---------------------------------------------------------------------------
# Restoration, transactional persistence, and cross-vault isolation
# (F-PERSIST-01 / F-CITE-01 baseline guarantees, re-verified against the
# corrected module boundaries).
# ---------------------------------------------------------------------------

def test_initial_analysis_is_persisted_as_complete_retained_unit(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    assert resp["ok"] is True

    saved_analyses = bridge.vault.payload["saved_analyses"]
    assert len(saved_analyses) == 1
    raw = saved_analyses[0]
    assert raw["question"] == "what changed overnight?"

    raw_bytes = Path(vault_path).read_bytes()
    assert raw["result"]["current_state"]["statement"].encode("utf-8") not in raw_bytes

    restored = saved_analysis_from_payload(raw)
    assert restored.result.analysis_status == bridge.analysis.analysis_status
    assert restored.question == "what changed overnight?"
    assert restored.evidence_snapshot.provider_id == "fake-provider-v1"


def test_restore_after_lock_and_unlock_in_same_bridge(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    original_cards = analyze_resp["data"]["citation_cards"]
    original_status = bridge.analysis.analysis_status
    original_question = bridge.last_question

    bridge.handle({"command": "lock_vault"})
    assert bridge.analysis is None and bridge.snapshot is None

    bridge.provider = _FailIfCalledProvider()
    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True

    assert bridge.analysis is not None
    assert bridge.analysis.analysis_status == original_status
    assert bridge.last_question == original_question

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["has_analysis"] is True
    assert state["retained_analysis_status"] == RETAINED_ANALYSIS_VALID
    assert state["citation_cards"] == original_cards


def test_restore_in_new_bridge_instance_without_provider_call(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    original_cards = analyze_resp["data"]["citation_cards"]
    original_status = bridge.analysis.analysis_status
    del bridge

    recovered = Bridge(provider=_FailIfCalledProvider())
    unlock_resp = recovered.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True

    assert recovered.analysis is not None
    assert recovered.analysis.analysis_status == original_status
    assert recovered.last_question == "what changed overnight?"

    state = recovered.handle({"command": "get_workspace_state"})["data"]
    assert state["has_analysis"] is True
    assert state["citation_cards"] == original_cards


def test_complete_encrypted_round_trip_verified_by_new_vault_instance(tmp_path: Path):
    """Proves persistence, not surviving Python object memory: a brand new Vault
    object reads the encrypted file directly, independent of the Bridge's cache."""
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "analyze_project", "question": "q"})
    original_status = bridge.analysis.analysis_status

    fresh_vault = Vault(Path(vault_path))
    fresh_vault.unlock("secret")
    try:
        saved_analyses = fresh_vault.payload["saved_analyses"]
        assert len(saved_analyses) == 1
        restored = saved_analysis_from_payload(saved_analyses[-1])
        assert restored.result.analysis_status == original_status
    finally:
        fresh_vault.lock()


def test_transactional_write_failure_preserves_previous_state(tmp_path: Path, monkeypatch):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    assert bridge.handle({"command": "analyze_project", "question": "first"})["ok"] is True

    before_bytes = Path(vault_path).read_bytes()
    before_count = len(bridge.vault.payload["saved_analyses"])
    before_analysis, before_snapshot, before_question = bridge.analysis, bridge.snapshot, bridge.last_question

    import continuity_ai.vault as vault_module
    original_write = vault_module._write
    monkeypatch.setattr(vault_module, "_write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated disk failure")))

    resp = bridge.handle({"command": "analyze_project", "question": "second"})
    assert resp["ok"] is False

    assert Path(vault_path).read_bytes() == before_bytes
    assert len(bridge.vault.payload["saved_analyses"]) == before_count
    assert bridge.analysis is before_analysis
    assert bridge.snapshot is before_snapshot
    assert bridge.last_question == before_question

    monkeypatch.setattr(vault_module, "_write", original_write)
    reopened = Bridge(FakeAuroraProvider())
    unlock_resp = reopened.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True
    assert len(reopened.vault.payload["saved_analyses"]) == before_count
    assert reopened.last_question == "first"


def test_transactional_encryption_failure_preserves_previous_state(tmp_path: Path, monkeypatch):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    assert bridge.handle({"command": "analyze_project", "question": "first"})["ok"] is True

    before_bytes = Path(vault_path).read_bytes()
    before_count = len(bridge.vault.payload["saved_analyses"])

    import continuity_ai.vault as vault_module
    monkeypatch.setattr(vault_module, "_encrypt", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated encryption failure")))

    resp = bridge.handle({"command": "analyze_project", "question": "second"})
    assert resp["ok"] is False
    assert Path(vault_path).read_bytes() == before_bytes
    assert len(bridge.vault.payload["saved_analyses"]) == before_count


def test_transactional_self_check_validation_failure_preserves_previous_state(tmp_path: Path, monkeypatch):
    """The candidate unit is serialized and re-validated before any encrypted write
    is attempted (Phase 10 step 3); a failure there must also leave everything intact."""
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    assert bridge.handle({"command": "analyze_project", "question": "first"})["ok"] is True

    before_bytes = Path(vault_path).read_bytes()
    before_count = len(bridge.vault.payload["saved_analyses"])

    import continuity_ai.vault as vault_module
    monkeypatch.setattr(vault_module, "saved_analysis_from_payload", lambda *a, **k: (_ for _ in ()).throw(InvalidSavedAnalysisError()))

    resp = bridge.handle({"command": "analyze_project", "question": "second"})
    assert resp["ok"] is False
    assert Path(vault_path).read_bytes() == before_bytes
    assert len(bridge.vault.payload["saved_analyses"]) == before_count


def test_cross_vault_leakage_prevented_even_with_equal_evidence(tmp_path: Path):
    root_a = tmp_path / "a"
    generate_project_aurora_fixture(root_a)
    artifact_root_a = str(root_a / "fixtures/project_aurora/generated/artifacts")
    vault_a_path = str(tmp_path / "vault_a.bin")
    vault_b_path = str(tmp_path / "vault_b.bin")

    setup = Vault(Path(vault_b_path))
    setup.initialize("Owner B", "secret-b")
    setup.lock()

    bridge = Bridge(provider=FakeAuroraProvider())
    bridge.handle({"command": "initialize_vault", "path": vault_a_path, "password": "secret-a", "owner_name": "Owner A"})
    bridge.handle({"command": "load_project", "artifact_root": artifact_root_a})
    assert bridge.handle({"command": "analyze_project", "question": "vault a question"})["ok"] is True
    records_before_switch = bridge.records

    unlock_resp = bridge.handle({"command": "unlock_vault", "path": vault_b_path, "password": "secret-b"})
    assert unlock_resp["ok"] is True

    # Vault B is empty and contributes no attestations, so the composed evidence
    # tuple is trivially equal to vault A's -- equality must never stand in for identity.
    assert bridge.records == records_before_switch
    assert bridge.analysis is None
    assert bridge.snapshot is None
    assert bridge.last_question is None

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["has_analysis"] is False
    assert state["retained_analysis_status"] == RETAINED_ANALYSIS_NONE


def test_analyze_project_response_contract_unchanged(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    resp = bridge.handle({"command": "analyze_project", "question": "what changed overnight?"})
    assert resp["ok"] is True
    data = resp["data"]
    assert set(data) == {
        "analysis_status", "continuity_break_kind", "current_state", "semantic_annotations",
        "continuity_break", "next_action", "project_report", "citation_cards",
        "analysis_id", "created_at", "prompt_version", "schema_version", "provider_id",
    }
    assert data["analysis_status"] == "break_found"
    assert data["citation_cards"]


def test_blank_question_is_rejected_before_persisting_or_calling_provider(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path, provider=_FailIfCalledProvider())
    resp = bridge.handle({"command": "analyze_project", "question": "   "})
    assert resp["ok"] is False
    assert bridge.vault.payload["saved_analyses"] == []


# ---------------------------------------------------------------------------
# F-11: an analysis produced without an unlocked vault is real in-memory state,
# but it was never retained, and must never be reported as "valid".
# ---------------------------------------------------------------------------

def test_unpersisted_analysis_is_not_reported_as_retained(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    bridge.handle({"command": "lock_vault"})
    assert bridge.records  # artifact evidence remains available while locked

    resp = bridge.handle({"command": "analyze_project", "question": "q"})
    assert resp["ok"] is True

    assert bridge.analysis is not None
    assert bridge.retained_analysis_status == RETAINED_ANALYSIS_NONE

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    assert state["has_analysis"] is True
    assert state["retained_analysis_status"] == RETAINED_ANALYSIS_NONE

    direct = Vault(Path(vault_path))
    direct.unlock("secret")
    try:
        assert direct.payload["saved_analyses"] == []
    finally:
        direct.lock()


def test_restored_result_with_unknown_span_is_rejected():
    raw = copy.deepcopy(_valid_propagation_payload())
    # The snapshot itself stays fully well-formed; only the result now cites a
    # span that does not exist anywhere in the validated snapshot.
    raw["result"]["current_state"]["span_ids"] = ["EV-A:L999-DOES-NOT-EXIST"]
    _assert_rejected(raw)


def test_single_source_change_does_not_mark_unrelated_citations_changed(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    analyze_resp = bridge.handle({"command": "analyze_project", "question": "q"})
    original_cards = analyze_resp["data"]["citation_cards"]
    assert len({c["evidence_id"] for c in original_cards}) > 1

    changed_evidence_id = original_cards[0]["evidence_id"]
    bridge.records = tuple(
        ReasoningEvidence(r.evidence_id, r.source_type, r.author_or_actor, r.timestamp, r.title, r.content + " CHANGED", r.provenance, r.uri, r.artifact_sha256)
        if r.evidence_id == changed_evidence_id else r
        for r in bridge.records
    )
    bridge.spans = build_spans(bridge.records)

    state = bridge.handle({"command": "get_workspace_state"})["data"]
    original_by_span = {c["span_id"]: c for c in original_cards}
    for card in state["citation_cards"]:
        original = original_by_span[card["span_id"]]
        assert card["exact_text"] == original["exact_text"]
        if card["evidence_id"] == changed_evidence_id:
            assert card["source_status"] == "source_changed_since_analysis"
        else:
            assert card["source_status"] == "snapshot"


def test_semantically_invalid_newest_entry_is_invalid_after_reopen(tmp_path: Path):
    bridge, vault_path, artifact_root = _init_and_load(tmp_path)
    assert bridge.handle({"command": "analyze_project", "question": "first"})["ok"] is True
    assert len(bridge.vault.payload["saved_analyses"]) == 1

    # Structurally well-formed (valid snapshot), but semantically invalid per the
    # canonical validator: incomplete annotation coverage over the evidence set.
    records, spans = _propagation_world()
    valid = _build_saved_analysis(records, spans, _propagation_candidate(records, spans), question="second")
    broken_raw = copy.deepcopy(saved_analysis_to_payload(valid))
    broken_raw["result"]["semantic_annotations"] = broken_raw["result"]["semantic_annotations"][:1]

    bridge.vault.payload["saved_analyses"].append(broken_raw)
    bridge.vault.persist()

    recovered = Bridge(provider=_FailIfCalledProvider())
    unlock_resp = recovered.handle({"command": "unlock_vault", "path": vault_path, "password": "secret"})
    assert unlock_resp["ok"] is True
    recovered.handle({"command": "load_project", "artifact_root": artifact_root})

    state = recovered.handle({"command": "get_workspace_state"})["data"]
    assert state["retained_analysis_status"] == RETAINED_ANALYSIS_INVALID
    assert state["has_analysis"] is False
    assert "citation_cards" not in state
    assert "analysis_status" not in state
    assert state["evidence_count"] > 0
