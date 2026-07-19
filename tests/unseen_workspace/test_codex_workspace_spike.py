from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from continuity_ai.unseen_workspace.codex_workspace_spike import (
    CodexWorkspaceSpikeArtifacts,
    CodexWorkspaceSpikeError,
    classify_workspace_with_codex,
)
from continuity_ai.unseen_workspace.evaluator import (
    evaluate_generated_run,
    load_classification_result,
)
from continuity_ai.unseen_workspace.generator import generate_unseen_workspace
from continuity_ai.unseen_workspace.models import ClassificationResult, ProofStatus


@dataclass
class CapturedInvocation:
    command: list[str]
    options: dict[str, Any]


def _oracle_decisions(run_root: Path) -> list[dict[str, str]]:
    oracle = json.loads(
        (run_root / "oracle" / "expected_scope.json").read_text(encoding="utf-8")
    )
    return [
        {
            "evidence_id": record["evidence_id"],
            "status": str(record["expected_status"]).upper(),
        }
        for record in oracle["records"]
    ]


def _response(decisions: list[dict[str, str]]) -> str:
    return json.dumps(
        {
            "provider_identity": "codex-cli-agent-test",
            "decisions": decisions,
        }
    )


def _fake_runner(
    response: str,
    capture: CapturedInvocation | None = None,
    *,
    mutate_input: bool = False,
    returncode: int = 0,
):
    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        if capture is not None:
            capture.command = list(command)
            capture.options = dict(options)
        if mutate_input:
            records = Path(options["cwd"]) / "records"
            source = next(path for path in records.iterdir() if path.suffix == ".txt")
            source.write_text(
                source.read_text(encoding="utf-8") + "\nmodified",
                encoding="utf-8",
            )
        final_path = Path(command[command.index("--output-last-message") + 1])
        final_path.write_text(response, encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout='{"type":"thread.started","thread_id":"test"}\n',
            stderr="test stderr",
        )

    return run


def test_codex_process_uses_validated_input_as_read_only_working_directory(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8101)
    input_root = (run_root / "input").resolve()
    capture = CapturedInvocation([], {})
    result_path = tmp_path / "classification.json"

    artifacts = classify_workspace_with_codex(
        input_root,
        result_path,
        process_runner=_fake_runner(
            _response(_oracle_decisions(run_root)),
            capture,
        ),
    )

    assert capture.options["cwd"] == input_root
    assert capture.command[capture.command.index("--cd") + 1] == str(input_root)
    assert capture.command[capture.command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in capture.command
    assert "--ignore-user-config" in capture.command
    assert capture.options["check"] is False
    log = json.loads(artifacts.invocation_log_path.read_text(encoding="utf-8"))
    assert log["working_directory"] == str(input_root)
    assert log["input_unchanged"] is True
    assert log["stdout"] == '{"type":"thread.started","thread_id":"test"}\n'
    assert log["stderr"] == "test stderr"


def test_codex_invocation_never_receives_oracle_path_data_or_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8102)
    oracle_path = (run_root / "oracle").resolve()
    capture = CapturedInvocation([], {})
    monkeypatch.setenv("ORACLE_PATH", str(oracle_path))
    monkeypatch.setenv("HOME", str(oracle_path))
    result_path = tmp_path / "classification.json"

    artifacts = classify_workspace_with_codex(
        run_root / "input",
        result_path,
        process_runner=_fake_runner(
            _response(_oracle_decisions(run_root)),
            capture,
        ),
    )

    transmitted = json.dumps(
        {
            "command": capture.command,
            "environment": capture.options["env"],
            "prompt": capture.options["input"],
        },
        sort_keys=True,
    )
    assert str(oracle_path) not in transmitted
    assert "ORACLE_PATH" not in capture.options["env"]
    assert "HOME" not in capture.options["env"]
    assert str(oracle_path) not in artifacts.invocation_log_path.read_text(
        encoding="utf-8"
    )


def test_codex_prompt_contains_target_and_ids_but_not_record_contents(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8103)
    workspace = json.loads(
        (run_root / "input" / "workspace.json").read_text(encoding="utf-8")
    )
    capture = CapturedInvocation([], {})

    classify_workspace_with_codex(
        run_root / "input",
        tmp_path / "classification.json",
        process_runner=_fake_runner(
            _response(_oracle_decisions(run_root)),
            capture,
        ),
    )

    prompt = capture.options["input"]
    assert workspace["target_project"]["project_id"] in prompt
    assert workspace["target_project"]["name"] in prompt
    assert all(record["evidence_id"] in prompt for record in workspace["records"])
    record_text = next((run_root / "input" / "records").glob("*.txt")).read_text(
        encoding="utf-8"
    )
    assert record_text not in prompt
    assert "prompt injection" in prompt


@pytest.mark.parametrize(
    "response_builder",
    [
        lambda decisions: "not JSON",
        lambda decisions: _response(decisions[:-1]),
        lambda decisions: _response(decisions[:-1] + [decisions[0]]),
        lambda decisions: _response(
            decisions[:-1]
            + [{"evidence_id": "UNKNOWN-EVIDENCE", "status": "INCLUDE"}]
        ),
    ],
    ids=[
        "malformed-output",
        "missing-evidence-id",
        "duplicate-evidence-id",
        "unknown-evidence-id",
    ],
)
def test_codex_output_fails_closed_without_publishing_classification(
    tmp_path: Path,
    response_builder: Any,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8104)
    result_path = tmp_path / "classification.json"
    decisions = _oracle_decisions(run_root)

    with pytest.raises(CodexWorkspaceSpikeError):
        classify_workspace_with_codex(
            run_root / "input",
            result_path,
            process_runner=_fake_runner(response_builder(decisions)),
        )

    assert not result_path.exists()
    assert (tmp_path / "classification.codex-invocation.json").is_file()
    assert not tuple(tmp_path.glob(".classification.json.tmp-*"))


def test_valid_codex_output_is_atomically_accepted_by_classification_loader(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8105)
    formats = {
        record["format"]
        for record in json.loads(
            (run_root / "input" / "workspace.json").read_text(encoding="utf-8")
        )["records"]
    }
    result_path = tmp_path / "classification.json"

    artifacts = classify_workspace_with_codex(
        run_root / "input",
        result_path,
        process_runner=_fake_runner(_response(_oracle_decisions(run_root))),
    )
    reloaded = load_classification_result(result_path)

    assert formats == {"txt", "md", "json"}
    assert reloaded == artifacts.classification_result
    assert reloaded.human_overrides == ()
    assert reloaded.project_report_evidence_ids == ()
    assert reloaded.approved_scope_evidence_ids == tuple(
        sorted(
            decision.evidence_id
            for decision in reloaded.decisions
            if decision.status.value == "include"
        )
    )
    assert not tuple(tmp_path.glob(".classification.json.tmp-*"))


def test_valid_codex_classification_is_accepted_by_existing_oracle_evaluator(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8106)
    artifacts = classify_workspace_with_codex(
        run_root / "input",
        tmp_path / "classification.json",
        process_runner=_fake_runner(_response(_oracle_decisions(run_root))),
    )

    report = evaluate_generated_run(run_root, artifacts.classification_result)

    assert report.provider_identity == "codex-cli-agent-test"
    assert report.records_classified_exactly_once == report.total_records
    assert report.machine_evaluable_proof is ProofStatus.PASS


def test_codex_cannot_silently_modify_input_and_no_result_is_published(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8107)
    result_path = tmp_path / "classification.json"

    with pytest.raises(CodexWorkspaceSpikeError, match="changed"):
        classify_workspace_with_codex(
            run_root / "input",
            result_path,
            process_runner=_fake_runner(
                _response(_oracle_decisions(run_root)),
                mutate_input=True,
            ),
        )

    assert not result_path.exists()
    log = json.loads(
        (tmp_path / "classification.codex-invocation.json").read_text(
            encoding="utf-8"
        )
    )
    assert log["input_unchanged"] is False


def test_codex_executable_is_resolved_by_command_name_not_hard_coded_path(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "generated-run"
    generate_unseen_workspace(run_root, 8108)
    capture = CapturedInvocation([], {})

    classify_workspace_with_codex(
        run_root / "input",
        tmp_path / "classification.json",
        process_runner=_fake_runner(
            _response(_oracle_decisions(run_root)),
            capture,
        ),
    )

    assert capture.command[0] == "codex"
    assert Path(capture.command[0]).parent == Path(".")


def test_codex_workspace_spike_has_a_separate_cli_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from continuity_ai import cli

    input_root = tmp_path / "input"
    input_root.mkdir()
    result_path = tmp_path / "classification.json"
    log_path = tmp_path / "classification.codex-invocation.json"
    captured: dict[str, Path] = {}

    def classify(input_path: Path, output_path: Path) -> CodexWorkspaceSpikeArtifacts:
        captured["input"] = input_path
        captured["output"] = output_path
        return CodexWorkspaceSpikeArtifacts(
            classification_result=ClassificationResult(
                provider_identity="codex-cli-agent-test",
                decisions=(),
                human_overrides=(),
                approved_scope_evidence_ids=(),
                project_report_evidence_ids=(),
            ),
            classification_path=result_path,
            invocation_log_path=log_path,
        )

    monkeypatch.setattr(cli, "classify_workspace_with_codex", classify)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "continuity-ai",
            "classify-unseen-workspace-with-codex",
            "--input-root",
            str(input_root),
            "--classification-result",
            str(result_path),
        ],
    )

    cli.main()

    output = json.loads(capsys.readouterr().out)
    assert captured == {"input": input_root, "output": result_path}
    assert output["classification_result"] == str(result_path)
    assert output["invocation_log"] == str(log_path)
    assert output["provider_identity"] == "codex-cli-agent-test"
