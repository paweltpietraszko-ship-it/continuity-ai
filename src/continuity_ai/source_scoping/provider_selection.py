"""Explicit source-scoping provider selection."""
from __future__ import annotations

import os

from continuity_ai.errors import ProviderError
from continuity_ai.source_scoping.fake_provider import FakeSourceScopingProvider
from continuity_ai.source_scoping.openai_provider import OpenAISourceScopingProvider

SOURCE_SCOPING_PROVIDER_ENV = "CONTINUITY_SOURCE_SCOPING_PROVIDER"


def create_source_scoping_provider():
    configured = os.environ.get(SOURCE_SCOPING_PROVIDER_ENV)
    if not isinstance(configured, str):
        raise ProviderError()
    normalized = configured.strip().casefold()
    if normalized == "openai":
        return OpenAISourceScopingProvider()
    if normalized == "fake":
        return FakeSourceScopingProvider()
    raise ProviderError()
