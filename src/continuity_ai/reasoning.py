"""Future evidence-grounded reasoning pipeline."""

from __future__ import annotations

from pathlib import Path


class ReasoningPipelineNotImplementedError(NotImplementedError):
    """Raised until the evidence-grounded reasoning pipeline is implemented."""


def answer_morning_question(project_root: Path, question: str) -> dict[str, object]:
    """Answer the Project Aurora morning question from artifacts.

    The production reasoning pipeline is intentionally not implemented in Gate G-01.
    It must eventually inspect generated artifacts directly and must not read test-only
    ground truth data.
    """

    raise ReasoningPipelineNotImplementedError(
        "Evidence-grounded reasoning pipeline is not implemented yet."
    )
