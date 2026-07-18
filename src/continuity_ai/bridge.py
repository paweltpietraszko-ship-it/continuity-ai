"""Stable UTF-8 newline-delimited JSON bridge wiring the real vertical-skeleton domain functions."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import asdict, is_dataclass
from continuity_ai import conversation
from continuity_ai.domain import AuthenticatedUserAttestation
from continuity_ai.errors import PublicError, ValidationError, VaultLockedError
from continuity_ai.evidence import artifact_to_reasoning, attestation_to_reasoning, order_evidence, build_spans, hydrate_citations
from continuity_ai.ingestion import ingest_artifacts
from continuity_ai.reasoning_pipeline import FakeAuroraProvider, run_analysis
from continuity_ai.vault import Vault


class Bridge:
    def __init__(self, provider=None):
        self.vault = None
        self.artifact_records: tuple = ()
        self.records: tuple = ()
        self.spans: tuple = ()
        self.analysis = None
        self.snapshot = None
        self.last_question: str | None = None
        self.provider = provider or FakeAuroraProvider()

    def handle(self, cmd) -> dict:
        command_name = cmd.get("command") if isinstance(cmd, dict) else None
        if not isinstance(command_name, str) or not command_name:
            command_name = None
        try:
            if not isinstance(cmd, dict) or command_name is None:
                raise ValidationError()
            data = self._dispatch(command_name, cmd)
            return {"ok": True, "command": command_name, "data": _ser(data)}
        except PublicError as exc:
            return {"ok": False, "command": command_name, "error": exc.to_dict()}
        except Exception:
            return {"ok": False, "command": command_name, "error": ValidationError().to_dict()}

    def _dispatch(self, name: str, cmd: dict):
        if name == "initialize_vault":
            candidate = Vault(Path(cmd["path"]))
            session = candidate.initialize(cmd.get("owner_name", "Owner"), cmd["password"])
            try:
                candidate_records, candidate_spans = _compose_evidence(self.artifact_records, candidate)
            except Exception:
                candidate.lock()
                raise
            previous_vault = self.vault
            if previous_vault is not None:
                previous_vault.lock()
            self.vault = candidate
            self.records = candidate_records
            self.spans = candidate_spans
            self._invalidate_analysis()
            return {"session_id": session.session_id}

        if name == "unlock_vault":
            candidate = Vault(Path(cmd["path"]))
            session = candidate.unlock(cmd["password"])
            try:
                candidate_records, candidate_spans = _compose_evidence(self.artifact_records, candidate)
            except Exception:
                candidate.lock()
                raise
            previous_records = self.records
            previous_vault = self.vault
            if previous_vault is not None:
                previous_vault.lock()
            self.vault = candidate
            self.records = candidate_records
            self.spans = candidate_spans
            if self.records != previous_records:
                self._invalidate_analysis()
            return {"session_id": session.session_id}

        if name == "lock_vault":
            if self.vault is None:
                raise VaultLockedError()
            self.vault.lock()
            self.records = self.artifact_records
            self.spans = build_spans(self.artifact_records)
            self._invalidate_analysis()
            return {"locked": True}

        if name == "load_project":
            new_artifact_records = order_evidence(
                tuple(artifact_to_reasoning(r) for r in ingest_artifacts(Path(cmd["artifact_root"])))
            )
            candidate_records, candidate_spans = _compose_evidence(new_artifact_records, self.vault)
            self.artifact_records = new_artifact_records
            self.records = candidate_records
            self.spans = candidate_spans
            self._invalidate_analysis()
            return {"artifact_evidence_count": len(self.artifact_records), "evidence_count": len(self.records)}

        if name == "analyze_project":
            if not self.records:
                raise ValidationError()
            question = cmd.get("question", "")
            if not isinstance(question, str):
                raise ValidationError()
            result, spans, snapshot = run_analysis(self.records, question, self.provider)
            self.analysis = result
            self.spans = spans
            self.snapshot = snapshot
            self.last_question = question
            cards = hydrate_citations(_citation_span_ids(result), self.records, self.spans)
            return {**_analysis_fields(result), "citation_cards": cards, **_snapshot_fields(snapshot)}

        if name == "send_message":
            message = cmd["message"]
            revision_candidate = cmd.get("revision_candidate")
            return conversation.send_message(
                message, self.records, self.spans, vault=self.vault, revision_candidate=revision_candidate
            )

        if name == "confirm_attestation":
            if self.vault is None:
                raise VaultLockedError()
            self.vault.require()
            if self.analysis is None or self.last_question is None:
                raise ValidationError()
            proposal_id = cmd["proposal_id"]
            attestation = self.vault.confirm_attestation(proposal_id)
            self._refresh_evidence()
            result, spans, snapshot = run_analysis(self.records, self.last_question, self.provider)
            self.analysis = result
            self.spans = spans
            self.snapshot = snapshot
            cards = hydrate_citations(_citation_span_ids(result), self.records, self.spans)
            return {
                "evidence_id": attestation.evidence_id,
                "evidence_count": len(self.records),
                "citation_cards": cards,
                **_analysis_fields(result),
            }

        if name == "confirm_analysis_revision":
            if self.vault is None:
                raise VaultLockedError()
            proposal_id = cmd["proposal_id"]
            result = conversation.confirm_analysis_revision(self.vault, proposal_id)
            self.analysis = result
            cards = hydrate_citations(_citation_span_ids(result), self.records, self.spans)
            return {"confirmed": True, "proposal_id": proposal_id, "citation_cards": cards, **_analysis_fields(result)}

        if name == "get_workspace_state":
            vault_unlocked = False
            pending_attestation_count = 0
            pending_revision_count = 0
            if self.vault is not None:
                pending_attestation_count = len(self.vault.pending_attestations)
                pending_revision_count = len(self.vault.pending_revisions)
                try:
                    self.vault.require()
                    vault_unlocked = True
                except VaultLockedError:
                    vault_unlocked = False
            data = {
                "vault_unlocked": vault_unlocked,
                "artifact_evidence_count": len(self.artifact_records),
                "evidence_count": len(self.records),
                "has_analysis": self.analysis is not None,
                "pending_attestation_count": pending_attestation_count,
                "pending_revision_count": pending_revision_count,
            }
            if self.analysis is not None:
                cards = hydrate_citations(_citation_span_ids(self.analysis), self.records, self.spans)
                data.update(_analysis_fields(self.analysis))
                data["citation_cards"] = cards
            return data

        raise PublicError("unknown_command", "The command is not supported.")

    def _refresh_evidence(self) -> None:
        self.records, self.spans = _compose_evidence(self.artifact_records, self.vault)

    def _invalidate_analysis(self) -> None:
        self.analysis = None
        self.snapshot = None
        self.last_question = None


def _compose_evidence(artifact_records: tuple, candidate_vault) -> tuple[tuple, tuple]:
    """Pure evidence composition: never mutates bridge or vault state."""
    records = artifact_records
    if candidate_vault is not None:
        try:
            candidate_vault.require()
        except VaultLockedError:
            pass
        else:
            attestations = tuple(AuthenticatedUserAttestation(**a) for a in candidate_vault.payload["attestations"])
            records = records + tuple(attestation_to_reasoning(a) for a in attestations)
    combined = order_evidence(records)
    spans = build_spans(combined)
    return combined, spans


def _citation_span_ids(result) -> tuple[str, ...]:
    ordered = list(result.current_state.span_ids)
    if result.continuity_break is not None:
        ordered += list(result.continuity_break.span_ids)
    if result.next_action is not None:
        ordered += list(result.next_action.span_ids)
    seen: set[str] = set()
    unique: list[str] = []
    for span_id in ordered:
        if span_id not in seen:
            seen.add(span_id)
            unique.append(span_id)
    return tuple(unique)


def _analysis_fields(result) -> dict:
    return {
        "analysis_status": result.analysis_status,
        "continuity_break_kind": result.continuity_break_kind,
        "current_state": result.current_state,
        "semantic_annotations": result.semantic_annotations,
        "continuity_break": result.continuity_break,
        "next_action": result.next_action,
    }


def _snapshot_fields(snapshot) -> dict:
    return {
        "analysis_id": snapshot.analysis_id,
        "created_at": snapshot.created_at,
        "prompt_version": snapshot.prompt_version,
        "schema_version": snapshot.schema_version,
        "provider_id": snapshot.provider_id,
    }


def _ser(v):
    if is_dataclass(v):
        return asdict(v)
    if isinstance(v, tuple):
        return [_ser(x) for x in v]
    if isinstance(v, dict):
        return {k: _ser(x) for k, x in v.items()}
    return v


def encode_response(resp: dict) -> bytes:
    return (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")


def decode_command(line: bytes) -> dict:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError() from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError() from exc
    if not isinstance(payload, dict):
        raise ValidationError()
    return payload
