"""Durable operation identity and OS-backed liveness for Codex recovery."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class OperationLiveness(str, Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNKNOWN = "unknown"


class OperationStage(str, Enum):
    RESERVED = "reserved"
    LAUNCHING = "launching"
    RUNNING = "running"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ProcessIdentity:
    """PID plus an OS creation token, preventing PID-reuse confusion."""

    pid: int
    creation_token: str


@dataclass(frozen=True)
class ActiveCodexOperation:
    operation_id: str
    controller_session_id: str
    operation_type: str
    stage: OperationStage
    owner_process: ProcessIdentity
    codex_process: ProcessIdentity | None
    reserved_at: datetime


@dataclass(frozen=True)
class OperationRecoveryEvent:
    event_id: str
    controller_session_id: str
    operation_id: str
    recovered_at: datetime
    observed_liveness: OperationLiveness
    abandoned_stage: OperationStage
    sanitized_error_code: str


class ProcessIdentityError(RuntimeError):
    """A stable OS process identity could not be captured."""


class ProcessLivenessVerifier(Protocol):
    def check(self, identity: ProcessIdentity) -> OperationLiveness: ...


class OsProcessLivenessVerifier:
    """Verify a PID and creation token using Windows or Linux OS state."""

    def check(self, identity: ProcessIdentity) -> OperationLiveness:
        if identity.pid <= 0 or not identity.creation_token:
            return OperationLiveness.UNKNOWN
        if sys.platform == "win32":
            return _windows_process_liveness(identity)
        if sys.platform.startswith("linux"):
            return _linux_process_liveness(identity)
        return OperationLiveness.UNKNOWN


def capture_process_identity(pid: int | None = None) -> ProcessIdentity:
    selected_pid = os.getpid() if pid is None else pid
    if selected_pid <= 0:
        raise ProcessIdentityError("Process identity is unavailable.")
    if sys.platform == "win32":
        identity, liveness = _windows_process_state(selected_pid)
    elif sys.platform.startswith("linux"):
        identity, liveness = _linux_process_state(selected_pid)
    else:
        raise ProcessIdentityError("OS process identity is unsupported.")
    if identity is None or liveness is not OperationLiveness.ALIVE:
        raise ProcessIdentityError("Process identity is unavailable.")
    return identity


def operation_liveness(
    operation: ActiveCodexOperation,
    verifier: ProcessLivenessVerifier,
) -> OperationLiveness:
    """Return liveness without treating age or caller testimony as proof."""

    if operation.stage is OperationStage.RESERVED:
        return verifier.check(operation.owner_process)
    if operation.stage is OperationStage.LAUNCHING:
        owner = verifier.check(operation.owner_process)
        # The controller may have died just after CreateProcess but before the
        # child identity was durably retained. That handoff can never prove
        # death, even when the owner is known dead.
        if owner is OperationLiveness.ALIVE:
            return OperationLiveness.ALIVE
        return OperationLiveness.UNKNOWN
    if operation.codex_process is None:
        return OperationLiveness.UNKNOWN
    return verifier.check(operation.codex_process)


def _linux_process_liveness(identity: ProcessIdentity) -> OperationLiveness:
    observed, liveness = _linux_process_state(identity.pid)
    if liveness is not OperationLiveness.ALIVE:
        return liveness
    if observed is None:
        return OperationLiveness.UNKNOWN
    if observed.creation_token != identity.creation_token:
        return OperationLiveness.DEAD
    return OperationLiveness.ALIVE


def _linux_process_state(
    pid: int,
) -> tuple[ProcessIdentity | None, OperationLiveness]:
    path = f"/proc/{pid}/stat"
    try:
        with open(path, "r", encoding="ascii") as process_stat:
            raw = process_stat.read()
    except FileNotFoundError:
        return None, OperationLiveness.DEAD
    except (OSError, UnicodeError):
        return None, OperationLiveness.UNKNOWN
    closing = raw.rfind(")")
    if closing < 0:
        return None, OperationLiveness.UNKNOWN
    fields = raw[closing + 2 :].split()
    if len(fields) <= 19:
        return None, OperationLiveness.UNKNOWN
    state = fields[0]
    if state in {"Z", "X"}:
        return None, OperationLiveness.DEAD
    token = fields[19]
    if not token.isdigit():
        return None, OperationLiveness.UNKNOWN
    return ProcessIdentity(pid, f"linux-procfs:{token}"), OperationLiveness.ALIVE


def _windows_process_liveness(identity: ProcessIdentity) -> OperationLiveness:
    observed, liveness = _windows_process_state(identity.pid)
    if liveness is not OperationLiveness.ALIVE:
        return liveness
    if observed is None:
        return OperationLiveness.UNKNOWN
    if observed.creation_token != identity.creation_token:
        return OperationLiveness.DEAD
    return OperationLiveness.ALIVE


def _windows_process_state(
    pid: int,
) -> tuple[ProcessIdentity | None, OperationLiveness]:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return None, OperationLiveness.DEAD
        return None, OperationLiveness.UNKNOWN
    try:
        creation = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        exit_code = wintypes.DWORD()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None, OperationLiveness.UNKNOWN
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None, OperationLiveness.UNKNOWN
        exited_at = (exit_time.high << 32) | exit_time.low
        if exited_at != 0 or exit_code.value != still_active:
            return None, OperationLiveness.DEAD
        created = (creation.high << 32) | creation.low
        return (
            ProcessIdentity(pid, f"windows-filetime:{created}"),
            OperationLiveness.ALIVE,
        )
    finally:
        kernel32.CloseHandle(handle)
