"""Atomic orchestration for source scoping."""
from __future__ import annotations

from typing import Any

from continuity_ai.errors import ProviderError, ValidationError
from continuity_ai.source_scoping.provider import SourceScopingProvider
from continuity_ai.source_scoping.validator import validate_source_scoping_payload


def run_source_scoping(
    target_project: str,
    evidence: tuple[Any, ...],
    spans: tuple[Any, ...],
    provider: SourceScopingProvider,
):
    """Return a validated result or fail without publishing partial provider output."""
    if (
        not isinstance(target_project, str)
        or not target_project.strip()
        or target_project != target_project.strip()
    ):
        raise ValidationError()
    try:
        candidate = provider.classify(target_project, evidence, spans)
    except ProviderError:
        raise
    except Exception:
        raise ProviderError() from None
    return validate_source_scoping_payload(candidate, target_project, evidence, spans)
