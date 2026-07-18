"""Explicit startup selection for the reasoning provider."""
from __future__ import annotations

import os

from continuity_ai.errors import ProviderError
from continuity_ai.openai_provider import OpenAIReasoningProvider
from continuity_ai.reasoning_pipeline import FakeAuroraProvider


CONTINUITY_REASONING_PROVIDER = "CONTINUITY_REASONING_PROVIDER"
OPENAI_PROVIDER = "openai"
FAKE_AURORA_PROVIDER = "fake_aurora"
SUPPORTED_REASONING_PROVIDERS = frozenset(
    {OPENAI_PROVIDER, FAKE_AURORA_PROVIDER}
)


def create_reasoning_provider():
    """Construct the explicitly configured reasoning provider."""
    configured = os.environ.get(CONTINUITY_REASONING_PROVIDER)
    if not isinstance(configured, str):
        raise ProviderError()
    normalized = configured.strip().casefold()
    if normalized == OPENAI_PROVIDER:
        return OpenAIReasoningProvider()
    if normalized == FAKE_AURORA_PROVIDER:
        return FakeAuroraProvider()
    raise ProviderError()
