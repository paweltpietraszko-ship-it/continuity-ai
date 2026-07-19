"""Shared fail-closed process boundary for the locally installed Codex CLI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


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
    try:
        if unresolved.is_symlink():
            raise CodexProcessBoundaryError("Workspace root cannot be a symbolic link.")
        resolved = unresolved.resolve(strict=True)
    except OSError as exc:
        raise CodexProcessBoundaryError("Workspace root could not be resolved.") from exc
    if not resolved.is_dir():
        raise CodexProcessBoundaryError("Workspace root must be a directory.")

    entries: list[WorkspaceEntry] = []
    try:
        for path in sorted(resolved.rglob("*"), key=lambda item: item.relative_to(resolved).as_posix()):
            relative = path.relative_to(resolved).as_posix()
            if path.is_symlink():
                raise CodexProcessBoundaryError("Workspace cannot contain symbolic links.")
            stat = path.stat()
            if path.is_dir():
                entries.append(
                    WorkspaceEntry(relative, "directory", None, 0, stat.st_mtime_ns, stat.st_mode)
                )
            elif path.is_file():
                raw = path.read_bytes()
                entries.append(
                    WorkspaceEntry(
                        relative,
                        "file",
                        hashlib.sha256(raw).hexdigest(),
                        len(raw),
                        stat.st_mtime_ns,
                        stat.st_mode,
                    )
                )
            else:
                raise CodexProcessBoundaryError("Workspace contains an unsupported file type.")
    except OSError as exc:
        raise CodexProcessBoundaryError("Workspace snapshot could not be captured.") from exc

    canonical = json.dumps(
        [entry.fingerprint_value() for entry in entries],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return WorkspaceSnapshot(tuple(entries), hashlib.sha256(canonical).hexdigest())


def workspace_fingerprint(root: Path) -> str:
    return capture_workspace(root).fingerprint


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
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.executable = executable
        self.resolved_executable = resolved_executable
        self.version = version
        self.capabilities = capabilities
        self._runner = process_runner or subprocess.run

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
        resolved = Path(resolved_name).resolve()

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
        return cls(
            executable,
            resolved_executable=resolved,
            version=version,
            capabilities=capabilities,
            process_runner=process_runner,
        )

    @classmethod
    def for_legacy_spike(
        cls,
        executable: str,
        *,
        process_runner: ProcessRunner | None = None,
    ) -> "CodexCliProcessAdapter":
        """Keep the spike's command-name resolution and injected runner contract."""

        resolved_name = shutil.which(executable) or executable
        return cls(
            executable,
            resolved_executable=Path(resolved_name).resolve(),
            version="unverified-legacy-spike",
            capabilities=CodexCliCapabilities(True, False, False, False, False),
            process_runner=process_runner,
        )

    def invoke(self, request: CodexInvocationRequest) -> CodexProcessResult:
        if request.timeout_seconds <= 0:
            raise CodexProcessBoundaryError("Codex timeout must be positive.")
        workspace = Path(request.workspace_root).resolve(strict=True)
        before = capture_workspace(workspace)
        if (
            request.expected_workspace_fingerprint is not None
            and before.fingerprint != request.expected_workspace_fingerprint
        ):
            raise CodexWorkspaceChangedBeforeLaunch(
                "Workspace changed before Codex process launch."
            )
        environment = codex_environment(
            workspace,
            allow_api_key=request.allow_api_key_environment,
            excluded_paths=request.excluded_environment_paths,
        )
        completed: subprocess.CompletedProcess[str] | None = None
        timed_out = False
        interrupted = False
        launch_error_type: str | None = None
        final_response = ""

        with tempfile.TemporaryDirectory(prefix="continuity-codex-") as temp_name:
            temporary_root = Path(temp_name).resolve()
            schema_path = temporary_root / "response.schema.json"
            response_path = temporary_root / "final-response.json"
            schema_path.write_text(
                json.dumps(request.output_schema, indent=2, sort_keys=True, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            command = self._build_command(request, workspace, schema_path, response_path)
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
                self.executable,
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
            self.executable,
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
