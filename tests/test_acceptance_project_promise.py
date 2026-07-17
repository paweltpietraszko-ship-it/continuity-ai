from __future__ import annotations
from pathlib import Path
from continuity_ai.aurora_fixture import generate_project_aurora_fixture
from continuity_ai.reasoning import answer_morning_question

def test_final_product_promise_finds_aurora_continuity_break(tmp_path: Path) -> None:
    generate_project_aurora_fixture(tmp_path)
    result = answer_morning_question(tmp_path / "fixtures/project_aurora/generated/artifacts", "What changed, and what must I fix before tomorrow?")
    assert result["analysis_status"] == "break_found"
    assert result["continuity_break_kind"] == "propagation_break"
    assert "approved decision" in result["continuity_break"]
    assert set(result["required_evidence"]) >= {"EV-AUR-001", "EV-AUR-002", "EV-AUR-003", "EV-AUR-004"}
    assert "Update" in result["next_action"]
