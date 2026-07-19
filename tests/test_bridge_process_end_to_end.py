"""Real subprocess acceptance test for the Bridge NDJSON process contract.

Proves the full path: parent process -> `python -m continuity_ai.bridge_main` ->
UTF-8 NDJSON stdin/stdout -> initialize vault -> load Project Aurora -> analyze
-> persist -> lock -> terminate the process -> start a new process -> unlock ->
restore the retained analysis without sending analyze_project -> load current
evidence -> detect a legitimate changed source -> preserve the historical
quotation. See docs/BRIDGE_PROCESS_CONTRACT_v0.1.md for the normative contract
this test verifies.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from continuity_ai.aurora_fixture import generate_project_aurora_fixture

_ARTIFACT_ROOT = "fixtures/project_aurora/generated/artifacts"
_MANIFEST_NAME = "evidence_manifest.json"
_CREW_BRIEFING_URI = "notes/crew_briefing.md"
_CITATION_CARD_FIELDS = {
    "evidence_id", "span_id", "exact_text", "title",
    "author_or_actor", "timestamp", "source_type", "provenance", "source_status",
}


class _BridgeProcess:
    """One persistent `bridge_main` child process, driven one NDJSON line at a time."""

    def __init__(self, provider: str = "deterministic_offline") -> None:
        env = os.environ.copy()
        env["CONTINUITY_REASONING_PROVIDER"] = provider
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "continuity_ai.bridge_main"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    def __enter__(self) -> "_BridgeProcess":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def send(self, command: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
        assert self._proc.stdin is not None and self._proc.stdout is not None
        line = json.dumps(command, ensure_ascii=False).encode("utf-8") + b"\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

        # A plain blocking readline() would hang forever on a protocol deadlock;
        # bound it with a timeout so a stuck process fails the test instead.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._proc.stdout.readline)
            try:
                raw = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise AssertionError(
                    f"Bridge process did not respond to command {command.get('command')!r} "
                    f"within {timeout}s (possible protocol deadlock)."
                )

        assert raw != b"", "Bridge process closed stdout before sending a response line."
        response = json.loads(raw.decode("utf-8"))
        assert isinstance(response, dict), "Bridge response line must decode to a JSON object."
        return response

    def close(self, timeout: float = 10.0) -> None:
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=timeout)


def _assert_ok(response: dict[str, Any], command: str) -> dict[str, Any]:
    assert response["command"] == command
    assert response["ok"] is True, response.get("error")
    return response["data"]


def _assert_controlled_failure(response: dict[str, Any], forbidden: tuple[str, ...]) -> dict[str, Any]:
    assert response["ok"] is False
    error = response["error"]
    assert set(error) == {"code", "message", "object_id"}
    assert error["object_id"] is None
    serialized = json.dumps(response, ensure_ascii=False)
    for phrase in forbidden:
        assert phrase not in serialized
    return error


def _read_manifest(artifact_root: Path) -> dict[str, Any]:
    return json.loads((artifact_root / _MANIFEST_NAME).read_text("utf-8"))


def _write_manifest(artifact_root: Path, manifest: dict[str, Any]) -> None:
    (artifact_root / _MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _manifest_entry_for(manifest: dict[str, Any], uri: str) -> dict[str, Any]:
    for entry in manifest["artifacts"]:
        if entry["uri"] == uri:
            return entry
    raise AssertionError(f"No manifest entry found for uri={uri!r}")


def test_bridge_process_end_to_end_restart_and_source_change(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / _ARTIFACT_ROOT
    vault_path = tmp_path / "vault.bin"
    test_password = "correct horse battery staple"  # local to this test process only

    # ---- Process A: initialize, load, analyze, persist, lock ----
    with _BridgeProcess() as process_a:
        init_data = _assert_ok(
            process_a.send({
                "command": "initialize_vault",
                "path": str(vault_path),
                "password": test_password,
                "owner_name": "Paweł",
            }),
            "initialize_vault",
        )
        assert isinstance(init_data["session_id"], str) and init_data["session_id"]

        load_data = _assert_ok(
            process_a.send({"command": "load_project", "artifact_root": str(artifact_root)}),
            "load_project",
        )
        assert load_data["artifact_evidence_count"] == 5
        assert load_data["evidence_count"] == 5
        assert load_data["project"] == "Project Aurora"
        assert len(load_data["evidence_records"]) == 5
        for record in load_data["evidence_records"]:
            assert set(record) == {
                "source_id", "evidence_id", "author", "timestamp",
                "source_type", "title", "uri", "artifact_sha256", "content",
            }

        state_before = _assert_ok(process_a.send({"command": "get_workspace_state"}), "get_workspace_state")
        assert state_before["vault_unlocked"] is True
        assert state_before["artifact_evidence_count"] == 5
        assert state_before["evidence_count"] == 5
        assert state_before["project"] == "Project Aurora"
        assert len(state_before["evidence_records"]) == 5
        assert state_before["has_analysis"] is False
        assert state_before["retained_analysis_status"] == "none"
        assert state_before["project_report"] is None

        question = "Gdzie jest Project Aurora, jaki ciąg decyzji się urwał i co trzeba zrobić następnie?"
        analyze_data = _assert_ok(
            process_a.send({"command": "analyze_project", "question": question}),
            "analyze_project",
        )
        assert analyze_data["analysis_status"] == "no_material_break_found"
        assert analyze_data["continuity_break_kind"] is None
        assert analyze_data["current_state"]["statement"].strip()
        assert analyze_data["continuity_break"] is None
        assert analyze_data["next_action"] is None

        project_report = analyze_data["project_report"]
        assert [s["key"] for s in project_report["sections"]] == [
            "decision", "budget", "schedule", "operations", "readiness", "casting", "agreements",
        ]
        assert project_report["summary"]["statement"].strip()
        assert project_report["summary"]["span_ids"]
        assert all(s["status"] == "evidence_gap" for s in project_report["sections"])

        manifest = _read_manifest(artifact_root)
        all_evidence_ids = {entry["evidence_id"] for entry in manifest["artifacts"]}
        assert len(all_evidence_ids) == 5
        annotated_ids = {a["evidence_id"] for a in analyze_data["semantic_annotations"]}
        assert annotated_ids == all_evidence_ids
        assert all(
            annotation["propagation_role"] == "none"
            for annotation in analyze_data["semantic_annotations"]
        )

        cards_after_analysis = analyze_data["citation_cards"]
        assert cards_after_analysis
        for card in cards_after_analysis:
            assert set(card) == _CITATION_CARD_FIELDS
            assert card["exact_text"].strip()
            assert card["source_status"] == "snapshot"

        captured_current_state = analyze_data["current_state"]
        captured_continuity_break = analyze_data["continuity_break"]
        captured_next_action = analyze_data["next_action"]
        captured_project_report = project_report
        captured_cards = cards_after_analysis

        state_after_analysis = _assert_ok(
            process_a.send({"command": "get_workspace_state"}), "get_workspace_state"
        )
        assert state_after_analysis["vault_unlocked"] is True
        assert state_after_analysis["has_analysis"] is True
        assert state_after_analysis["retained_analysis_status"] == "valid"
        assert state_after_analysis["project"] == "Project Aurora"
        assert state_after_analysis["current_state"] == captured_current_state
        assert state_after_analysis["continuity_break"] == captured_continuity_break
        assert state_after_analysis["next_action"] == captured_next_action
        assert state_after_analysis["project_report"] == captured_project_report
        assert state_after_analysis["citation_cards"] == captured_cards

        lock_data = _assert_ok(process_a.send({"command": "lock_vault"}), "lock_vault")
        assert lock_data == {"locked": True}

        state_locked = _assert_ok(process_a.send({"command": "get_workspace_state"}), "get_workspace_state")
        assert state_locked["vault_unlocked"] is False
        assert state_locked["owner_display_name"] is None
        assert state_locked["has_analysis"] is False
        assert state_locked["retained_analysis_status"] == "none"
        assert state_locked["project_report"] is None
        assert "citation_cards" not in state_locked
        assert "analysis_status" not in state_locked

    # ---- Process B: restart, restore without analyzing, then reload evidence ----
    with _BridgeProcess() as process_b:
        unlock_data = _assert_ok(
            process_b.send({"command": "unlock_vault", "path": str(vault_path), "password": test_password}),
            "unlock_vault",
        )
        assert isinstance(unlock_data["session_id"], str) and unlock_data["session_id"]

        state_restored = _assert_ok(process_b.send({"command": "get_workspace_state"}), "get_workspace_state")
        assert state_restored["vault_unlocked"] is True
        assert state_restored["owner_display_name"] == "Paweł"
        assert state_restored["has_analysis"] is True
        assert state_restored["retained_analysis_status"] == "valid"
        assert state_restored["artifact_evidence_count"] == 0
        assert state_restored["project"] == "Project Aurora"
        assert state_restored["current_state"] == captured_current_state
        assert state_restored["continuity_break"] == captured_continuity_break
        assert state_restored["next_action"] == captured_next_action
        assert state_restored["project_report"] == captured_project_report
        assert state_restored["citation_cards"] == captured_cards
        for card in state_restored["citation_cards"]:
            assert card["source_status"] == "snapshot"

        reload_data = _assert_ok(
            process_b.send({"command": "load_project", "artifact_root": str(artifact_root)}),
            "load_project",
        )
        assert reload_data["artifact_evidence_count"] == 5
        assert reload_data["evidence_count"] == 5
        assert reload_data["project"] == "Project Aurora"
        assert len(reload_data["evidence_records"]) == 5

        state_after_reload = _assert_ok(
            process_b.send({"command": "get_workspace_state"}), "get_workspace_state"
        )
        assert state_after_reload["artifact_evidence_count"] == 5
        assert state_after_reload["evidence_count"] == 5
        assert state_after_reload["has_analysis"] is True
        assert state_after_reload["retained_analysis_status"] == "valid"
        assert state_after_reload["project"] == "Project Aurora"
        assert state_after_reload["project_report"] == captured_project_report
        for card in state_after_reload["citation_cards"]:
            original = next(c for c in captured_cards if c["span_id"] == card["span_id"])
            assert card["exact_text"] == original["exact_text"]
            assert card["source_status"] == "snapshot"

        # ---- Unverified file mutation must fail safely ----
        briefing_path = artifact_root / _CREW_BRIEFING_URI
        original_bytes = briefing_path.read_bytes()
        mutated_bytes = original_bytes + b"\nUnverified addition that the manifest does not yet describe.\n"
        briefing_path.write_bytes(mutated_bytes)

        bad_reload_response = process_b.send(
            {"command": "load_project", "artifact_root": str(artifact_root)}
        )
        _assert_controlled_failure(
            bad_reload_response,
            forbidden=("Traceback", "Exception", test_password, str(vault_path), str(artifact_root)),
        )

        state_after_bad_reload = _assert_ok(
            process_b.send({"command": "get_workspace_state"}), "get_workspace_state"
        )
        assert state_after_bad_reload["has_analysis"] is True
        assert state_after_bad_reload["retained_analysis_status"] == "valid"
        assert state_after_bad_reload["citation_cards"] == captured_cards

        # ---- Legitimate new source version ----
        manifest = _read_manifest(artifact_root)
        crew_entry = _manifest_entry_for(manifest, _CREW_BRIEFING_URI)
        crew_evidence_id = crew_entry["evidence_id"]
        crew_entry["sha256"] = hashlib.sha256(mutated_bytes).hexdigest()
        _write_manifest(artifact_root, manifest)

        good_reload_data = _assert_ok(
            process_b.send({"command": "load_project", "artifact_root": str(artifact_root)}),
            "load_project",
        )
        assert good_reload_data["artifact_evidence_count"] == 5
        assert good_reload_data["evidence_count"] == 5

        final_state = _assert_ok(process_b.send({"command": "get_workspace_state"}), "get_workspace_state")
        assert final_state["has_analysis"] is True
        assert final_state["retained_analysis_status"] == "valid"

        changed_seen = False
        for card in final_state["citation_cards"]:
            original = next(c for c in captured_cards if c["span_id"] == card["span_id"])
            assert card["exact_text"] == original["exact_text"]
            assert "Unverified addition" not in card["exact_text"]
            if card["evidence_id"] == crew_evidence_id:
                assert card["source_status"] == "source_changed_since_analysis"
                changed_seen = True
            else:
                assert card["source_status"] == "snapshot"
        assert changed_seen, "expected at least one citation card for the changed crew-briefing evidence"


def test_bridge_process_wrong_password_fails_safely_and_process_stays_usable(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    artifact_root = tmp_path / _ARTIFACT_ROOT
    vault_path = tmp_path / "vault.bin"
    test_password = "another local test password"

    with _BridgeProcess() as process:
        _assert_ok(
            process.send({
                "command": "initialize_vault",
                "path": str(vault_path),
                "password": test_password,
                "owner_name": "Paweł",
            }),
            "initialize_vault",
        )
        _assert_ok(
            process.send({"command": "load_project", "artifact_root": str(artifact_root)}),
            "load_project",
        )
        _assert_ok(process.send({"command": "lock_vault"}), "lock_vault")

        wrong_unlock = process.send(
            {"command": "unlock_vault", "path": str(vault_path), "password": "definitely-wrong"}
        )
        error = _assert_controlled_failure(
            wrong_unlock,
            forbidden=(
                "Traceback", "Exception", "VaultAuthError",
                test_password, "definitely-wrong", str(vault_path),
            ),
        )
        assert error["code"] == "vault_auth_failed"

        recovered_state = _assert_ok(process.send({"command": "get_workspace_state"}), "get_workspace_state")
        assert recovered_state["vault_unlocked"] is False
