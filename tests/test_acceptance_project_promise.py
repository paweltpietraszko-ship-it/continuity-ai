from __future__ import annotations

from pathlib import Path

from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.reasoning import answer_morning_question


def test_final_product_promise_finds_aurora_continuity_break(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)

    result = answer_morning_question(
        tmp_path / "fixtures/project_aurora/generated/artifacts",
        "What changed overnight, what contradicts itself, and what needs attention next?",
    )

    assert result["continuity_break"] == (
        "The approved location change is reflected in the budget but not in the production calendar or current call sheet."
    )
    assert result["required_evidence"] == [
        "aurora-email-investor-approval-001",
        "aurora-budget-v4-001",
        "aurora-calendar-production-001",
        "aurora-callsheet-current-001",
    ]
    assert result["next_action"] == (
        "Update the production calendar and call sheet before tomorrow's crew briefing."
    )
