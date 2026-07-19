"""Stable UTF-8 newline-delimited JSON bridge wiring the real vertical-skeleton domain functions."""
from __future__ import annotations
import json
from pathlib import Path
from dataclasses import fields, is_dataclass
from continuity_ai import conversation
from continuity_ai.analysis_revision import build_analysis_revision_context_binding
from continuity_ai.domain import AnalysisRevisionProposal, AuthenticatedUserAttestation, SavedAnalysis
from continuity_ai.errors import PublicError, ProjectMismatchError, ValidationError, VaultLockedError
from continuity_ai.evidence import artifact_to_reasoning, attestation_to_reasoning, order_evidence, build_spans, content_sha256, hydrate_citations, hydrate_snapshot_citations, snapshot_citation_statuses
from continuity_ai.ingestion import ingest_artifacts, read_project_name
from continuity_ai.provider_selection import create_reasoning_provider
from continuity_ai.reasoning_pipeline import run_analysis
from continuity_ai.retained_analysis import RETAINED_ANALYSIS_NONE, RETAINED_ANALYSIS_VALID, restore_latest
from continuity_ai.source_scoping.bridge_adapter import (
    STATUS_APPROVED,
    STATUS_INVALID,
    STATUS_NONE,
    STATUS_PENDING_REVIEW,
    SourceScopingSession,
)
from continuity_ai.vault import Vault


class Bridge:
    def __init__(self, provider=None, source_scoping_provider=None):
        self.vault = None
        self.project: str | None = None
        self.artifact_records: tuple = ()
        self.artifact_evidence_records: tuple = ()
        self.records: tuple = ()
        self.spans: tuple = ()
        self.analysis = None
        self.snapshot = None
        self.last_question: str | None = None
        self.retained_analysis_status: str = RETAINED_ANALYSIS_NONE
        self.provider = provider if provider is not None else create_reasoning_provider()
        self.source_scoping = SourceScopingSession(source_scoping_provider)

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
            # A newly established vault starts with no live artifact evidence at all:
            # the previous vault's artifact_records must never be composed against
            # this one, or the new project would silently inherit the old project's
            # live evidence before load_project is ever called for it.
            try:
                candidate_records, candidate_spans = _compose_evidence((), candidate)
            except Exception:
                candidate.lock()
                raise
            previous_vault = self.vault
            if previous_vault is not None:
                previous_vault.lock()
            self.vault = candidate
            self.artifact_records = ()
            self.artifact_evidence_records = ()
            self.records = candidate_records
            self.spans = candidate_spans
            self.source_scoping.reset()
            self._restore_from_vault(clear_project=True)
            return {"session_id": session.session_id, "owner_display_name": candidate.payload["owner"]["display_name"]}

        if name == "unlock_vault":
            candidate = Vault(Path(cmd["path"]))
            session = candidate.unlock(cmd["password"])
            # Same isolation rule as initialize_vault: this vault's own project
            # identity, if any, is restored below from its own retained analysis,
            # never from whatever artifacts happened to be loaded for a prior vault.
            try:
                candidate_records, candidate_spans = _compose_evidence((), candidate)
            except Exception:
                candidate.lock()
                raise
            previous_vault = self.vault
            if previous_vault is not None:
                previous_vault.lock()
            self.vault = candidate
            self.artifact_records = ()
            self.artifact_evidence_records = ()
            self.records = candidate_records
            self.spans = candidate_spans
            self.source_scoping.reset()
            self._restore_from_vault(clear_project=True)
            return {"session_id": session.session_id, "owner_display_name": candidate.payload["owner"]["display_name"]}

        if name == "lock_vault":
            if self.vault is None:
                raise VaultLockedError()
            self.vault.lock()
            self._prepare_downstream_project_evidence(after_vault_lock=True)
            self._invalidate_analysis()
            return {"locked": True}

        if name == "load_project":
            artifact_root = Path(cmd["artifact_root"])
            raw_records = ingest_artifacts(artifact_root)
            project_name = read_project_name(artifact_root)
            # A retained analysis is grounded in one specific project; loading a
            # different project's evidence while that analysis is active would make
            # its project_report incoherent, so it is rejected atomically instead of
            # silently swapping project identity out from under the retained report.
            if self.analysis is not None and project_name != self.project:
                raise ProjectMismatchError()
            new_artifact_records = order_evidence(tuple(artifact_to_reasoning(r) for r in raw_records))
            candidate_records, candidate_spans = _compose_evidence(new_artifact_records, self.vault)
            self.artifact_records = new_artifact_records
            self.artifact_evidence_records = tuple(sorted(raw_records, key=lambda r: (r.timestamp, r.evidence_id)))
            self.records = candidate_records
            self.spans = candidate_spans
            self.project = project_name
            # A retained analysis is bound to its own encrypted snapshot, not to
            # whatever project evidence happens to be loaded right now: reloading
            # current evidence re-restores it from the same active vault rather than
            # discarding it (F-05). Citation source status is recomputed against the
            # newly loaded evidence the next time cards are hydrated.
            self._restore_from_vault(clear_project=False)
            self.source_scoping.restore(project_name, self.artifact_records, self.vault)
            try:
                _, _, scoped = self._prepare_downstream_project_evidence()
            except ValidationError:
                self.records = ()
                self.spans = ()
                self._invalidate_analysis()
            else:
                if scoped and not self._analysis_matches_live_evidence():
                    self._invalidate_analysis()
            return {
                "project": self.project,
                "artifact_evidence_count": len(self.artifact_records),
                "evidence_count": len(self.records),
                "evidence_records": self.artifact_evidence_records,
            }

        if name == "scope_project_sources":
            if not self.artifact_records or self.project is None:
                raise ValidationError()
            requested_target = cmd.get("target_project", self.project)
            if requested_target != self.project:
                raise ProjectMismatchError()
            response = self.source_scoping.classify(self.project, self.artifact_records)
            self._invalidate_analysis()
            return {"project": self.project, **response}

        if name == "confirm_source_scope":
            if self.project is None or not self.artifact_records:
                raise ValidationError()
            overrides = cmd.get("overrides")
            if not isinstance(overrides, dict):
                raise ValidationError()
            response = self.source_scoping.approve(
                self.artifact_records, overrides, vault=self.vault
            )
            self._invalidate_analysis()
            self._prepare_downstream_project_evidence()
            return {
                "project": self.project,
                "evidence_count": len(self.records),
                **response,
            }

        if name == "analyze_project":
            records, _, _ = self._prepare_downstream_project_evidence()
            if not records or self.project is None:
                raise ValidationError()
            question = cmd.get("question", "")
            if not isinstance(question, str) or not question.strip():
                raise ValidationError()
            result, spans, snapshot = run_analysis(records, question, self.provider)
            saved = SavedAnalysis(snapshot.analysis_id, snapshot.created_at, result, snapshot, question, self.project)
            persisted = False
            if self.vault is not None:
                try:
                    self.vault.require()
                except VaultLockedError:
                    pass
                else:
                    self.vault.save_initial_analysis(saved)
                    persisted = True
            self.analysis = result
            self.spans = spans
            self.snapshot = snapshot
            self.last_question = question
            # An analysis without an unlocked vault is a real in-memory result, but it
            # was never retained: reporting "valid" here would falsely describe an
            # ephemeral analysis as persisted (F-11).
            self.retained_analysis_status = RETAINED_ANALYSIS_VALID if persisted else RETAINED_ANALYSIS_NONE
            cards = self._hydrate_retained_cards(saved, result)
            return {"project": self.project, **_analysis_fields(result), "citation_cards": cards, **_snapshot_fields(snapshot)}

        if name == "send_message":
            message = cmd["message"]
            revision_candidate = cmd.get("revision_candidate")
            records, spans, scoped = self._prepare_downstream_project_evidence()
            return conversation.send_message(
                message,
                records,
                spans,
                vault=self.vault,
                revision_candidate=revision_candidate,
                project_only=scoped,
                target_project=self.project,
                source_scoping_status=self.source_scoping.status,
                approved_source_scope=self.source_scoping.approved_scope,
            )

        if name == "confirm_attestation":
            if self.vault is None:
                raise VaultLockedError()
            self.vault.require()
            if self.analysis is None or self.last_question is None:
                raise ValidationError()
            proposal_id = cmd["proposal_id"]
            attestation = self.vault.confirm_attestation(proposal_id)
            records, _, _ = self._prepare_downstream_project_evidence(
                refresh_unscoped_projection=True,
            )
            result, spans, snapshot = run_analysis(records, self.last_question, self.provider)
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
            current_context_binding = build_analysis_revision_context_binding(
                self.vault,
                target_project=self.project,
                source_scoping_status=self.source_scoping.status,
                approved_source_scope=self.source_scoping.approved_scope,
                records=self.records,
            )
            result = conversation.confirm_analysis_revision(
                self.vault,
                proposal_id,
                current_context_binding,
            )
            self.analysis = result
            cards = hydrate_citations(_citation_span_ids(result), self.records, self.spans)
            return {"confirmed": True, "proposal_id": proposal_id, "citation_cards": cards, **_analysis_fields(result)}

        if name == "get_workspace_state":
            vault_unlocked = False
            pending_attestation_count = 0
            pending_revision_count = 0
            owner_display_name = None
            if self.vault is not None:
                pending_attestation_count = len(self.vault.pending_attestations)
                pending_revision_count = len(self.vault.pending_revisions)
                try:
                    self.vault.require()
                    vault_unlocked = True
                    owner_display_name = self.vault.payload["owner"]["display_name"]
                except VaultLockedError:
                    vault_unlocked = False
            data = {
                "vault_unlocked": vault_unlocked,
                "owner_display_name": owner_display_name,
                "project": self.project,
                "artifact_evidence_count": len(self.artifact_records),
                "evidence_count": len(self.records),
                "evidence_records": self.artifact_evidence_records,
                "has_analysis": self.analysis is not None,
                "retained_analysis_status": self.retained_analysis_status,
                "project_report": None,
                "pending_attestation_count": pending_attestation_count,
                "pending_revision_count": pending_revision_count,
            }
            if self.source_scoping.status != STATUS_NONE:
                data.update(self.source_scoping.state_payload())
            if self.analysis is not None and self.snapshot is not None and self.last_question and self.project:
                saved = SavedAnalysis(self.snapshot.analysis_id, self.snapshot.created_at, self.analysis, self.snapshot, self.last_question, self.project)
                data.update(_analysis_fields(self.analysis))
                data["citation_cards"] = self._hydrate_retained_cards(saved, self.analysis)
            return data

        raise PublicError("unknown_command", "The command is not supported.")

    def _prepare_downstream_project_evidence(
        self,
        *,
        after_vault_lock: bool = False,
        refresh_unscoped_projection: bool = False,
    ) -> tuple[tuple, tuple, bool]:
        """Apply the one authoritative Source Scoping boundary for project consumers."""
        status = self.source_scoping.status
        if status == STATUS_NONE:
            if after_vault_lock or refresh_unscoped_projection:
                self.records, self.spans = _compose_evidence(
                    self.artifact_records,
                    self.vault,
                )
            return self.records, self.spans, False

        if status in {STATUS_PENDING_REVIEW, STATUS_INVALID}:
            if after_vault_lock:
                self.records = ()
                self.spans = ()
                return self.records, self.spans, True
            raise ValidationError()

        if status != STATUS_APPROVED:
            if after_vault_lock:
                self.records = ()
                self.spans = ()
                return self.records, self.spans, True
            raise ValidationError()

        approved_artifacts = self.source_scoping.active_evidence(
            self.artifact_records
        )
        self.records, self.spans = _compose_evidence(
            approved_artifacts,
            self.vault,
        )
        return self.records, self.spans, True

    def _prepare_analysis_evidence(self) -> None:
        """Preserve the existing analysis seam while delegating to the canonical boundary."""
        self._prepare_downstream_project_evidence()

    def _analysis_matches_live_evidence(self) -> bool:
        if self.snapshot is None:
            return True
        snapshot_records = tuple(
            (str(record["evidence_id"]), str(record["canonical_content_sha256"]))
            for record in self.snapshot.records
        )
        live_records = tuple((record.evidence_id, content_sha256(record.content)) for record in self.records)
        return snapshot_records == live_records

    def _hydrate_retained_cards(self, saved: SavedAnalysis, result) -> tuple:
        """Historical citation text and metadata always come from the retained
        snapshot. Only the per-card source-status label is recomputed against
        whatever live evidence is currently loaded, so drift is surfaced without
        ever rewriting the retained quotation (F-04)."""
        statuses = snapshot_citation_statuses(saved.evidence_snapshot.records, self.records)
        return hydrate_snapshot_citations(saved, _citation_span_ids(result), statuses)

    def _invalidate_analysis(self) -> None:
        self.analysis = None
        self.snapshot = None
        self.last_question = None
        self.retained_analysis_status = RETAINED_ANALYSIS_NONE

    def _restore_from_vault(self, clear_project: bool) -> None:
        """Clear any previous vault's in-memory analysis, then restore only the
        newest retained analysis in the now-active vault if it is valid. Record
        equality with a prior vault is never treated as proof of vault identity,
        and a malformed newest entry never falls back to an older one.

        `clear_project` distinguishes a vault switch (initialize_vault/unlock_vault,
        where any previous vault's project identity must not leak into the new one)
        from a same-vault re-derivation during load_project (where the project was
        just authoritatively established from the freshly loaded manifest and must
        not be reset merely because this vault has no valid retained analysis)."""
        self._invalidate_analysis()
        if clear_project:
            self.project = None
        if self.vault is None:
            return
        try:
            self.vault.require()
        except VaultLockedError:
            return
        restoration = restore_latest(self.vault.payload.get("saved_analyses", []))
        self.retained_analysis_status = restoration.status
        if restoration.status != RETAINED_ANALYSIS_VALID:
            return
        saved = restoration.saved
        self.analysis = saved.result
        self.snapshot = saved.evidence_snapshot
        self.last_question = saved.question
        self.project = saved.project


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
    ordered += list(result.project_report.summary.span_ids)
    for section in result.project_report.sections:
        ordered += list(section.span_ids)
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
        "project_report": result.project_report,
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
        return {
            field.name: _ser(getattr(v, field.name))
            for field in fields(v)
            if not (
                isinstance(v, AnalysisRevisionProposal)
                and field.name == 'context_binding'
            )
        }
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
