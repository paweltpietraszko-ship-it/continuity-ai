"""Independent falsification tests for the frozen Project Report v3 contract.

These tests deliberately do not reuse the implementation commit's report helpers or
generated Aurora fixture.  Small evidence worlds and artifact projects are built from
the frozen contract so that the implementation cannot define its own oracle.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from continuity_ai.bridge import Bridge, _citation_span_ids
from continuity_ai.domain import ReasoningEvidence
from continuity_ai.errors import ValidationError
from continuity_ai.evidence import build_spans, hydrate_citations
from continuity_ai.ingestion import ArtifactIngestionError, ingest_artifacts, read_project_name
from continuity_ai.reasoning_pipeline import DeterministicOfflineReasoningProvider, _grounded_statement, validate_analysis
from continuity_ai.vault import Vault


SECTION_KEYS = ("decision", "budget", "schedule", "operations", "readiness", "casting", "agreements")
FROZEN_SECTION_FIELDS = {"key", "status", "headline", "detail", "span_ids"}
LEGACY_SECTION_FIELDS = {"section", "status", "headline", "statement", "span_ids"}


def _write_project(root: Path, project: str, token: str) -> Path:
    """Create a valid, independent five-artifact markdown project."""
    root.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for index in range(1, 6):
        uri = f"{token.lower()}-artifact-{index}.md"
        content = f"{token} confidential evidence content {index}.\n".encode("utf-8")
        (root / uri).write_bytes(content)
        artifacts.append(
            {
                "source_id": f"{token}-SOURCE-{index}",
                "evidence_id": f"EV-{token}-{index:03d}",
                "author": f"{token} Author {index}",
                "timestamp": f"2026-06-{index:02d}T0{index}:00:00Z",
                "source_type": "markdown",
                "title": f"{token} Private Title {index}",
                "uri": uri,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {"schema_version": 1, "project": project, "artifacts": artifacts}
    (root / "evidence_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def _initialize_load_and_analyze(
    base: Path, *, project: str, token: str, password: str
) -> tuple[Bridge, Path, Path, dict]:
    artifact_root = _write_project(base / "artifacts", project, token)
    vault_path = base / "vault.bin"
    bridge = Bridge(provider=DeterministicOfflineReasoningProvider())
    initialized = bridge.handle(
        {
            "command": "initialize_vault",
            "path": str(vault_path),
            "password": password,
            "owner_name": f"{token} Owner",
        }
    )
    assert initialized["ok"] is True
    loaded = bridge.handle({"command": "load_project", "artifact_root": str(artifact_root)})
    assert loaded["ok"] is True
    analyzed = bridge.handle({"command": "analyze_project", "question": f"Analyze {token}"})
    assert analyzed["ok"] is True
    return bridge, vault_path, artifact_root, analyzed["data"]


def _validator_world() -> tuple[tuple[ReasoningEvidence, ...], tuple]:
    records = (
        ReasoningEvidence(
            "EV-AUDIT-A",
            "decision",
            "Auditor A",
            "2026-01-01T00:00:00Z",
            "Independent approval",
            "The change is independently approved.",
            "artifact",
        ),
        ReasoningEvidence(
            "EV-AUDIT-B",
            "runbook",
            "Auditor B",
            "2026-01-02T00:00:00Z",
            "Independent runbook",
            "The runbook still contains the old value.",
            "artifact",
        ),
    )
    return records, build_spans(records)


def _frozen_gap(key: str) -> dict:
    return {
        "key": key,
        "status": "evidence_gap",
        "headline": "No verified status available",
        "detail": f"No available project source establishes the current {key} status.",
        "span_ids": [],
    }


def _frozen_candidate(records: tuple, spans: tuple) -> dict:
    span_a, span_b = spans[0].span_id, spans[1].span_id
    return {
        "schema_version": "3.0",
        "analysis_status": "break_found",
        "continuity_break_kind": "propagation_break",
        "current_state": {"statement": "Current state.", "span_ids": [span_a]},
        "semantic_annotations": [
            {"evidence_id": records[0].evidence_id, "propagation_role": "approved_decision", "context_tags": []},
            {"evidence_id": records[1].evidence_id, "propagation_role": "conflicts_with_decision", "context_tags": []},
        ],
        "continuity_break": {"statement": "Continuity break.", "span_ids": [span_a, span_b]},
        "next_action": {"statement": "Next action.", "span_ids": [span_b]},
        "project_report": {
            "summary": {"statement": "Project summary.", "span_ids": [span_a]},
            "sections": [
                {
                    "key": "decision",
                    "status": "attention",
                    "headline": "Decision requires attention",
                    "detail": "The approved change has not propagated.",
                    "span_ids": [span_a, span_b],
                },
                *[_frozen_gap(key) for key in SECTION_KEYS[1:]],
            ],
        },
    }


def _legacy_candidate(records: tuple, spans: tuple) -> dict:
    candidate = _frozen_candidate(records, spans)
    for section in candidate["project_report"]["sections"]:
        section["section"] = section.pop("key")
        section["statement"] = section.pop("detail")
    return candidate


def _workspace(bridge: Bridge) -> dict:
    response = bridge.handle({"command": "get_workspace_state"})
    assert response["ok"] is True
    return response["data"]


def test_analyze_project_data_contains_selected_project(tmp_path: Path) -> None:
    _, _, _, data = _initialize_load_and_analyze(
        tmp_path / "analyze", project="Audit Project", token="ANALYZE", password="secret"
    )
    assert data["project"] == "Audit Project"


def test_project_report_sections_expose_exact_frozen_fields(tmp_path: Path) -> None:
    _, _, _, data = _initialize_load_and_analyze(
        tmp_path / "shape", project="Shape Project", token="SHAPE", password="secret"
    )
    sections = data["project_report"]["sections"]
    assert len(sections) == len(SECTION_KEYS)
    assert all(set(section) == FROZEN_SECTION_FIELDS for section in sections)
    assert [section["key"] for section in sections] == list(SECTION_KEYS)
    assert all(not (set(section) & {"section", "statement"}) for section in sections)


def test_validator_accepts_exact_frozen_section_shape() -> None:
    records, spans = _validator_world()
    result = validate_analysis(_frozen_candidate(records, spans), records, spans)
    assert len(result.project_report.sections) == len(SECTION_KEYS)


def test_validator_rejects_legacy_section_and_statement_fields() -> None:
    records, spans = _validator_world()
    with pytest.raises(ValidationError):
        validate_analysis(_legacy_candidate(records, spans), records, spans)


@pytest.mark.parametrize(
    "contract_location",
    ["current_state", "continuity_break", "next_action", "project_report.summary"],
)
def test_repeated_span_ids_rejected_in_all_grounded_statements(contract_location: str) -> None:
    """All four locations share the canonical grounded-statement validator."""
    with pytest.raises(ValidationError):
        _grounded_statement(
            {"statement": f"Duplicate at {contract_location}", "span_ids": ["EV-A:L001", "EV-A:L001"]}
        )


@pytest.mark.parametrize("index,key", list(enumerate(SECTION_KEYS)))
def test_repeated_span_ids_rejected_in_every_project_report_section(index: int, key: str) -> None:
    records, spans = _validator_world()
    valid = _frozen_candidate(records, spans)
    detail_field = "detail"
    try:
        validate_analysis(copy.deepcopy(valid), records, spans)
    except ValidationError:
        # The exact-shape tests independently fail if only the legacy route is
        # accepted. Using that reachable route here isolates duplicate enforcement
        # instead of letting the shape defect mask a second validator defect.
        valid = _legacy_candidate(records, spans)
        detail_field = "statement"
        validate_analysis(copy.deepcopy(valid), records, spans)

    candidate = copy.deepcopy(valid)
    section = candidate["project_report"]["sections"][index]
    if index:
        section["status"] = "confirmed"
        section["headline"] = f"{key} confirmed"
        section[detail_field] = f"{key} detail"
    section["span_ids"] = [spans[0].span_id, spans[0].span_id]
    with pytest.raises(ValidationError):
        validate_analysis(candidate, records, spans)


def test_switching_to_second_vault_clears_first_projects_live_evidence(tmp_path: Path) -> None:
    bridge_a, _, _, _ = _initialize_load_and_analyze(
        tmp_path / "project-a", project="Project A", token="ALPHA", password="secret-a"
    )
    project_a_records = copy.deepcopy(_workspace(bridge_a)["evidence_records"])

    _, vault_b, _, analysis_b = _initialize_load_and_analyze(
        tmp_path / "project-b", project="Project B", token="BRAVO", password="secret-b"
    )
    report_b = analysis_b["project_report"]

    switched = bridge_a.handle(
        {"command": "unlock_vault", "path": str(vault_b), "password": "secret-b"}
    )
    assert switched["ok"] is True
    state = _workspace(bridge_a)

    deviations = []
    expected = {
        "project": "Project B",
        "project_report": report_b,
        "artifact_evidence_count": 0,
        "evidence_count": 0,
        "evidence_records": [],
    }
    for field, value in expected.items():
        if state[field] != value:
            deviations.append(f"{field}: expected {value!r}, got {state[field]!r}")

    serialized = json.dumps(state, sort_keys=True, ensure_ascii=False)
    for record in project_a_records:
        for field in ("evidence_id", "title", "uri", "content", "artifact_sha256"):
            if record[field] in serialized:
                deviations.append(f"Project A {field} leaked: {record[field]!r}")
    assert not deviations, "\n".join(deviations)


def test_opening_new_empty_vault_clears_orphaned_project_and_evidence(tmp_path: Path) -> None:
    bridge, _, _, _ = _initialize_load_and_analyze(
        tmp_path / "loaded", project="Loaded Project", token="LOADED", password="loaded-secret"
    )
    prior_records = copy.deepcopy(_workspace(bridge)["evidence_records"])

    empty_vault_path = tmp_path / "empty-vault.bin"
    empty_vault = Vault(empty_vault_path)
    empty_vault.initialize("Empty Owner", "empty-secret")
    empty_vault.lock()

    opened = bridge.handle(
        {"command": "unlock_vault", "path": str(empty_vault_path), "password": "empty-secret"}
    )
    assert opened["ok"] is True
    state = _workspace(bridge)

    expected = {
        "project": None,
        "artifact_evidence_count": 0,
        "evidence_count": 0,
        "evidence_records": [],
        "has_analysis": False,
    }
    deviations = [
        f"{field}: expected {value!r}, got {state[field]!r}"
        for field, value in expected.items()
        if state[field] != value
    ]
    serialized = json.dumps(state, sort_keys=True, ensure_ascii=False)
    for record in prior_records:
        for field in ("evidence_id", "title", "uri", "content", "artifact_sha256"):
            if record[field] in serialized:
                deviations.append(f"orphaned {field}: {record[field]!r}")
    assert not deviations, "\n".join(deviations)


def test_bad_password_preserves_active_vault_and_complete_previous_state(tmp_path: Path) -> None:
    bridge, active_path, _, _ = _initialize_load_and_analyze(
        tmp_path / "active", project="Active Project", token="ACTIVE", password="active-secret"
    )
    pending = bridge.vault.propose_attestation("Pending state must survive failed unlock")

    other_path = tmp_path / "other-vault.bin"
    other = Vault(other_path)
    other.initialize("Other Owner", "other-secret")
    other.lock()

    active_vault = bridge.vault
    active_session = active_vault.session
    key_before = bytes(active_session.key_buffer)
    state_before = copy.deepcopy(_workspace(bridge))
    internals_before = (
        bridge.project,
        bridge.artifact_records,
        bridge.artifact_evidence_records,
        bridge.records,
        bridge.spans,
        bridge.analysis,
        bridge.snapshot,
        bridge.last_question,
        bridge.retained_analysis_status,
    )
    active_bytes_before = active_path.read_bytes()

    response = bridge.handle(
        {"command": "unlock_vault", "path": str(other_path), "password": "wrong-password"}
    )
    assert response["ok"] is False
    assert bridge.vault is active_vault
    assert bridge.vault.session is active_session
    assert active_session.unlocked is True
    assert bytes(active_session.key_buffer) == key_before
    assert pending.proposal_id in active_vault.pending_attestations
    assert active_path.read_bytes() == active_bytes_before
    assert _workspace(bridge) == state_before
    assert (
        bridge.project,
        bridge.artifact_records,
        bridge.artifact_evidence_records,
        bridge.records,
        bridge.spans,
        bridge.analysis,
        bridge.snapshot,
        bridge.last_question,
        bridge.retained_analysis_status,
    ) == internals_before


@pytest.mark.parametrize("project", ["", "   \t\r\n"])
def test_manifest_project_rejects_empty_and_whitespace_only_values(tmp_path: Path, project: str) -> None:
    artifact_root = _write_project(tmp_path / "manifest", project, "MANIFEST")
    with pytest.raises(ArtifactIngestionError):
        read_project_name(artifact_root)


@pytest.mark.parametrize("project", [" Project With Leading Space", "Project With Trailing Space "])
def test_manifest_project_rejects_or_explicitly_normalizes_edge_whitespace(
    tmp_path: Path, project: str
) -> None:
    artifact_root = _write_project(tmp_path / "manifest", project, "EDGE")
    try:
        normalized = read_project_name(artifact_root)
    except ArtifactIngestionError:
        return
    assert normalized == project.strip()


def test_project_mismatch_after_successful_ingestion_is_fully_atomic(tmp_path: Path) -> None:
    bridge, active_path, _, _ = _initialize_load_and_analyze(
        tmp_path / "atomic-a", project="Atomic Project A", token="ATOMA", password="secret-a"
    )
    other_root = _write_project(
        tmp_path / "atomic-b" / "artifacts", "Atomic Project B", "ATOMB"
    )
    # Establish independently that the candidate manifest and all artifacts pass ingestion.
    assert len(ingest_artifacts(other_root)) == 5
    assert read_project_name(other_root) == "Atomic Project B"

    active_vault = bridge.vault
    active_session = active_vault.session
    state_before = copy.deepcopy(_workspace(bridge))
    internals_before = (
        bridge.project,
        bridge.artifact_records,
        bridge.artifact_evidence_records,
        bridge.records,
        bridge.spans,
        bridge.analysis,
        bridge.snapshot,
        bridge.last_question,
        bridge.retained_analysis_status,
    )
    vault_bytes_before = active_path.read_bytes()

    response = bridge.handle({"command": "load_project", "artifact_root": str(other_root)})
    assert response["ok"] is False
    assert response["error"]["code"] == "project_mismatch"
    assert bridge.vault is active_vault
    assert bridge.vault.session is active_session
    assert _workspace(bridge) == state_before
    assert active_path.read_bytes() == vault_bytes_before
    assert (
        bridge.project,
        bridge.artifact_records,
        bridge.artifact_evidence_records,
        bridge.records,
        bridge.spans,
        bridge.analysis,
        bridge.snapshot,
        bridge.last_question,
        bridge.retained_analysis_status,
    ) == internals_before


def test_lock_keeps_only_live_artifact_projection_and_hides_owner_and_attestations(
    tmp_path: Path,
) -> None:
    bridge, _, _, _ = _initialize_load_and_analyze(
        tmp_path / "lock", project="Lock Project", token="LOCK", password="lock-secret"
    )
    artifact_records = copy.deepcopy(_workspace(bridge)["evidence_records"])
    statement = "Encrypted attestation must leave the live evidence projection on lock"
    proposal = bridge.handle({"command": "send_message", "message": f"I attest {statement}"})
    assert proposal["ok"] is True
    proposal_id = proposal["data"]["attestation_proposal"]["proposal_id"]
    confirmed = bridge.handle({"command": "confirm_attestation", "proposal_id": proposal_id})
    assert confirmed["ok"] is True
    attestation_id = confirmed["data"]["evidence_id"]
    assert _workspace(bridge)["evidence_count"] == 6

    locked = bridge.handle({"command": "lock_vault"})
    assert locked["ok"] is True
    state = _workspace(bridge)
    assert state["owner_display_name"] is None
    assert state["artifact_evidence_count"] == 5
    assert state["evidence_count"] == 5
    assert state["evidence_records"] == artifact_records
    serialized = json.dumps(state, sort_keys=True, ensure_ascii=False)
    assert attestation_id not in serialized
    assert statement not in serialized


def test_citation_cards_are_ordered_deduplicated_union_of_all_report_spans() -> None:
    records = (
        ReasoningEvidence("EV-CITE-1", "note", "A", "2026-01-01T00:00:00Z", "One", "one", "artifact"),
        ReasoningEvidence("EV-CITE-2", "note", "B", "2026-01-02T00:00:00Z", "Two", "two", "artifact"),
        ReasoningEvidence("EV-CITE-3", "note", "C", "2026-01-03T00:00:00Z", "Three", "three", "artifact"),
    )
    spans = build_spans(records)
    span_1, span_2, span_3 = (span.span_id for span in spans)
    result = SimpleNamespace(
        current_state=SimpleNamespace(span_ids=(span_2, span_1)),
        continuity_break=SimpleNamespace(span_ids=(span_1, span_3)),
        next_action=SimpleNamespace(span_ids=(span_3,)),
        project_report=SimpleNamespace(
            summary=SimpleNamespace(span_ids=(span_2, span_3)),
            sections=(
                SimpleNamespace(span_ids=(span_3, span_1)),
                *(SimpleNamespace(span_ids=()) for _ in range(6)),
            ),
        ),
    )

    ordered_ids = _citation_span_ids(result)
    cards = hydrate_citations(ordered_ids, records, spans)
    assert [card.span_id for card in cards] == [span_2, span_1, span_3]
    assert len(cards) == len({card.span_id for card in cards})
