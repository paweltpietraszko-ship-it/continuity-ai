"""Provider protocol dedicated to source scoping."""
from __future__ import annotations

from typing import Any, Protocol


class SourceScopingProvider(Protocol):
    provider_id: str

    def classify(
        self,
        target_project: str,
        evidence: tuple[Any, ...],
        spans: tuple[Any, ...],
    ) -> dict[str, Any]: ...
