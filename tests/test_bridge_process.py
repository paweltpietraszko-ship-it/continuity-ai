from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


def _runner_environment(provider: str | None = "fake_aurora") -> dict[str, str]:
    environment = os.environ.copy()
    if provider is None:
        environment.pop("CONTINUITY_REASONING_PROVIDER", None)
    else:
        environment["CONTINUITY_REASONING_PROVIDER"] = provider
    return environment


def _run_bridge(
    payload: bytes,
    *,
    provider: str | None = "fake_aurora",
    timeout: float = 10,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "continuity_ai.bridge_main"],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_runner_environment(provider),
        check=False,
        timeout=timeout,
    )


def _json_lines(output: bytes) -> list[dict]:
    text = output.decode("utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _assert_controlled_error(response: dict, code: str = "validation_error") -> None:
    assert response["ok"] is False
    assert response["error"]["code"] == code
    assert set(response["error"]) == {"code", "message", "object_id"}
    assert response["error"]["object_id"] is None
    serialized = json.dumps(response, ensure_ascii=False)
    for forbidden in ("Traceback", "Exception", "password", "API key"):
        assert forbidden not in serialized


def test_process_round_trips_polish_utf8_without_stdout_noise() -> None:
    polish_command = "nieznane-Paweł Żółć"
    request = json.dumps(
        {"command": polish_command}, ensure_ascii=False
    ).encode("utf-8") + b"\n"

    completed = _run_bridge(request)

    assert completed.returncode == 0
    assert completed.stderr == b""
    responses = _json_lines(completed.stdout)
    assert len(responses) == 1
    assert responses[0]["command"] == polish_command
    _assert_controlled_error(responses[0], "unknown_command")


def test_process_continues_after_malformed_utf8_then_valid_command() -> None:
    valid = json.dumps({"command": "get_workspace_state"}).encode("utf-8")

    completed = _run_bridge(b"\xff\xfe invalid UTF-8\n" + valid + b"\n")

    assert completed.returncode == 0
    assert completed.stderr == b""
    responses = _json_lines(completed.stdout)
    assert len(responses) == 2
    _assert_controlled_error(responses[0])
    assert responses[1] == {
        "ok": True,
        "command": "get_workspace_state",
        "data": {
            "vault_unlocked": False,
            "artifact_evidence_count": 0,
            "evidence_count": 0,
            "has_analysis": False,
            "retained_analysis_status": "none",
            "pending_attestation_count": 0,
            "pending_revision_count": 0,
        },
    }


def test_process_contains_empty_and_non_object_lines_then_recovers() -> None:
    inputs = [
        b"\n",
        b"[]\n",
        json.dumps("Paweł Żółć", ensure_ascii=False).encode("utf-8") + b"\n",
        json.dumps({"command": "get_workspace_state"}).encode("utf-8") + b"\n",
    ]

    completed = _run_bridge(b"".join(inputs))

    assert completed.returncode == 0
    assert completed.stderr == b""
    responses = _json_lines(completed.stdout)
    assert len(responses) == len(inputs)
    for response in responses[:3]:
        _assert_controlled_error(response)
    assert responses[3]["ok"] is True
    assert responses[3]["command"] == "get_workspace_state"


def test_process_clean_eof_exits_without_phantom_response() -> None:
    request = json.dumps({"command": "get_workspace_state"}).encode("utf-8") + b"\n"

    completed = _run_bridge(request, timeout=5)

    assert completed.returncode == 0
    assert completed.stderr == b""
    assert len(_json_lines(completed.stdout)) == 1
    assert completed.stdout.endswith(b"\n")


@pytest.mark.parametrize("provider", [None, "unsupported-provider"])
def test_process_provider_startup_configuration_fails_safely(
    provider: str | None,
) -> None:
    request = json.dumps({"command": "get_workspace_state"}).encode("utf-8") + b"\n"

    completed = _run_bridge(request, provider=provider)

    assert completed.returncode != 0
    assert completed.stdout == b""
    assert completed.stderr == b""
