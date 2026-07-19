"""Typed lifecycle and persistence boundary for one local Codex semantic agent."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Protocol

from continuity_ai.codex_process import (
    CodexCliProcessAdapter,
    CodexInvocationRequest,
    CodexProcessBoundaryError,
    CodexProcessResult,
    CodexWorkspaceChangedBeforeLaunch,
    workspace_fingerprint,
)

SESSION_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1


class SessionPhase(str, Enum):
    READY = "ready"
    INVESTIGATING = "investigating"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED = "approved"
    REPORTING = "reporting"
    CONVERSATIONAL = "conversational"
    COMPLETED = "completed"


class CodexAvailability(str, Enum):
    AVAILABLE = "available"
    NOT_INSTALLED = "not_installed"
    NOT_AUTHENTICATED = "not_authenticated"
    UNAVAILABLE = "unavailable"
    INTERRUPTED = "interrupted"
    LIMIT_REACHED = "limit_reached"


class CodexOperation(str, Enum):
    INVESTIGATION = "investigation"
    REPORT = "report"
    CONVERSATION = "conversation"
    RESUME = "resume"


class FailureCategory(str, Enum):
    NOT_INSTALLED = "codex_not_installed"
    NOT_AUTHENTICATED = "codex_not_authenticated"
    UNAVAILABLE = "codex_unavailable"
    LIMIT_REACHED = "codex_limit_reached"
    INTERRUPTED = "codex_interrupted"
    SESSION_MISMATCH = "codex_session_mismatch"
    WORKSPACE_MISMATCH = "workspace_mismatch"
    WORKSPACE_CHANGED = "workspace_changed"
    RESUME_UNSUPPORTED = "resume_unsupported"
    INVALID_STATE = "invalid_session_state"
    INVALID_OUTPUT = "invalid_codex_output"


class CodexSessionError(RuntimeError):
    failure_category = FailureCategory.UNAVAILABLE

    def __init__(self, message: str, *, receipt: "InvocationReceipt | None" = None) -> None:
        super().__init__(message)
        self.receipt = receipt


class CodexNotInstalled(CodexSessionError):
    failure_category = FailureCategory.NOT_INSTALLED


class CodexNotAuthenticated(CodexSessionError):
    failure_category = FailureCategory.NOT_AUTHENTICATED


class CodexUnavailable(CodexSessionError):
    failure_category = FailureCategory.UNAVAILABLE


class CodexLimitReached(CodexSessionError):
    failure_category = FailureCategory.LIMIT_REACHED


class CodexInterrupted(CodexSessionError):
    failure_category = FailureCategory.INTERRUPTED


class CodexSessionBusy(CodexSessionError):
    failure_category = FailureCategory.INVALID_STATE


class CodexSessionMismatch(CodexSessionError):
    failure_category = FailureCategory.SESSION_MISMATCH


class WorkspaceMismatch(CodexSessionError):
    failure_category = FailureCategory.WORKSPACE_MISMATCH


class WorkspaceChanged(CodexSessionError):
    failure_category = FailureCategory.WORKSPACE_CHANGED


class ResumeUnsupported(CodexSessionError):
    failure_category = FailureCategory.RESUME_UNSUPPORTED


class InvalidSessionState(CodexSessionError):
    failure_category = FailureCategory.INVALID_STATE


class CorruptSessionState(CodexSessionError):
    failure_category = FailureCategory.INVALID_STATE


class IncompatibleSessionState(CorruptSessionState):
    pass


class InvalidCodexOutput(CodexSessionError):
    failure_category = FailureCategory.INVALID_OUTPUT


class SessionPersistenceError(CodexSessionError):
    failure_category = FailureCategory.INVALID_STATE


@dataclass(frozen=True)
class FailureState:
    category: FailureCategory
    occurred_at: datetime


@dataclass(frozen=True)
class InvocationReceipt:
    receipt_schema_version: int
    controller_session_id: str
    codex_session_id: str | None
    operation_type: CodexOperation
    started_at: datetime
    finished_at: datetime
    resolved_executable: str
    codex_version: str
    workspace_root: str
    workspace_fingerprint_before: str
    workspace_fingerprint_after: str | None
    input_unchanged: bool
    sandbox_mode: str
    process_exit_status: int | None
    structured_output_valid: bool
    output_artifact_fingerprint: str | None
    failure_category: FailureCategory | None
    resume_attempted: bool
    process_started: bool
    new_codex_session_created: bool

    @property
    def succeeded(self) -> bool:
        return (
            self.failure_category is None
            and self.process_exit_status == 0
            and self.structured_output_valid
            and self.input_unchanged
        )


@dataclass(frozen=True)
class CodexControllerSession:
    schema_version: int
    controller_session_id: str
    codex_session_id: str | None
    codex_executable: str
    codex_version: str
    workspace_root: str
    workspace_fingerprint: str
    approved_workspace_root: str | None
    approved_workspace_fingerprint: str | None
    phase: SessionPhase
    availability: CodexAvailability
    created_at: datetime
    updated_at: datetime
    resume_supported: bool
    last_successful_invocation_receipt: InvocationReceipt | None
    last_invocation_receipt: InvocationReceipt | None
    last_explicit_failure: FailureState | None
    sanitized_error_code: str | None
    codex_process_active: bool


@dataclass(frozen=True)
class CodexOperationRequest:
    prompt: str
    output_schema: Mapping[str, object]
    timeout_seconds: float = 300.0


@dataclass(frozen=True)
class CodexOperationResult:
    session: CodexControllerSession
    receipt: InvocationReceipt
    structured_output: object


class SessionStore(Protocol):
    def create(self, session: CodexControllerSession) -> None: ...

    def load(self, controller_session_id: str) -> CodexControllerSession: ...

    def save(self, session: CodexControllerSession) -> None: ...


class JsonSessionStore:
    """Caller-located deterministic JSON store with atomic same-directory writes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def create(self, session: CodexControllerSession) -> None:
        with self._lock:
            document = self._read_document()
            sessions = document["sessions"]
            if session.controller_session_id in sessions:
                raise InvalidSessionState("Controller session already exists.")
            sessions[session.controller_session_id] = _session_to_dict(session)
            _validate_session_collection(sessions)
            self._write_document(document)

    def load(self, controller_session_id: str) -> CodexControllerSession:
        with self._lock:
            document = self._read_document()
            raw = document["sessions"].get(controller_session_id)
            if raw is None:
                raise CodexSessionMismatch("Controller session ID does not match retained state.")
            return _session_from_dict(raw)

    def save(self, session: CodexControllerSession) -> None:
        with self._lock:
            document = self._read_document()
            sessions = document["sessions"]
            if session.controller_session_id not in sessions:
                raise CodexSessionMismatch("Controller session ID does not match retained state.")
            sessions[session.controller_session_id] = _session_to_dict(session)
            _validate_session_collection(sessions)
            self._write_document(document)

    def _read_document(self) -> dict[str, object]:
        if not self.path.exists():
            return {"schema_version": SESSION_SCHEMA_VERSION, "sessions": {}}
        if self.path.is_symlink() or not self.path.is_file():
            raise CorruptSessionState("Session store path is not a regular file.")
        try:
            decoded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorruptSessionState("Session state is corrupt.") from exc
        if not isinstance(decoded, dict) or set(decoded) != {"schema_version", "sessions"}:
            raise CorruptSessionState("Session state has an invalid shape.")
        if decoded["schema_version"] != SESSION_SCHEMA_VERSION:
            raise IncompatibleSessionState("Session state schema version is incompatible.")
        if not isinstance(decoded["sessions"], dict):
            raise CorruptSessionState("Session collection is invalid.")
        _validate_session_collection(decoded["sessions"])
        return decoded

    def _write_document(self, document: Mapping[str, object]) -> None:
        parent = self.path.parent.resolve()
        if not parent.is_dir() or self.path.parent.is_symlink():
            raise SessionPersistenceError("Session store parent is unavailable.")
        temporary = parent / f".{self.path.name}.tmp-{uuid.uuid4().hex}"
        try:
            temporary.write_text(
                json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            temporary.replace(self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise SessionPersistenceError("Session state could not be persisted atomically.") from exc


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise InvalidSessionState("Session timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise CorruptSessionState("Session timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorruptSessionState("Session timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise CorruptSessionState("Session timestamp is invalid.")
    return parsed.astimezone(timezone.utc)


def _failure_to_dict(value: FailureState | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {"category": value.category.value, "occurred_at": _iso(value.occurred_at)}


def _failure_from_dict(value: object) -> FailureState | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"category", "occurred_at"}:
        raise CorruptSessionState("Retained failure state is invalid.")
    try:
        category = FailureCategory(value["category"])
    except (ValueError, TypeError) as exc:
        raise CorruptSessionState("Retained failure category is invalid.") from exc
    return FailureState(category, _datetime(value["occurred_at"]))


def _receipt_to_dict(value: InvocationReceipt | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "receipt_schema_version": value.receipt_schema_version,
        "controller_session_id": value.controller_session_id,
        "codex_session_id": value.codex_session_id,
        "operation_type": value.operation_type.value,
        "started_at": _iso(value.started_at),
        "finished_at": _iso(value.finished_at),
        "resolved_executable": value.resolved_executable,
        "codex_version": value.codex_version,
        "workspace_root": value.workspace_root,
        "workspace_fingerprint_before": value.workspace_fingerprint_before,
        "workspace_fingerprint_after": value.workspace_fingerprint_after,
        "input_unchanged": value.input_unchanged,
        "sandbox_mode": value.sandbox_mode,
        "process_exit_status": value.process_exit_status,
        "structured_output_valid": value.structured_output_valid,
        "output_artifact_fingerprint": value.output_artifact_fingerprint,
        "failure_category": None if value.failure_category is None else value.failure_category.value,
        "resume_attempted": value.resume_attempted,
        "process_started": value.process_started,
        "new_codex_session_created": value.new_codex_session_created,
    }


_RECEIPT_FIELDS = {
    "receipt_schema_version", "controller_session_id", "codex_session_id",
    "operation_type", "started_at", "finished_at", "resolved_executable",
    "codex_version", "workspace_root", "workspace_fingerprint_before",
    "workspace_fingerprint_after", "input_unchanged", "sandbox_mode",
    "process_exit_status", "structured_output_valid", "output_artifact_fingerprint",
    "failure_category", "resume_attempted", "process_started",
    "new_codex_session_created",
}


def _receipt_from_dict(value: object) -> InvocationReceipt | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS:
        raise CorruptSessionState("Invocation receipt is invalid.")
    if value["receipt_schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise IncompatibleSessionState("Invocation receipt schema version is incompatible.")
    try:
        operation = CodexOperation(value["operation_type"])
        category = (
            None if value["failure_category"] is None
            else FailureCategory(value["failure_category"])
        )
        return InvocationReceipt(
            receipt_schema_version=RECEIPT_SCHEMA_VERSION,
            controller_session_id=_string(value["controller_session_id"]),
            codex_session_id=_optional_string(value["codex_session_id"]),
            operation_type=operation,
            started_at=_datetime(value["started_at"]),
            finished_at=_datetime(value["finished_at"]),
            resolved_executable=_string(value["resolved_executable"]),
            codex_version=_string(value["codex_version"]),
            workspace_root=_string(value["workspace_root"]),
            workspace_fingerprint_before=_hash(value["workspace_fingerprint_before"]),
            workspace_fingerprint_after=_optional_hash(value["workspace_fingerprint_after"]),
            input_unchanged=_boolean(value["input_unchanged"]),
            sandbox_mode=_string(value["sandbox_mode"]),
            process_exit_status=_optional_int(value["process_exit_status"]),
            structured_output_valid=_boolean(value["structured_output_valid"]),
            output_artifact_fingerprint=_optional_hash(value["output_artifact_fingerprint"]),
            failure_category=category,
            resume_attempted=_boolean(value["resume_attempted"]),
            process_started=_boolean(value["process_started"]),
            new_codex_session_created=_boolean(value["new_codex_session_created"]),
        )
    except (ValueError, TypeError) as exc:
        raise CorruptSessionState("Invocation receipt contains invalid values.") from exc


_SESSION_FIELDS = {
    "schema_version", "controller_session_id", "codex_session_id",
    "codex_executable", "codex_version", "workspace_root",
    "workspace_fingerprint", "approved_workspace_root",
    "approved_workspace_fingerprint", "phase", "availability", "created_at",
    "updated_at", "resume_supported", "last_successful_invocation_receipt",
    "last_invocation_receipt", "last_explicit_failure", "sanitized_error_code",
    "codex_process_active",
}


def _session_to_dict(value: CodexControllerSession) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "controller_session_id": value.controller_session_id,
        "codex_session_id": value.codex_session_id,
        "codex_executable": value.codex_executable,
        "codex_version": value.codex_version,
        "workspace_root": value.workspace_root,
        "workspace_fingerprint": value.workspace_fingerprint,
        "approved_workspace_root": value.approved_workspace_root,
        "approved_workspace_fingerprint": value.approved_workspace_fingerprint,
        "phase": value.phase.value,
        "availability": value.availability.value,
        "created_at": _iso(value.created_at),
        "updated_at": _iso(value.updated_at),
        "resume_supported": value.resume_supported,
        "last_successful_invocation_receipt": _receipt_to_dict(
            value.last_successful_invocation_receipt
        ),
        "last_invocation_receipt": _receipt_to_dict(value.last_invocation_receipt),
        "last_explicit_failure": _failure_to_dict(value.last_explicit_failure),
        "sanitized_error_code": value.sanitized_error_code,
        "codex_process_active": value.codex_process_active,
    }


def _session_from_dict(value: object) -> CodexControllerSession:
    if not isinstance(value, dict) or set(value) != _SESSION_FIELDS:
        raise CorruptSessionState("Controller session has an invalid shape.")
    if value["schema_version"] != SESSION_SCHEMA_VERSION:
        raise IncompatibleSessionState("Controller session schema version is incompatible.")
    try:
        session = CodexControllerSession(
            schema_version=SESSION_SCHEMA_VERSION,
            controller_session_id=_uuid_string(value["controller_session_id"]),
            codex_session_id=_optional_uuid_string(value["codex_session_id"]),
            codex_executable=_string(value["codex_executable"]),
            codex_version=_string(value["codex_version"]),
            workspace_root=_string(value["workspace_root"]),
            workspace_fingerprint=_hash(value["workspace_fingerprint"]),
            approved_workspace_root=_optional_string(value["approved_workspace_root"]),
            approved_workspace_fingerprint=_optional_hash(
                value["approved_workspace_fingerprint"]
            ),
            phase=SessionPhase(value["phase"]),
            availability=CodexAvailability(value["availability"]),
            created_at=_datetime(value["created_at"]),
            updated_at=_datetime(value["updated_at"]),
            resume_supported=_boolean(value["resume_supported"]),
            last_successful_invocation_receipt=_receipt_from_dict(
                value["last_successful_invocation_receipt"]
            ),
            last_invocation_receipt=_receipt_from_dict(value["last_invocation_receipt"]),
            last_explicit_failure=_failure_from_dict(value["last_explicit_failure"]),
            sanitized_error_code=_optional_string(value["sanitized_error_code"]),
            codex_process_active=_boolean(value["codex_process_active"]),
        )
    except (ValueError, TypeError) as exc:
        raise CorruptSessionState("Controller session contains invalid values.") from exc
    if (session.approved_workspace_root is None) != (
        session.approved_workspace_fingerprint is None
    ):
        raise CorruptSessionState("Approved workspace binding is incomplete.")
    for receipt in (
        session.last_successful_invocation_receipt,
        session.last_invocation_receipt,
    ):
        if receipt is not None and receipt.controller_session_id != session.controller_session_id:
            raise CorruptSessionState("Invocation receipt belongs to another session.")
    if (
        session.last_successful_invocation_receipt is not None
        and not session.last_successful_invocation_receipt.succeeded
    ):
        raise CorruptSessionState("Last successful receipt is not successful.")
    return session


def _validate_session_collection(value: Mapping[object, object]) -> None:
    codex_owners: dict[str, str] = {}
    for raw_id, raw_session in value.items():
        if not isinstance(raw_id, str):
            raise CorruptSessionState("Controller session key is invalid.")
        session = _session_from_dict(raw_session)
        if raw_id != session.controller_session_id:
            raise CorruptSessionState("Controller session key does not match its record.")
        if session.codex_session_id is None:
            continue
        owner = codex_owners.get(session.codex_session_id)
        if owner is not None and owner != session.controller_session_id:
            raise CorruptSessionState(
                "Codex session identity is assigned to multiple controller sessions."
            )
        codex_owners[session.codex_session_id] = session.controller_session_id


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _uuid_string(value: object) -> str:
    text = _string(value)
    return str(uuid.UUID(text))


def _optional_uuid_string(value: object) -> str | None:
    return None if value is None else _uuid_string(value)


def _hash(value: object) -> str:
    text = _string(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError
    return text


def _optional_hash(value: object) -> str | None:
    return None if value is None else _hash(value)


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError
    return value


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


class CodexSessionController:
    """Persisted workflow lifecycle around exactly one local Codex CLI adapter."""

    def __init__(
        self,
        store: SessionStore,
        process_adapter: CodexCliProcessAdapter,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        self.store = store
        self.process_adapter = process_adapter
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or uuid.uuid4
        self._active_sessions: set[str] = set()
        self._active_lock = threading.Lock()

    @classmethod
    def with_local_codex(
        cls,
        store: SessionStore,
        *,
        executable: str = "codex",
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], uuid.UUID] | None = None,
    ) -> "CodexSessionController":
        try:
            adapter = CodexCliProcessAdapter.discover(executable)
        except FileNotFoundError as exc:
            raise CodexNotInstalled("Codex executable is not installed.") from exc
        except CodexProcessBoundaryError as exc:
            raise CodexUnavailable("Codex capability discovery failed.") from exc
        return cls(store, adapter, clock=clock, id_factory=id_factory)

    def create_session(self, workspace_root: Path) -> CodexControllerSession:
        root = _resolved_workspace(workspace_root)
        fingerprint = workspace_fingerprint(root)
        now = self._now()
        session = CodexControllerSession(
            schema_version=SESSION_SCHEMA_VERSION,
            controller_session_id=str(self._id_factory()),
            codex_session_id=None,
            codex_executable=str(self.process_adapter.resolved_executable),
            codex_version=self.process_adapter.version,
            workspace_root=str(root),
            workspace_fingerprint=fingerprint,
            approved_workspace_root=None,
            approved_workspace_fingerprint=None,
            phase=SessionPhase.READY,
            availability=CodexAvailability.AVAILABLE,
            created_at=now,
            updated_at=now,
            resume_supported=self.process_adapter.capabilities.resume_supported,
            last_successful_invocation_receipt=None,
            last_invocation_receipt=None,
            last_explicit_failure=None,
            sanitized_error_code=None,
            codex_process_active=False,
        )
        self.store.create(session)
        return session

    def get_session(self, controller_session_id: str) -> CodexControllerSession:
        return self.store.load(controller_session_id)

    def start_investigation(
        self,
        controller_session_id: str,
        workspace_root: Path,
        request: CodexOperationRequest,
    ) -> CodexOperationResult:
        return self._execute(
            controller_session_id,
            workspace_root,
            request,
            operation=CodexOperation.INVESTIGATION,
            allowed_phases={SessionPhase.READY},
            success_phase=SessionPhase.INVESTIGATING,
            resume_session_id=None,
        )

    def record_awaiting_human_review(
        self, controller_session_id: str
    ) -> CodexControllerSession:
        return self._transition(
            controller_session_id,
            {SessionPhase.INVESTIGATING},
            SessionPhase.AWAITING_HUMAN_REVIEW,
        )

    def bind_approved_workspace(
        self,
        controller_session_id: str,
        approved_workspace_root: Path,
        approved_workspace_fingerprint: str,
    ) -> CodexControllerSession:
        session = self.store.load(controller_session_id)
        self._require_idle(session)
        if session.phase is not SessionPhase.AWAITING_HUMAN_REVIEW:
            raise InvalidSessionState("Approved workspace binding requires human-review state.")
        approved = _resolved_workspace(approved_workspace_root)
        original = Path(session.workspace_root)
        if approved == original or original.is_relative_to(approved):
            raise WorkspaceMismatch("Approved workspace cannot widen or equal the original workspace.")
        actual = workspace_fingerprint(approved)
        if actual != approved_workspace_fingerprint:
            raise WorkspaceChanged("Approved workspace fingerprint does not match its contents.")
        updated = replace(
            session,
            approved_workspace_root=str(approved),
            approved_workspace_fingerprint=actual,
            phase=SessionPhase.APPROVED,
            updated_at=self._now(),
            last_explicit_failure=None,
            sanitized_error_code=None,
        )
        self.store.save(updated)
        return updated

    def start_reporting(
        self,
        controller_session_id: str,
        approved_workspace_root: Path,
        request: CodexOperationRequest,
    ) -> CodexOperationResult:
        return self._execute(
            controller_session_id,
            approved_workspace_root,
            request,
            operation=CodexOperation.REPORT,
            allowed_phases={SessionPhase.APPROVED},
            success_phase=SessionPhase.REPORTING,
            resume_session_id=None,
        )

    def enter_conversational_phase(
        self, controller_session_id: str
    ) -> CodexControllerSession:
        return self._transition(
            controller_session_id,
            {SessionPhase.REPORTING},
            SessionPhase.CONVERSATIONAL,
        )

    def complete_session(self, controller_session_id: str) -> CodexControllerSession:
        return self._transition(
            controller_session_id,
            {
                SessionPhase.INVESTIGATING,
                SessionPhase.REPORTING,
                SessionPhase.CONVERSATIONAL,
            },
            SessionPhase.COMPLETED,
        )

    def resume_session(
        self,
        controller_session_id: str,
        codex_session_id: str,
        workspace_root: Path,
        request: CodexOperationRequest,
    ) -> CodexOperationResult:
        session = self.store.load(controller_session_id)
        if not session.resume_supported:
            receipt = self._record_preflight_failure(
                session,
                FailureCategory.RESUME_UNSUPPORTED,
                CodexOperation.RESUME,
                _session_bound_root(session),
                resume_attempted=True,
            )
            raise ResumeUnsupported(
                "Codex resume is unsupported by the validated CLI boundary.",
                receipt=receipt,
            )
        try:
            normalized = str(uuid.UUID(codex_session_id))
        except ValueError as exc:
            receipt = self._record_preflight_failure(
                session,
                FailureCategory.SESSION_MISMATCH,
                CodexOperation.RESUME,
                _session_bound_root(session),
                resume_attempted=True,
            )
            raise CodexSessionMismatch(
                "Codex session ID is not a genuine UUID.", receipt=receipt
            ) from exc
        if session.codex_session_id is None or session.codex_session_id != normalized:
            receipt = self._record_preflight_failure(
                session,
                FailureCategory.SESSION_MISMATCH,
                CodexOperation.RESUME,
                _session_bound_root(session),
                resume_attempted=True,
            )
            raise CodexSessionMismatch(
                "Codex session ID belongs to another or unknown session.",
                receipt=receipt,
            )
        return self._execute(
            controller_session_id,
            workspace_root,
            request,
            operation=CodexOperation.RESUME,
            allowed_phases={
                SessionPhase.INVESTIGATING,
                SessionPhase.REPORTING,
                SessionPhase.CONVERSATIONAL,
            },
            success_phase=session.phase,
            resume_session_id=normalized,
        )

    def mark_interrupted(self, controller_session_id: str) -> CodexControllerSession:
        return self._mark_availability(
            controller_session_id,
            CodexAvailability.INTERRUPTED,
            FailureCategory.INTERRUPTED,
        )

    def mark_unavailable(self, controller_session_id: str) -> CodexControllerSession:
        return self._mark_availability(
            controller_session_id,
            CodexAvailability.UNAVAILABLE,
            FailureCategory.UNAVAILABLE,
        )

    def _transition(
        self,
        controller_session_id: str,
        allowed_phases: set[SessionPhase],
        phase: SessionPhase,
    ) -> CodexControllerSession:
        session = self.store.load(controller_session_id)
        self._require_idle(session)
        if session.phase not in allowed_phases:
            raise InvalidSessionState("Lifecycle transition is not allowed from this phase.")
        updated = replace(
            session,
            phase=phase,
            updated_at=self._now(),
            last_explicit_failure=None,
            sanitized_error_code=None,
        )
        self.store.save(updated)
        return updated

    def _mark_availability(
        self,
        controller_session_id: str,
        availability: CodexAvailability,
        category: FailureCategory,
    ) -> CodexControllerSession:
        session = self.store.load(controller_session_id)
        self._require_idle(session)
        now = self._now()
        updated = replace(
            session,
            availability=availability,
            updated_at=now,
            last_explicit_failure=FailureState(category, now),
            sanitized_error_code=category.value,
        )
        self.store.save(updated)
        return updated

    def _execute(
        self,
        controller_session_id: str,
        workspace_root: Path,
        request: CodexOperationRequest,
        *,
        operation: CodexOperation,
        allowed_phases: set[SessionPhase],
        success_phase: SessionPhase,
        resume_session_id: str | None,
    ) -> CodexOperationResult:
        self._acquire(controller_session_id)
        try:
            session = self.store.load(controller_session_id)
            self._require_idle(session)
            if session.phase not in allowed_phases:
                raise InvalidSessionState("Codex operation is not allowed from this phase.")
            root, expected_fingerprint = self._validate_workspace_binding(
                session,
                workspace_root,
                operation,
                resume_attempted=resume_session_id is not None,
            )
            _validate_operation_request(request)
            active = replace(
                session,
                codex_process_active=True,
                updated_at=self._now(),
            )
            # The active marker is persisted before launch. If this save fails,
            # no subprocess is created and no later phase can be published.
            self.store.save(active)
            started = self._now()
            try:
                process = self.process_adapter.invoke(
                    CodexInvocationRequest(
                        workspace_root=root,
                        prompt=request.prompt,
                        output_schema=request.output_schema,
                        timeout_seconds=request.timeout_seconds,
                        ephemeral=False,
                        resume_session_id=resume_session_id,
                        allow_api_key_environment=False,
                        expected_workspace_fingerprint=expected_fingerprint,
                    )
                )
            except CodexWorkspaceChangedBeforeLaunch as exc:
                receipt = self._boundary_failure_receipt(
                    active,
                    operation,
                    root,
                    expected_fingerprint,
                    started,
                    FailureCategory.WORKSPACE_CHANGED,
                    resume_session_id is not None,
                )
                failed = self._failed_state(active, receipt)
                self.store.save(failed)
                raise WorkspaceChanged(
                    "Workspace changed before Codex process launch.", receipt=receipt
                ) from exc
            except CodexProcessBoundaryError as exc:
                process = None
                receipt = self._boundary_failure_receipt(
                    active,
                    operation,
                    root,
                    expected_fingerprint,
                    started,
                    FailureCategory.UNAVAILABLE,
                    resume_session_id is not None,
                )
                failed = self._failed_state(active, receipt)
                self.store.save(failed)
                raise CodexUnavailable(
                    "Codex process boundary is unavailable.", receipt=receipt
                ) from exc

            finished = self._now()
            category = _process_failure_category(process)
            structured: object | None = None
            structured_valid = False
            if category is None:
                if not process.input_unchanged:
                    category = FailureCategory.WORKSPACE_CHANGED
                else:
                    try:
                        structured = _validated_output(
                            process.final_response, request.output_schema
                        )
                        structured_valid = True
                    except InvalidCodexOutput:
                        category = FailureCategory.INVALID_OUTPUT
            if (
                category is None
                and resume_session_id is not None
                and process.codex_session_id != resume_session_id
            ):
                category = FailureCategory.SESSION_MISMATCH
                structured_valid = False

            output_fingerprint = (
                hashlib.sha256(process.final_response.encode("utf-8")).hexdigest()
                if process.final_response
                else None
            )
            returned_id = process.codex_session_id
            receipt = InvocationReceipt(
                receipt_schema_version=RECEIPT_SCHEMA_VERSION,
                controller_session_id=session.controller_session_id,
                codex_session_id=returned_id,
                operation_type=operation,
                started_at=started,
                finished_at=finished,
                resolved_executable=session.codex_executable,
                codex_version=session.codex_version,
                workspace_root=str(root),
                workspace_fingerprint_before=process.before_snapshot.fingerprint,
                workspace_fingerprint_after=(
                    None
                    if process.after_snapshot is None
                    else process.after_snapshot.fingerprint
                ),
                input_unchanged=process.input_unchanged,
                sandbox_mode="read-only",
                process_exit_status=process.returncode,
                structured_output_valid=structured_valid,
                output_artifact_fingerprint=output_fingerprint,
                failure_category=category,
                resume_attempted=resume_session_id is not None,
                process_started=process.process_started,
                new_codex_session_created=(
                    resume_session_id is None and returned_id is not None
                ),
            )
            if category is not None:
                failed = self._failed_state(active, receipt)
                self.store.save(failed)
                raise _exception_for_failure(category, receipt)

            retained_codex_id = session.codex_session_id
            if returned_id is not None:
                if retained_codex_id is not None and retained_codex_id != returned_id:
                    failed_receipt = replace(
                        receipt,
                        structured_output_valid=False,
                        failure_category=FailureCategory.SESSION_MISMATCH,
                    )
                    self.store.save(self._failed_state(active, failed_receipt))
                    raise CodexSessionMismatch(
                        "Codex returned an identity assigned to another session.",
                        receipt=failed_receipt,
                    )
                retained_codex_id = returned_id
            succeeded = replace(
                active,
                codex_session_id=retained_codex_id,
                phase=success_phase,
                availability=CodexAvailability.AVAILABLE,
                updated_at=finished,
                last_successful_invocation_receipt=receipt,
                last_invocation_receipt=receipt,
                last_explicit_failure=None,
                sanitized_error_code=None,
                codex_process_active=False,
            )
            self.store.save(succeeded)
            assert structured is not None
            return CodexOperationResult(succeeded, receipt, structured)
        finally:
            self._release(controller_session_id)

    def _validate_workspace_binding(
        self,
        session: CodexControllerSession,
        workspace_root: Path,
        operation: CodexOperation,
        *,
        resume_attempted: bool,
    ) -> tuple[Path, str]:
        root = _resolved_workspace(workspace_root)
        use_approved = session.phase in {
            SessionPhase.APPROVED,
            SessionPhase.REPORTING,
            SessionPhase.CONVERSATIONAL,
        }
        expected_root = (
            session.approved_workspace_root if use_approved else session.workspace_root
        )
        expected_fingerprint = (
            session.approved_workspace_fingerprint
            if use_approved
            else session.workspace_fingerprint
        )
        if expected_root is None or expected_fingerprint is None:
            raise InvalidSessionState("Required workspace binding is absent.")
        if root != Path(expected_root):
            receipt = self._record_preflight_failure(
                session,
                FailureCategory.WORKSPACE_MISMATCH,
                operation,
                root,
                resume_attempted=resume_attempted,
            )
            raise WorkspaceMismatch(
                "Workspace path does not match the controller session.",
                receipt=receipt,
            )
        actual = workspace_fingerprint(root)
        if actual != expected_fingerprint:
            receipt = self._record_preflight_failure(
                session,
                FailureCategory.WORKSPACE_CHANGED,
                operation,
                root,
                resume_attempted=resume_attempted,
            )
            raise WorkspaceChanged(
                "Workspace contents changed after session binding.",
                receipt=receipt,
            )
        return root, expected_fingerprint

    def _record_preflight_failure(
        self,
        session: CodexControllerSession,
        category: FailureCategory,
        operation: CodexOperation,
        root: Path,
        *,
        resume_attempted: bool,
    ) -> InvocationReceipt:
        fingerprint = workspace_fingerprint(root)
        started = self._now()
        receipt = self._boundary_failure_receipt(
            session,
            operation,
            root,
            fingerprint,
            started,
            category,
            resume_attempted,
        )
        self.store.save(self._failed_state(session, receipt))
        return receipt

    def _boundary_failure_receipt(
        self,
        session: CodexControllerSession,
        operation: CodexOperation,
        root: Path,
        fingerprint: str,
        started: datetime,
        category: FailureCategory,
        resume_attempted: bool,
    ) -> InvocationReceipt:
        return InvocationReceipt(
            receipt_schema_version=RECEIPT_SCHEMA_VERSION,
            controller_session_id=session.controller_session_id,
            codex_session_id=session.codex_session_id,
            operation_type=operation,
            started_at=started,
            finished_at=self._now(),
            resolved_executable=session.codex_executable,
            codex_version=session.codex_version,
            workspace_root=str(root),
            workspace_fingerprint_before=fingerprint,
            workspace_fingerprint_after=fingerprint,
            input_unchanged=True,
            sandbox_mode="read-only",
            process_exit_status=None,
            structured_output_valid=False,
            output_artifact_fingerprint=None,
            failure_category=category,
            resume_attempted=resume_attempted,
            process_started=False,
            new_codex_session_created=False,
        )

    def _failed_state(
        self,
        session: CodexControllerSession,
        receipt: InvocationReceipt,
    ) -> CodexControllerSession:
        category = receipt.failure_category or FailureCategory.UNAVAILABLE
        availability = {
            FailureCategory.NOT_INSTALLED: CodexAvailability.NOT_INSTALLED,
            FailureCategory.NOT_AUTHENTICATED: CodexAvailability.NOT_AUTHENTICATED,
            FailureCategory.LIMIT_REACHED: CodexAvailability.LIMIT_REACHED,
            FailureCategory.INTERRUPTED: CodexAvailability.INTERRUPTED,
            FailureCategory.UNAVAILABLE: CodexAvailability.UNAVAILABLE,
        }.get(category, session.availability)
        return replace(
            session,
            availability=availability,
            updated_at=receipt.finished_at,
            last_invocation_receipt=receipt,
            last_explicit_failure=FailureState(category, receipt.finished_at),
            sanitized_error_code=category.value,
            codex_process_active=False,
        )

    def _acquire(self, controller_session_id: str) -> None:
        with self._active_lock:
            if controller_session_id in self._active_sessions:
                raise CodexSessionBusy("A Codex process is already active for this session.")
            self._active_sessions.add(controller_session_id)

    def _release(self, controller_session_id: str) -> None:
        with self._active_lock:
            self._active_sessions.discard(controller_session_id)

    @staticmethod
    def _require_idle(session: CodexControllerSession) -> None:
        if session.codex_process_active:
            raise CodexSessionBusy("A Codex process is already active for this session.")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise InvalidSessionState("Controller clock must return timezone-aware timestamps.")
        return value.astimezone(timezone.utc)


def _resolved_workspace(value: Path) -> Path:
    unresolved = Path(value)
    try:
        if unresolved.is_symlink():
            raise WorkspaceMismatch("Workspace root cannot be a symbolic link.")
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceMismatch("Workspace root could not be resolved.") from exc
    if not resolved.is_dir():
        raise WorkspaceMismatch("Workspace root must be a directory.")
    return resolved


def _session_bound_root(session: CodexControllerSession) -> Path:
    if (
        session.phase
        in {SessionPhase.APPROVED, SessionPhase.REPORTING, SessionPhase.CONVERSATIONAL}
        and session.approved_workspace_root is not None
    ):
        return Path(session.approved_workspace_root)
    return Path(session.workspace_root)


def _validate_operation_request(request: CodexOperationRequest) -> None:
    if not isinstance(request.prompt, str) or not request.prompt.strip():
        raise InvalidSessionState("Codex prompt must be non-empty.")
    if request.timeout_seconds <= 0:
        raise InvalidSessionState("Codex timeout must be positive.")
    if not isinstance(request.output_schema, Mapping):
        raise InvalidSessionState("Codex output schema must be an object.")
    _validate_schema_contract(request.output_schema)
    if request.output_schema.get("type") != "object":
        raise InvalidSessionState("Codex output schema root must be an object.")


def _validate_schema_contract(schema: Mapping[str, object]) -> None:
    allowed = {
        "type", "properties", "required", "additionalProperties", "items",
        "enum", "const", "minLength", "minItems", "maxItems",
    }
    if not set(schema).issubset(allowed):
        raise InvalidSessionState("Codex output schema uses unsupported validation keywords.")
    schema_type = schema.get("type")
    if schema_type not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise InvalidSessionState("Codex output schema has an unsupported type.")
    if "enum" in schema and not isinstance(schema["enum"], list):
        raise InvalidSessionState("Codex output schema enum must be an array.")
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, Mapping) or not all(
            isinstance(key, str) and isinstance(item, Mapping)
            for key, item in properties.items()
        ):
            raise InvalidSessionState("Codex object schema properties are invalid.")
        if not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            raise InvalidSessionState("Codex object schema required list is invalid.")
        if not set(required).issubset(properties):
            raise InvalidSessionState("Codex object schema requires unknown properties.")
        if schema.get("additionalProperties", True) is not False:
            raise InvalidSessionState("Codex object schema must reject additional properties.")
        for child in properties.values():
            _validate_schema_contract(child)
    if schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise InvalidSessionState("Codex array schema must define item validation.")
        _validate_schema_contract(items)


def _validated_output(final_response: str, schema: Mapping[str, object]) -> object:
    if not final_response:
        raise InvalidCodexOutput("Codex did not emit structured output.")
    try:
        decoded = json.loads(final_response)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise InvalidCodexOutput("Codex output is not strict JSON.") from exc
    try:
        _validate_value(decoded, schema, "$")
    except ValueError as exc:
        raise InvalidCodexOutput("Codex output does not match the required schema.") from exc
    return decoded


def _validate_value(value: object, schema: Mapping[str, object], path: str) -> None:
    expected = schema["type"]
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[str(expected)]
    if not matches:
        raise ValueError(path)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(path)
    if "const" in schema and value != schema["const"]:
        raise ValueError(path)
    if expected == "string" and len(value) < int(schema.get("minLength", 0)):  # type: ignore[arg-type]
        raise ValueError(path)
    if expected == "object":
        assert isinstance(value, dict)
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        assert isinstance(properties, Mapping)
        if not set(required).issubset(value):
            raise ValueError(path)
        if schema.get("additionalProperties") is False and not set(value).issubset(properties):
            raise ValueError(path)
        for key, child in properties.items():
            if key in value:
                assert isinstance(child, Mapping)
                _validate_value(value[key], child, f"{path}.{key}")
    if expected == "array":
        assert isinstance(value, list)
        minimum = int(schema.get("minItems", 0))
        maximum = schema.get("maxItems")
        if len(value) < minimum or (maximum is not None and len(value) > int(maximum)):
            raise ValueError(path)
        items = schema["items"]
        assert isinstance(items, Mapping)
        for index, item in enumerate(value):
            _validate_value(item, items, f"{path}[{index}]")


def _process_failure_category(result: CodexProcessResult) -> FailureCategory | None:
    if result.interrupted:
        return FailureCategory.INTERRUPTED
    if result.timed_out:
        return FailureCategory.UNAVAILABLE
    if result.launch_error_type in {"FileNotFoundError", "WinError2"}:
        return FailureCategory.NOT_INSTALLED
    if result.launch_error_type is not None:
        return FailureCategory.UNAVAILABLE
    if result.returncode == 0:
        return None
    sanitized = f"{result.stderr}\n{result.stdout}".casefold()
    if any(
        marker in sanitized
        for marker in (
            "not logged in", "authentication required", "please run codex login",
            "unauthorized", "invalid authentication",
        )
    ):
        return FailureCategory.NOT_AUTHENTICATED
    if any(
        marker in sanitized
        for marker in ("usage limit", "quota exceeded", "rate limit exceeded")
    ):
        return FailureCategory.LIMIT_REACHED
    if result.returncode in {-2, -1073741510, 3221225786}:
        return FailureCategory.INTERRUPTED
    return FailureCategory.UNAVAILABLE


def _exception_for_failure(
    category: FailureCategory, receipt: InvocationReceipt
) -> CodexSessionError:
    exception_type: type[CodexSessionError] = {
        FailureCategory.NOT_INSTALLED: CodexNotInstalled,
        FailureCategory.NOT_AUTHENTICATED: CodexNotAuthenticated,
        FailureCategory.UNAVAILABLE: CodexUnavailable,
        FailureCategory.LIMIT_REACHED: CodexLimitReached,
        FailureCategory.INTERRUPTED: CodexInterrupted,
        FailureCategory.SESSION_MISMATCH: CodexSessionMismatch,
        FailureCategory.WORKSPACE_CHANGED: WorkspaceChanged,
        FailureCategory.INVALID_OUTPUT: InvalidCodexOutput,
    }.get(category, CodexUnavailable)
    return exception_type(
        f"Codex operation failed closed with {category.value}.",
        receipt=receipt,
    )
