"""Explicit startup selection for the reasoning provider."""
from __future__ import annotations

import os

from continuity_ai.errors import ProviderError
from continuity_ai.deterministic_offline_provider import (
    DeterministicOfflineReasoningProvider,
)
from continuity_ai.openai_provider import OpenAIReasoningProvider


CONTINUITY_REASONING_PROVIDER = "CONTINUITY_REASONING_PROVIDER"
OPENAI_PROVIDER = "openai"
DETERMINISTIC_OFFLINE_PROVIDER = "deterministic_offline"
SUPPORTED_REASONING_PROVIDERS = frozenset(
    {OPENAI_PROVIDER, DETERMINISTIC_OFFLINE_PROVIDER}
)


def create_reasoning_provider():
    """Construct the explicitly configured reasoning provider."""
    configured = os.environ.get(CONTINUITY_REASONING_PROVIDER)
    if not isinstance(configured, str):
        raise ProviderError()
    normalized = configured.strip().casefold()
    if normalized == OPENAI_PROVIDER:
        return OpenAIReasoningProvider()
    if normalized == DETERMINISTIC_OFFLINE_PROVIDER:
        return DeterministicOfflineReasoningProvider()
    raise ProviderError()
