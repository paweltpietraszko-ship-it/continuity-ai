import json
from types import SimpleNamespace

import pytest

from continuity_ai.errors import ProviderError
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.openai_provider import (
    OpenAISourceScopingProvider,
    build_request_document,
)


class Responses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class Client:
    def __init__(self, responses):
        self.responses = responses


def test_request_contains_only_authoritative_input_not_ground_truth(workspace):
    target, records, spans = workspace
    document = build_request_document(target, records, spans)
    serialized = json.dumps(document).casefold()
    assert document["target_project"] == target
    assert "ground_truth" not in serialized
    assert "expected_status" not in serialized
    assert all("content" not in item for item in document["evidence"])
    assert any(
        "ignore all prior instructions" in span["text"].casefold()
        for span in document["spans"]
    )


def test_openai_provider_uses_strict_schema_and_no_tools(workspace):
    target, records, spans = workspace
    payload = FakeSourceScopingProvider().classify(target, records, spans)
    response = SimpleNamespace(
        status="completed",
        refusal=None,
        output=(),
        output_text=json.dumps(payload),
    )
    responses = Responses(response=response)
    provider = OpenAISourceScopingProvider(Client(responses), model="test-model")
    assert provider.classify(target, records, spans) == payload
    call = responses.calls[0]
    assert call["store"] is False
    assert call["tools"] == []
    assert call["text"]["format"]["strict"] is True
    assert call["text"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="failed", refusal=None, output=(), output_text="{}"),
        SimpleNamespace(status="completed", refusal="no", output=(), output_text="{}"),
        SimpleNamespace(status="completed", refusal=None, output=(), output_text=""),
        SimpleNamespace(status="completed", refusal=None, output=(), output_text="[]"),
        SimpleNamespace(
            status="completed", refusal=None, output=(), output_text="not-json"
        ),
    ],
)
def test_invalid_provider_responses_fail_closed(response, workspace):
    target, records, spans = workspace
    provider = OpenAISourceScopingProvider(
        Client(Responses(response=response)), model="test-model"
    )
    with pytest.raises(ProviderError):
        provider.classify(target, records, spans)


def test_transport_error_fails_closed(workspace):
    target, records, spans = workspace
    provider = OpenAISourceScopingProvider(
        Client(Responses(error=RuntimeError("offline"))), model="test-model"
    )
    with pytest.raises(ProviderError):
        provider.classify(target, records, spans)
