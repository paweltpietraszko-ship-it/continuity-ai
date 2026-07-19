from __future__ import annotations
from pathlib import Path
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.reasoning import answer_morning_question
from continuity_ai.reasoning_pipeline import DeterministicOfflineReasoningProvider

def test_offline_provider_does_not_invent_fixture_continuity_break(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    result = answer_morning_question(
        tmp_path / "fixtures/project_aurora/generated/artifacts",
        "What changed, and what must I fix before tomorrow?",
        DeterministicOfflineReasoningProvider(),
    )
    assert result == {
        "analysis_status": "no_material_break_found",
        "continuity_break_kind": None,
        "continuity_break": None,
        "required_evidence": [],
        "next_action": None,
    }
