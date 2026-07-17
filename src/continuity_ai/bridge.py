"""Stable UTF-8 newline-delimited JSON bridge."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import asdict, is_dataclass
from continuity_ai.errors import PublicError
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.evidence import artifact_to_reasoning, order_evidence
from continuity_ai.reasoning_pipeline import FakeAuroraProvider, run_analysis
from continuity_ai.vault import Vault
class Bridge:
    def __init__(self): self.vault=None; self.records=(); self.spans=(); self.analysis=None
    def handle(self, cmd: dict):
        name=cmd["command"]
        try:
            if name=="initialize_vault": self.vault=Vault(Path(cmd["path"])); s=self.vault.initialize(cmd.get("owner_name","Owner"), cmd["password"]); data={"session_id":s.session_id}
            elif name=="unlock_vault": self.vault=Vault(Path(cmd["path"])); s=self.vault.unlock(cmd["password"]); data={"session_id":s.session_id}
            elif name=="lock_vault": self.vault.lock(); data={"locked":True}
            elif name=="load_project": self.records=order_evidence(tuple(artifact_to_reasoning(r) for r in ingest_artifacts(Path(cmd["artifact_root"])))); data={"evidence_count":len(self.records)}
            elif name=="analyze_project": self.analysis,self.spans,snap=run_analysis(self.records, cmd.get("question",""), FakeAuroraProvider()); data={"analysis_status":self.analysis.analysis_status,"citation_cards":[]}
            elif name=="send_message": data={"kind":"general","message":"I can help with that. Nothing in the project was changed."}
            elif name=="confirm_attestation": a=self.vault.confirm_attestation(cmd["proposal_id"]); data={"evidence_id":a.evidence_id}
            elif name=="confirm_analysis_revision": data={"confirmed":True}
            elif name=="get_workspace_state": data={"evidence_count":len(self.records),"has_analysis":self.analysis is not None}
            else: raise PublicError("unknown_command","The command is not supported.")
            return {"ok":True,"command":name,"data":_ser(data)}
        except PublicError as e:
            return {"ok":False,"command":name,"error":e.to_dict()}
def _ser(v):
    if is_dataclass(v): return asdict(v)
    if isinstance(v, tuple): return [_ser(x) for x in v]
    if isinstance(v, dict): return {k:_ser(x) for k,x in v.items()}
    return v
def encode_response(resp: dict) -> bytes: return (json.dumps(resp, ensure_ascii=False)+"\n").encode("utf-8")
def decode_command(line: bytes) -> dict: return json.loads(line.decode("utf-8"))
