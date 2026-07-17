"""Evidence-grounded reasoning entry point."""
from __future__ import annotations
from pathlib import Path
from continuity_ai.artifact_io import validate_production_artifact_root
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.evidence import artifact_to_reasoning, order_evidence
from continuity_ai.reasoning_pipeline import FakeAuroraProvider, run_analysis
class ReasoningPipelineNotImplementedError(NotImplementedError): pass
def answer_morning_question(project_root: Path, question: str) -> dict[str, object]:
    validate_production_artifact_root(project_root)
    records=order_evidence(tuple(artifact_to_reasoning(r) for r in ingest_artifacts(project_root)))
    result, spans, snapshot = run_analysis(records, question, FakeAuroraProvider())
    required=[]
    for gs in (result.continuity_break, result.next_action):
        if gs:
            for sid in gs.span_ids:
                eid=sid.split(":",1)[0]
                if eid not in required: required.append(eid)
    return {"analysis_status": result.analysis_status, "continuity_break_kind": result.continuity_break_kind, "continuity_break": result.continuity_break.statement if result.continuity_break else None, "required_evidence": required, "next_action": result.next_action.statement if result.next_action else None}
