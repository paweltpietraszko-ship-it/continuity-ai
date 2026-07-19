from __future__ import annotations

import json
from pathlib import Path

import pytest

from continuity_ai.codex_process import workspace_fingerprint
from continuity_ai.codex_session import (
    CodexOperationRequest,
    CodexSessionController,
    JsonSessionStore,
)


@pytest.mark.live_network
def test_real_local_codex_session_smoke_and_supported_resume(tmp_path: Path) -> None:
    workspace = tmp_path / "synthetic-input"
    workspace.mkdir()
    (workspace / "fact.txt").write_text(
        "marker=synthetic-local-codex-smoke\n",
        encoding="utf-8",
    )
    workspace = workspace.resolve()
    store = JsonSessionStore(tmp_path / "controller-state.json")
    controller = CodexSessionController.with_local_codex(store)
    created = controller.create_session(workspace)
    assert created.codex_executable == str(
        controller.process_adapter.resolved_executable
    )
    before = workspace_fingerprint(workspace)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {
            "answer": {
                "type": "string",
                "enum": ["synthetic-local-codex-smoke"],
            }
        },
    }

    first = controller.start_investigation(
        created.controller_session_id,
        workspace,
        CodexOperationRequest(
            "Read fact.txt inside the current workspace. Return its marker value as answer.",
            schema,
            120,
        ),
    )

    assert first.structured_output == {"answer": "synthetic-local-codex-smoke"}
    assert first.receipt.succeeded
    assert first.receipt.resolved_executable == created.codex_executable
    assert first.receipt.workspace_root == str(workspace)
    assert first.receipt.sandbox_mode == "read-only"
    assert first.receipt.input_unchanged
    assert first.receipt.structured_output_valid
    assert workspace_fingerprint(workspace) == before
    assert not json.loads(store.path.read_text(encoding="utf-8")).get("prompt")

    if first.session.resume_supported:
        assert first.session.codex_session_id is not None
        resume_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {
                "answer": {"type": "string", "enum": ["resume-ok"]}
            },
        }
        resumed = controller.resume_session(
            first.session.controller_session_id,
            first.session.codex_session_id,
            workspace,
            CodexOperationRequest(
                "Return answer resume-ok. Do not modify any file.",
                resume_schema,
                120,
            ),
        )

        assert resumed.structured_output == {"answer": "resume-ok"}
        assert resumed.receipt.succeeded
        assert resumed.receipt.resume_attempted
        assert resumed.receipt.codex_session_id == first.session.codex_session_id
        assert resumed.receipt.workspace_root == first.receipt.workspace_root
        assert resumed.receipt.workspace_fingerprint_before == before
        assert resumed.receipt.workspace_fingerprint_after == before
        assert workspace_fingerprint(workspace) == before


@pytest.mark.live_network
def test_real_local_codex_reporting_resumes_same_thread_on_separate_approved_workspace(
    tmp_path: Path,
) -> None:
    """The blocking question for the vertical flow: can the real Codex CLI
    resume the same thread after `--cd` changes to a physically separate
    approved-only workspace? If this fails, same-session mixed-to-approved
    resume is not achievable with the current CLI boundary."""
    mixed = tmp_path / "mixed-input"
    mixed.mkdir()
    (mixed / "fact.txt").write_text(
        "marker=mixed-workspace-marker\n", encoding="utf-8"
    )
    (mixed / "excluded.txt").write_text(
        "marker=must-never-be-read-after-approval\n", encoding="utf-8"
    )
    mixed = mixed.resolve()

    approved = tmp_path / "approved-output"
    approved.mkdir()
    (approved / "fact.txt").write_text(
        "marker=mixed-workspace-marker\n", encoding="utf-8"
    )
    approved = approved.resolve()
    assert not approved.is_relative_to(mixed)
    assert not mixed.is_relative_to(approved)

    store = JsonSessionStore(tmp_path / "controller-state.json")
    controller = CodexSessionController.with_local_codex(store)
    created = controller.create_session(mixed)

    investigation_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {
            "answer": {
                "type": "string",
                "enum": ["mixed-workspace-marker"],
            }
        },
    }
    investigated = controller.start_investigation(
        created.controller_session_id,
        mixed,
        CodexOperationRequest(
            "Read fact.txt inside the current workspace. Return its marker value as answer.",
            investigation_schema,
            120,
        ),
    )
    assert investigated.receipt.succeeded

    if not investigated.session.resume_supported:
        pytest.skip("Local Codex CLI does not support verified resume.")
    assert investigated.session.codex_session_id is not None

    waiting = controller.record_awaiting_human_review(
        investigated.session.controller_session_id
    )
    bound = controller.bind_approved_workspace(
        waiting.controller_session_id,
        approved,
        workspace_fingerprint(approved),
    )
    assert bound.approved_workspace_root == str(approved)

    reporting_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {
            "answer": {
                "type": "string",
                "enum": ["mixed-workspace-marker", "excluded-file-visible"],
            }
        },
    }
    reported = controller.start_reporting(
        bound.controller_session_id,
        approved,
        CodexOperationRequest(
            (
                "This is the same investigation thread, now bound to a "
                "different, approved-only workspace directory. Read fact.txt "
                "in the current workspace and return its marker value as "
                "answer. If excluded.txt exists in the current workspace, "
                "return excluded-file-visible instead."
            ),
            reporting_schema,
            120,
        ),
    )

    assert reported.receipt.succeeded
    assert reported.receipt.resume_attempted is True
    assert reported.receipt.new_codex_session_created is False
    assert reported.receipt.codex_session_id == investigated.session.codex_session_id
    assert reported.session.codex_session_id == investigated.session.codex_session_id
    assert reported.receipt.workspace_root == str(approved)
    assert reported.structured_output == {"answer": "mixed-workspace-marker"}
