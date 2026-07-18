import copy
from pathlib import Path

import pytest

from continuity_ai.evidence import build_spans
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.io import load_workspace

FIXTURE = Path(__file__).parents[2] / "fixtures" / "source_scoping_mixed_workspace"


@pytest.fixture
def workspace():
    target, records = load_workspace(FIXTURE)
    spans = build_spans(records)
    return target, records, spans


@pytest.fixture
def valid_payload(workspace):
    target, records, spans = workspace
    return FakeSourceScopingProvider().classify(target, records, spans)


@pytest.fixture
def mutate(valid_payload):
    def factory():
        return copy.deepcopy(valid_payload)

    return factory
