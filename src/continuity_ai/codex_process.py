"""Shared fail-closed process boundary for the locally installed Codex CLI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from continuity_ai.codex_operation import ProcessIdentity, capture_process_identity


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]

# Resume is a security-sensitive capability, not a syntax guess. Each version
# must pass the bounded real workspace/schema/same-ID proof before inclusion.
_VERIFIED_RESUME_VERSIONS = frozenset({"codex-cli 0.144.6"})

_BASE_ENVIRONMENT_ALLOWLIST = (
    "APPDATA",
    "CODEX_HOME",
    "COMSPEC",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LOCALAPPDATA",
    "NO_PROXY",
    "PATH",
    "PATHEXT",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
    "XDG_CONFIG_HOME",
)


class CodexProcessBoundaryError(RuntimeError):
    """The Codex process boundary could not be established safely."""


class CodexWorkspaceChangedBeforeLaunch(CodexProcessBoundaryError):
    """The retained workspace fingerprint no longer matches before launch."""


class CodexWorkspaceUnavailableBeforeLaunch(CodexWorkspaceChangedBeforeLaunch):
    """The bound workspace could not be accessed during pre-launch validation."""


class CodexWorkspaceTypeChangedBeforeLaunch(CodexWorkspaceChangedBeforeLaunch):
    """The bound workspace is no longer a directory before launch."""


class CodexWorkspaceLinkSubstitutionBeforeLaunch(CodexWorkspaceChangedBeforeLaunch):
    """The bound workspace was replaced by a link or reparse point."""


@dataclass(frozen=True)
class CodexExecutableIdentity:
    sha256: str
    size: int
    device: int
    inode: int


@dataclass(frozen=True)
class CodexInvocationLifecycle:
    before_launch: Callable[[], None]
    process_started: Callable[[ProcessIdentity], None]
    process_completed: Callable[[], None]


@dataclass(frozen=True)
class WorkspaceEntry:
    relative_path: str
    kind: str
    sha256: str | None
    size: int
    modified_time_ns: int
    mode: int

    def fingerprint_value(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "mode": self.mode,
            "path": self.relative_path,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class WorkspaceSnapshot:
    entries: tuple[WorkspaceEntry, ...]
    fingerprint: str


def capture_workspace(root: Path) -> WorkspaceSnapshot:
    """Hash every path, file byte sequence, and relevant file type in ``root``."""

    unresolved = Path(root)
    resolution_failed = False
    try:
        root_stat = unresolved.lstat()
        if _is_link_or_reparse(root_stat):
            raise CodexProcessBoundaryError("Workspace root cannot be a symbolic link.")
        resolved = unresolved.resolve(strict=True)
    except OSError:
        resolution_failed = True
    if resolution_failed:
        raise CodexProcessBoundaryError("Workspace root could not be resolved.")
    if not resolved.is_dir():
        raise CodexProcessBoundaryError("Workspace root must be a directory.")

    entries: list[WorkspaceEntry] = []
    snapshot_failed = False
    try:
        for path in sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix()):
            relative = path.relative_to(resolved).as_posix()
            path_stat = path.lstat()
            if _is_link_or_reparse(path_stat):
                raise CodexProcessBoundaryError("Workspace cannot contain symbolic links.")
            path_stat = path.stat()
            if path.is_dir():
                entries.append(
                    WorkspaceEntry(
                        relative,
                        "directory",
                        None,
                        0,
                        path_stat.st_mtime_ns,
                        path_stat.st_mode,
                    )
                )
            elif path.is_file():
                raw = path.read_bytes()
                entries.append(
                    WorkspaceEntry(
                        relative,
                        "file",
                        hashlib.sha256(raw).hexdigest(),
                        len(raw),
                        path_stat.st_mtime_ns,
                        path_stat.st_mode,
                    )
                )
            else:
                raise CodexProcessBoundaryError("Workspace contains an unsupported file type.")
    except OSError:
        snapshot_failed = True
    if snapshot_failed:
        raise CodexProcessBoundaryError("Workspace snapshot could not be captured.")

    canonical = json.dumps(
        [entry.fingerprint_value() for entry in entries],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return WorkspaceSnapshot(tuple(entries), hashlib.sha256(canonical).hexdigest())


def workspace_fingerprint(root: Path) -> str:
    return capture_workspace(root).fingerprint


def _is_link_or_reparse(path_stat: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(file_attributes & reparse_flag)


def _workspace_before_launch(root: Path) -> tuple[Path, WorkspaceSnapshot]:
    """Resolve and snapshot one exact non-link directory without leaking OS errors."""

    unresolved = Path(root)
    workspace_unavailable = False
    try:
        before_resolution = unresolved.lstat()
    except OSError:
        workspace_unavailable = True
    if workspace_unavailable:
        raise CodexWorkspaceUnavailableBeforeLaunch(
            "Workspace is unavailable before Codex process launch."
        )
    if _is_link_or_reparse(before_resolution):
        raise CodexWorkspaceLinkSubstitutionBeforeLaunch(
            "Workspace link substitution was rejected before Codex process launch."
        )
    if not stat.S_ISDIR(before_resolution.st_mode):
        raise CodexWorkspaceTypeChangedBeforeLaunch(
            "Workspace is no longer a directory before Codex process launch."
        )
    workspace_unavailable = False
    try:
        resolved = unresolved.resolve(strict=True)
    except OSError:
        workspace_unavailable = True
    if workspace_unavailable:
        raise CodexWorkspaceUnavailableBeforeLaunch(
            "Workspace is unavailable before Codex process launch."
        )
    if resolved != unresolved.absolute():
        raise CodexWorkspaceLinkSubstitutionBeforeLaunch(
            "Workspace link substitution was rejected before Codex process launch."
        )
    validation_failure: str | None = None
    try:
        snapshot = capture_workspace(resolved)
        after_snapshot = unresolved.lstat()
        resolved_after = unresolved.resolve(strict=True)
    except CodexProcessBoundaryError:
        validation_failure = "Workspace validation failed before Codex process launch."
    except OSError:
        validation_failure = "Workspace is unavailable before Codex process launch."
    if validation_failure is not None:
        raise CodexWorkspaceUnavailableBeforeLaunch(validation_failure)
    if _is_link_or_reparse(after_snapshot) or resolved_after != resolved:
        raise CodexWorkspaceLinkSubstitutionBeforeLaunch(
            "Workspace link substitution was rejected before Codex process launch."
        )
    if not stat.S_ISDIR(after_snapshot.st_mode):
        raise CodexWorkspaceTypeChangedBeforeLaunch(
            "Workspace is no longer a directory before Codex process launch."
        )
    if (before_resolution.st_dev, before_resolution.st_ino) != (
        after_snapshot.st_dev,
        after_snapshot.st_ino,
    ):
        raise CodexWorkspaceLinkSubstitutionBeforeLaunch(
            "Workspace identity changed before Codex process launch."
        )
    return resolved, snapshot


@contextmanager
def _invocation_paths(
    output_schema: Mapping[str, object],
) -> Iterator[tuple[Path, Path]]:
    """Create adapter-owned launch artifacts behind a sanitized OS boundary."""

    preparation_failed = False
    try:
        with tempfile.TemporaryDirectory(prefix="continuity-codex-") as temp_name:
            temporary_root = Path(temp_name).resolve()
            schema_path = temporary_root / "response.schema.json"
            response_path = temporary_root / "final-response.json"
            schema_path.write_text(
                json.dumps(output_schema, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            yield schema_path, response_path
    except OSError:
        preparation_failed = True
    if preparation_failed:
        raise CodexProcessBoundaryError(
            "Codex pre-launch boundary preparation failed."
        )


def codex_environment(
    workspace_root: Path,
    *,
    source: Mapping[str, str] | None = None,
    allow_api_key: bool = False,
    excluded_paths: Sequence[Path] = (),
) -> dict[str, str]:
    """Return a narrow environment without inspecting credential values."""

    inherited = os.environ if source is None else source
    allowlist = list(_BASE_ENVIRONMENT_ALLOWLIST)
    if allow_api_key:
        # Compatibility only for the pre-existing one-shot spike. The session
        # controller never enables this application-managed API-key path.
        allowlist.append("OPENAI_API_KEY")
    excluded = [str(Path(path).resolve()).casefold() for path in excluded_paths]
    environment = {
        key: inherited[key]
        for key in allowlist
        if key in inherited
        and inherited[key]
        and not any(value in inherited[key].casefold() for value in excluded)
    }
    environment["NO_COLOR"] = "1"
    return environment


@dataclass(frozen=True)
class CodexCliCapabilities:
    non_interactive_exec: bool
    non_interactive_resume: bool
    resume_output_schema: bool
    resume_workspace_binding: bool
    resume_read_only_sandbox: bool
    resume_verified: bool = False

    @property
    def resume_supported(self) -> bool:
        return all(
            (
                self.non_interactive_resume,
                self.resume_output_schema,
                self.resume_workspace_binding,
                self.resume_read_only_sandbox,
                self.resume_verified,
            )
        )


@dataclass(frozen=True)
class CodexInvocationRequest:
    workspace_root: Path
    prompt: str
    output_schema: Mapping[str, object]
    timeout_seconds: float = 300.0
    ephemeral: bool = False
    resume_session_id: str | None = None
    allow_api_key_environment: bool = False
    excluded_environment_paths: tuple[Path, ...] = ()
    expected_workspace_fingerprint: str | None = None
    lifecycle: CodexInvocationLifecycle | None = None


@dataclass(frozen=True)
class CodexProcessResult:
    command: tuple[str, ...]
    working_directory: Path
    environment_keys: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    final_response: str
    before_snapshot: WorkspaceSnapshot
    after_snapshot: WorkspaceSnapshot | None
    input_unchanged: bool
    process_started: bool
    timed_out: bool
    interrupted: bool
    launch_error_type: str | None
    codex_session_id: str | None


class CodexCliProcessAdapter:
    """The sole subprocess implementation used by Codex-native workflows."""

    def __init__(
        self,
        executable: str,
        *,
        resolved_executable: Path,
        version: str,
        capabilities: CodexCliCapabilities,
        executable_identity: CodexExecutableIdentity | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.executable = executable
        self.resolved_executable = Path(resolved_executable).resolve(strict=True)
        self.version = version
        self.capabilities = capabilities
        self.executable_identity = executable_identity or _executable_identity(
            self.resolved_executable
        )
        self._runner = process_runner

    @classmethod
    def discover(
        cls,
        executable: str = "codex",
        *,
        process_runner: ProcessRunner | None = None,
    ) -> "CodexCliProcessAdapter":
        runner = process_runner or subprocess.run
        resolved_name = shutil.which(executable)
        if resolved_name is None:
            raise FileNotFoundError("Codex executable was not found.")
        resolved = Path(resolved_name).resolve(strict=True)
        identity = _executable_identity(resolved)

        def inspect(*arguments: str) -> str:
            completed = runner(
                [str(resolved), *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30.0,
                check=False,
            )
            if completed.returncode != 0:
                raise CodexProcessBoundaryError("Codex capability discovery failed.")
            return completed.stdout

        version = inspect("--version").strip()
        top_help = inspect("--help")
        exec_help = inspect("exec", "--help")
        resume_help = ""
        if "resume" in exec_help:
            resume_help = inspect("exec", "resume", "--help")
        capabilities = CodexCliCapabilities(
            non_interactive_exec="Run Codex non-interactively" in exec_help,
            non_interactive_resume="Resume a previous session" in resume_help,
            resume_output_schema="--output-schema" in resume_help,
            # Resume accepts global flags before ``exec``; both must be exposed
            # by this exact installed binary before construction is allowed.
            resume_workspace_binding="--cd" in top_help,
            resume_read_only_sandbox="--sandbox" in top_help,
            resume_verified=version in _VERIFIED_RESUME_VERSIONS,
        )
        if _executable_identity(resolved) != identity:
            raise CodexProcessBoundaryError(
                "Codex executable changed during capability discovery."
            )
        return cls(
            executable,
            resolved_executable=resolved,
            version=version,
            capabilities=capabilities,
            executable_identity=identity,
            process_runner=process_runner,
        )

    @classmethod
    def for_legacy_spike(
        cls,
        executable: str,
        *,
        process_runner: ProcessRunner | None = None,
    ) -> "CodexCliProcessAdapter":
        """Keep dynamic discovery and the spike's injected-runner contract."""

        resolved_name = shutil.which(executable)
        if resolved_name is None:
            raise FileNotFoundError("Codex executable was not found.")
        resolved = Path(resolved_name).resolve(strict=True)
        return cls(
            executable,
            resolved_executable=resolved,
            version="unverified-legacy-spike",
            capabilities=CodexCliCapabilities(True, False, False, False, False),
            executable_identity=_executable_identity(resolved),
            process_runner=process_runner,
        )

    def invoke(self, request: CodexInvocationRequest) -> CodexProcessResult:
        if request.timeout_seconds <= 0:
            raise CodexProcessBoundaryError("Codex timeout must be positive.")
        workspace, before = _workspace_before_launch(request.workspace_root)
        if (
            request.expected_workspace_fingerprint is not None
            and before.fingerprint != request.expected_workspace_fingerprint
        ):
            raise CodexWorkspaceChangedBeforeLaunch(
                "Workspace changed before Codex process launch."
            )
        environment_failed = False
        try:
            environment = codex_environment(
                workspace,
                allow_api_key=request.allow_api_key_environment,
                excluded_paths=request.excluded_environment_paths,
            )
        except OSError:
            environment_failed = True
        if environment_failed:
            raise CodexProcessBoundaryError(
                "Codex pre-launch environment validation failed."
            )
        completed: subprocess.CompletedProcess[str] | None = None
        timed_out = False
        interrupted = False
        launch_error_type: str | None = None
        final_response = ""

        with _invocation_paths(request.output_schema) as (schema_path, response_path):
            command = self._build_command(request, workspace, schema_path, response_path)
            try:
                if request.lifecycle is not None:
                    request.lifecycle.before_launch()
                self._revalidate_executable()
                if self._runner is None:
                    completed = self._run_production_process(
                        command, workspace, environment, request
                    )
                else:
                    if request.lifecycle is not None:
                        request.lifecycle.process_started(capture_process_identity())
                    try:
                        completed = self._runner(
                            command,
                            cwd=workspace,
                            env=environment,
                            input=request.prompt,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            timeout=request.timeout_seconds,
                            check=False,
                        )
                    finally:
                        if request.lifecycle is not None:
                            request.lifecycle.process_completed()
            except subprocess.TimeoutExpired:
                timed_out = True
                launch_error_type = "TimeoutExpired"
            except KeyboardInterrupt:
                interrupted = True
                launch_error_type = "KeyboardInterrupt"
            except OSError as exc:
                launch_error_type = type(exc).__name__

            if response_path.is_file() and not response_path.is_symlink():
                try:
                    final_response = response_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    final_response = ""

        try:
            after = capture_workspace(workspace)
        except CodexProcessBoundaryError:
            after = None
        input_unchanged = after == before
        stdout = "" if completed is None else completed.stdout
        return CodexProcessResult(
            command=tuple(command),
            working_directory=workspace,
            environment_keys=tuple(sorted(environment)),
            returncode=None if completed is None else completed.returncode,
            stdout=stdout,
            stderr="" if completed is None else completed.stderr,
            final_response=final_response,
            before_snapshot=before,
            after_snapshot=after,
            input_unchanged=input_unchanged,
            process_started=completed is not None or timed_out or interrupted,
            timed_out=timed_out,
            interrupted=interrupted,
            launch_error_type=launch_error_type,
            codex_session_id=_genuine_thread_id(stdout),
        )

    def _revalidate_executable(self) -> None:
        validation_failed = False
        try:
            current = _executable_identity(self.resolved_executable)
        except (OSError, CodexProcessBoundaryError):
            validation_failed = True
        if validation_failed:
            raise CodexProcessBoundaryError(
                "Codex executable identity validation failed before launch."
            )
        if current != self.executable_identity:
            raise CodexProcessBoundaryError(
                "Codex executable identity changed after capability discovery."
            )

    def _run_production_process(
        self,
        command: list[str],
        workspace: Path,
        environment: Mapping[str, str],
        request: CodexInvocationRequest,
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        lifecycle_started = False
        try:
            if request.lifecycle is not None:
                try:
                    request.lifecycle.process_started(
                        capture_process_identity(process.pid)
                    )
                    lifecycle_started = True
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
            try:
                stdout, stderr = process.communicate(
                    input=request.prompt,
                    timeout=request.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                process.kill()
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(
                    command,
                    request.timeout_seconds,
                    output=stdout,
                    stderr=stderr,
                ) from exc
            except BaseException:
                process.kill()
                process.wait()
                raise
            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        finally:
            if lifecycle_started and request.lifecycle is not None:
                request.lifecycle.process_completed()

    def _build_command(
        self,
        request: CodexInvocationRequest,
        workspace: Path,
        schema_path: Path,
        response_path: Path,
    ) -> list[str]:
        common = [
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(response_path),
            "--json",
        ]
        if request.resume_session_id is None:
            command = [
                str(self.resolved_executable),
                "exec",
                "--sandbox",
                "read-only",
                "--cd",
                str(workspace),
                *common,
            ]
            if request.ephemeral:
                command.append("--ephemeral")
            command.append("-")
            return command
        if not self.capabilities.resume_supported:
            raise CodexProcessBoundaryError("Codex resume boundary is unsupported.")
        return [
            str(self.resolved_executable),
            "--sandbox",
            "read-only",
            "--cd",
            str(workspace),
            "exec",
            "resume",
            *common,
            request.resume_session_id,
            "-",
        ]


def _executable_identity(path: Path) -> CodexExecutableIdentity:
    selected = Path(path)
    before = selected.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(before, "st_file_attributes", 0)
    if selected.is_symlink() or file_attributes & reparse_flag:
        raise CodexProcessBoundaryError(
            "Codex executable cannot be a link or reparse point."
        )
    if not stat.S_ISREG(before.st_mode):
        raise CodexProcessBoundaryError("Codex executable must be a regular file.")
    digest = hashlib.sha256()
    with selected.open("rb") as executable_file:
        for block in iter(lambda: executable_file.read(1024 * 1024), b""):
            digest.update(block)
    after = selected.lstat()
    if (
        before.st_mode != after.st_mode
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or getattr(before, "st_ino", None) != getattr(after, "st_ino", None)
    ):
        raise CodexProcessBoundaryError("Codex executable changed during validation.")
    return CodexExecutableIdentity(
        digest.hexdigest(),
        before.st_size,
        before.st_dev,
        before.st_ino,
    )


def _genuine_thread_id(stdout: str) -> str | None:
    found: set[str] = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "thread.started":
            continue
        candidate = event.get("thread_id")
        if not isinstance(candidate, str):
            continue
        try:
            normalized = str(uuid.UUID(candidate))
        except (ValueError, AttributeError):
            continue
        found.add(normalized)
    return next(iter(found)) if len(found) == 1 else None
