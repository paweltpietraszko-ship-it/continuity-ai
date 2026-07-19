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
