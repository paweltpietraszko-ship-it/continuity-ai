from __future__ import annotations

import socket

import pytest

from continuity_ai.bridge import Bridge
from continuity_ai.openai_provider import OpenAIReasoningProvider
from continuity_ai.reasoning_pipeline import DeterministicOfflineReasoningProvider


LOOPBACK_CLOSED_PORT = ("127.0.0.1", 9)


def _assert_default_socket_guard_blocks_connection() -> None:
    with pytest.warns(UserWarning, match="A test tried to use socket.socket"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(0.05)
                client.connect(LOOPBACK_CLOSED_PORT)
        except Exception as exc:
            assert type(exc).__name__ == "SocketBlockedError"
        else:
            raise AssertionError("the default pytest socket guard did not block TCP")


def test_default_pytest_run_blocks_tcp_connections() -> None:
    _assert_default_socket_guard_blocks_connection()


def test_explicit_openai_provider_does_not_bypass_default_socket_guard(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CONTINUITY_REASONING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("CONTINUITY_OPENAI_MODEL", "test-model")

    bridge = Bridge()

    assert isinstance(bridge.provider, OpenAIReasoningProvider)
    assert not isinstance(bridge.provider, DeterministicOfflineReasoningProvider)
    _assert_default_socket_guard_blocks_connection()
