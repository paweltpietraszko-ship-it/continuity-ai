"""Fail-closed, deterministic approved-only workspace materialization."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from continuity_ai.approved_workspace.canonical import (
    canonical_json_bytes,
    normalize_json_value,
    sha256_bytes,
)
from continuity_ai.approved_workspace.contracts import (
    ApprovedArtifactSelection,
    ApprovedHumanAttestation,
    ApprovedWorkspaceMaterializationError,
    ApprovedWorkspaceRequest,
    AttestationApprovalStatus,
    FailureCategory,
    MaterializationReceipt,
    PublicationStatus,
    SourceScopeBinding,
)


SCHEMA_VERSION = "1.0"
APPROVED_ATTESTATIONS_RELATIVE_PATH = Path(
    ".continuity/approved_attestations.json"
)
APPROVED_MANIFEST_RELATIVE_PATH = Path(
    ".continuity/approved_workspace_manifest.json"
)

_READ_CHUNK_SIZE = 1024 * 1024
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_SENSITIVE_ATTESTATION_KEYS = frozenset(
    {
        "api_key",
        "credential",
        "credentials",
        "owner_secret",
        "password",
        "secret",
        "session_key",
    }
)


@dataclass(frozen=True, slots=True)
class _ValidatedAttestation:
    attestation_id: str
    downstream_data: dict[str, Any]
    human_actor_id: str
    approval_reference: str


@dataclass(frozen=True, slots=True)
class _ValidatedRequest:
    source_root: Path
    destination_root: Path
    artifacts: tuple[ApprovedArtifactSelection, ...]
    attestations: tuple[_ValidatedAttestation, ...]
    source_scope_binding: SourceScopeBinding | None


@dataclass(frozen=True, slots=True)
class _MaterializationTestHooks:
    """Narrow deterministic fault hooks; not part of the public package API."""

    after_artifact_copied: Callable[
        [ApprovedArtifactSelection, Path, Path], None
    ] | None = None
    before_publish: Callable[[Path, Path], None] | None = None


def _fail(category: FailureCategory) -> ApprovedWorkspaceMaterializationError:
    return ApprovedWorkspaceMaterializationError(category)


def _is_reparse_point(path: Path, metadata: os.stat_result | None = None) -> bool:
    try:
        item_stat = metadata if metadata is not None else path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(item_stat.st_mode):
        return True
    if getattr(item_stat, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE:
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            return bool(is_junction())
        except OSError:
            return True
    return False


def _require_canonical_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or unicodedata.normalize("NFC", value) != value
        or any(ord(character) < 32 for character in value)
    ):
        raise _fail(FailureCategory.INVALID_INPUT)
    return value


def _require_sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _fail(FailureCategory.INVALID_INPUT)
    return value


def _portable_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _fail(FailureCategory.UNSAFE_PATH)
    if unicodedata.normalize("NFC", value) != value:
        raise _fail(FailureCategory.UNSAFE_PATH)

    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise _fail(FailureCategory.UNSAFE_PATH)

    for part in posix_path.parts:
        if (
            part.endswith((" ", "."))
            or any(character in _WINDOWS_FORBIDDEN_CHARS for character in part)
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_STEMS
        ):
            raise _fail(FailureCategory.UNSAFE_PATH)
    if posix_path.parts[0].casefold() == ".continuity":
        raise _fail(FailureCategory.UNSAFE_PATH)
    return value


def _normalized_absolute_root(value: object) -> Path:
    if not isinstance(value, Path):
        raise _fail(FailureCategory.INVALID_INPUT)
    return Path(os.path.abspath(os.fspath(value)))


def _validate_directory_chain(path: Path, category: FailureCategory) -> None:
    parts = path.parts
    if not parts:
        raise _fail(category)
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise _fail(category) from exc
        if _is_reparse_point(current, metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise _fail(category)


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        common = os.path.commonpath((os.fspath(first), os.fspath(second)))
    except ValueError:
        return False
    normalized_common = os.path.normcase(os.path.abspath(common))
    return normalized_common in {
        os.path.normcase(os.path.abspath(os.fspath(first))),
        os.path.normcase(os.path.abspath(os.fspath(second))),
    }


def _validate_source_item(source_root: Path, relative_path: str) -> Path:
    current = source_root
    path_parts = PurePosixPath(relative_path).parts
    for index, part in enumerate(path_parts):
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError as exc:
            raise _fail(FailureCategory.SOURCE_MISSING) from exc
        except OSError as exc:
            raise _fail(FailureCategory.SOURCE_NOT_REGULAR) from exc
        if _is_reparse_point(current, metadata):
            raise _fail(FailureCategory.SOURCE_LINK)
        is_last = index == len(path_parts) - 1
        if is_last and not stat.S_ISREG(metadata.st_mode):
            raise _fail(FailureCategory.SOURCE_NOT_REGULAR)
        if not is_last and not stat.S_ISDIR(metadata.st_mode):
            raise _fail(FailureCategory.SOURCE_NOT_REGULAR)
    return current


def _sensitive_key_present(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = key.casefold().replace("-", "_").replace(" ", "_")
            if normalized_key in _SENSITIVE_ATTESTATION_KEYS:
                return True
            if _sensitive_key_present(item):
                return True
    elif isinstance(value, list):
        return any(_sensitive_key_present(item) for item in value)
    return False


def _validate_attestation_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _require_canonical_text(key)
            _validate_attestation_keys(item)
    elif isinstance(value, list):
        for item in value:
            _validate_attestation_keys(item)


def _validate_attestation(
    attestation: ApprovedHumanAttestation,
) -> _ValidatedAttestation:
    if not isinstance(attestation, ApprovedHumanAttestation):
        raise _fail(FailureCategory.INVALID_INPUT)
    if attestation.approval_status is not AttestationApprovalStatus.APPROVED:
        raise _fail(FailureCategory.INVALID_INPUT)
    try:
        downstream_data = normalize_json_value(attestation.downstream_data)
    except (TypeError, ValueError) as exc:
        raise _fail(FailureCategory.INVALID_INPUT) from exc
    if not isinstance(downstream_data, dict) or not downstream_data:
        raise _fail(FailureCategory.INVALID_INPUT)
    _validate_attestation_keys(downstream_data)
    if _sensitive_key_present(downstream_data):
        raise _fail(FailureCategory.INVALID_INPUT)
    return _ValidatedAttestation(
        attestation_id=_require_canonical_text(attestation.attestation_id),
        downstream_data=downstream_data,
        human_actor_id=_require_canonical_text(attestation.human_actor_id),
        approval_reference=_require_canonical_text(attestation.approval_reference),
    )


def _validate_binding(
    binding: SourceScopeBinding | None,
    artifacts: tuple[ApprovedArtifactSelection, ...],
) -> SourceScopeBinding | None:
    if binding is None:
        return None
    if not isinstance(binding, SourceScopeBinding) or not isinstance(
        binding.expected_source_fingerprints, tuple
    ):
        raise _fail(FailureCategory.INVALID_INPUT)
    _require_sha256(binding.binding_sha256)
    fingerprints = tuple(
        sorted(_require_sha256(value) for value in binding.expected_source_fingerprints)
    )
    expected_artifact_fingerprints = tuple(
        sorted(artifact.expected_sha256 for artifact in artifacts)
    )
    if fingerprints and fingerprints != expected_artifact_fingerprints:
        raise _fail(FailureCategory.INVALID_INPUT)
    return SourceScopeBinding(
        binding_sha256=binding.binding_sha256,
        expected_source_fingerprints=fingerprints,
    )


def _validate_request(request: ApprovedWorkspaceRequest) -> _ValidatedRequest:
    if not isinstance(request, ApprovedWorkspaceRequest):
        raise _fail(FailureCategory.INVALID_INPUT)
    if not isinstance(request.approved_artifacts, tuple) or not isinstance(
        request.approved_attestations, tuple
    ):
        raise _fail(FailureCategory.INVALID_INPUT)
    if not request.approved_artifacts:
        # v0.1 deliberately does not publish attestation-only workspaces.
        raise _fail(FailureCategory.INVALID_INPUT)

    source_root = _normalized_absolute_root(request.original_workspace_root)
    destination_root = _normalized_absolute_root(request.destination_workspace_root)
    if _paths_overlap(source_root, destination_root):
        raise _fail(FailureCategory.DESTINATION_OVERLAP)
    if os.path.lexists(destination_root):
        raise _fail(FailureCategory.DESTINATION_EXISTS)

    try:
        source_metadata = source_root.lstat()
    except OSError as exc:
        raise _fail(FailureCategory.SOURCE_MISSING) from exc
    if _is_reparse_point(source_root, source_metadata):
        raise _fail(FailureCategory.SOURCE_LINK)
    if not stat.S_ISDIR(source_metadata.st_mode):
        raise _fail(FailureCategory.SOURCE_NOT_REGULAR)
    _validate_directory_chain(source_root, FailureCategory.SOURCE_LINK)

    destination_parent = destination_root.parent
    if not destination_parent.exists():
        raise _fail(FailureCategory.DESTINATION_PARENT_UNSAFE)
    _validate_directory_chain(
        destination_parent, FailureCategory.DESTINATION_PARENT_UNSAFE
    )

    artifacts: list[ApprovedArtifactSelection] = []
    evidence_keys: set[str] = set()
    path_keys: set[str] = set()
    path_part_keys: list[tuple[str, ...]] = []
    for artifact in request.approved_artifacts:
        if not isinstance(artifact, ApprovedArtifactSelection):
            raise _fail(FailureCategory.INVALID_INPUT)
        evidence_id = _require_canonical_text(artifact.evidence_id)
        evidence_key = evidence_id.casefold()
        if evidence_key in evidence_keys:
            raise _fail(FailureCategory.INVALID_INPUT)
        evidence_keys.add(evidence_key)
        relative_path = _portable_relative_path(artifact.source_relative_path)
        path_key = relative_path.casefold()
        parts_key = tuple(part.casefold() for part in PurePosixPath(relative_path).parts)
        if path_key in path_keys or any(
            parts_key[: len(existing)] == existing
            or existing[: len(parts_key)] == parts_key
            for existing in path_part_keys
        ):
            raise _fail(FailureCategory.PATH_COLLISION)
        path_keys.add(path_key)
        path_part_keys.append(parts_key)
        expected_sha256 = _require_sha256(artifact.expected_sha256)
        if artifact.expected_byte_size is not None and (
            not isinstance(artifact.expected_byte_size, int)
            or isinstance(artifact.expected_byte_size, bool)
            or artifact.expected_byte_size < 0
        ):
            raise _fail(FailureCategory.INVALID_INPUT)
        normalized_artifact = ApprovedArtifactSelection(
            evidence_id=evidence_id,
            source_relative_path=relative_path,
            expected_sha256=expected_sha256,
            expected_byte_size=artifact.expected_byte_size,
        )
        _validate_source_item(source_root, relative_path)
        artifacts.append(normalized_artifact)

    attestations = tuple(_validate_attestation(item) for item in request.approved_attestations)
    attestation_keys = [item.attestation_id.casefold() for item in attestations]
    if len(set(attestation_keys)) != len(attestation_keys):
        raise _fail(FailureCategory.INVALID_INPUT)

    return _ValidatedRequest(
        source_root=source_root,
        destination_root=destination_root,
        artifacts=tuple(
            sorted(
                artifacts,
                key=lambda item: (
                    item.source_relative_path.casefold(),
                    item.source_relative_path,
                    item.evidence_id,
                ),
            )
        ),
        attestations=tuple(sorted(attestations, key=lambda item: item.attestation_id)),
        source_scope_binding=_validate_binding(
            request.source_scope_binding,
            tuple(artifacts),
        ),
    )


def _same_file_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
        and stat.S_IFMT(first.st_mode) == stat.S_IFMT(second.st_mode)
    )


def _open_source(source_root: Path, relative_path: str) -> tuple[int, os.stat_result, Path]:
    source_path = _validate_source_item(source_root, relative_path)
    before = source_path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source_path, flags)
    except OSError as exc:
        raise _fail(FailureCategory.SOURCE_NOT_REGULAR) from exc
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or not _same_file_identity(before, opened):
        os.close(descriptor)
        raise _fail(FailureCategory.SOURCE_MUTATED)
    return descriptor, opened, source_path


def _verify_source_unchanged(
    source_path: Path, opened: os.stat_result, descriptor: int
) -> None:
    after_open = os.fstat(descriptor)
    try:
        after_path = source_path.lstat()
    except OSError as exc:
        raise _fail(FailureCategory.SOURCE_MUTATED) from exc
    if (
        _is_reparse_point(source_path, after_path)
        or not _same_file_identity(opened, after_open)
        or not _same_file_identity(opened, after_path)
        or opened.st_size != after_open.st_size
        or opened.st_mtime_ns != after_open.st_mtime_ns
    ):
        raise _fail(FailureCategory.SOURCE_MUTATED)


def _copy_and_hash_source(
    source_root: Path,
    artifact: ApprovedArtifactSelection,
    staged_path: Path,
) -> tuple[str, int]:
    descriptor, opened, source_path = _open_source(
        source_root, artifact.source_relative_path
    )
    digest = hashlib.sha256()
    byte_size = 0
    try:
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        with staged_path.open("xb") as destination:
            while True:
                chunk = os.read(descriptor, _READ_CHUNK_SIZE)
                if not chunk:
                    break
                destination.write(chunk)
                digest.update(chunk)
                byte_size += len(chunk)
        _verify_source_unchanged(source_path, opened, descriptor)
    except ApprovedWorkspaceMaterializationError:
        raise
    except OSError as exc:
        raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
    finally:
        os.close(descriptor)

    observed_sha256 = digest.hexdigest()
    if observed_sha256 != artifact.expected_sha256 or (
        artifact.expected_byte_size is not None
        and byte_size != artifact.expected_byte_size
    ):
        raise _fail(FailureCategory.SOURCE_FINGERPRINT_MISMATCH)
    copied_sha256, copied_size = _hash_regular_file(staged_path)
    if copied_sha256 != observed_sha256 or copied_size != byte_size:
        raise _fail(FailureCategory.PUBLICATION_FAILED)
    return observed_sha256, byte_size


def _hash_regular_file(path: Path) -> tuple[str, int]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
    if _is_reparse_point(path, metadata) or not stat.S_ISREG(metadata.st_mode):
        raise _fail(FailureCategory.PUBLICATION_FAILED)
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_READ_CHUNK_SIZE), b""):
                digest.update(chunk)
                byte_size += len(chunk)
    except OSError as exc:
        raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
    return digest.hexdigest(), byte_size


def _rehash_source(
    source_root: Path, artifact: ApprovedArtifactSelection
) -> tuple[str, int]:
    descriptor, opened, source_path = _open_source(
        source_root, artifact.source_relative_path
    )
    digest = hashlib.sha256()
    byte_size = 0
    try:
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            byte_size += len(chunk)
        _verify_source_unchanged(source_path, opened, descriptor)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), byte_size


def _attestation_payload(
    attestations: tuple[_ValidatedAttestation, ...]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    manifest_entries: list[dict[str, Any]] = []
    for attestation in attestations:
        entry = {
            "attestation_id": attestation.attestation_id,
            "downstream_data": attestation.downstream_data,
            "provenance": {
                "approval_reference": attestation.approval_reference,
                "human_actor_id": attestation.human_actor_id,
                "type": "human_attestation",
            },
        }
        entries.append(entry)
        manifest_entries.append(
            {
                "attestation_id": attestation.attestation_id,
                "sha256": sha256_bytes(canonical_json_bytes(entry)),
            }
        )
    return {"schema_version": SCHEMA_VERSION, "attestations": entries}, manifest_entries


def _binding_payload(binding: SourceScopeBinding | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "binding_sha256": binding.binding_sha256,
        "expected_source_fingerprints": list(binding.expected_source_fingerprints),
    }


def _workspace_id(
    artifact_entries: list[dict[str, Any]],
    attestation_entries: list[dict[str, Any]],
    binding: SourceScopeBinding | None,
) -> str:
    identity = {
        "schema_version": SCHEMA_VERSION,
        "approved_artifacts": artifact_entries,
        "approved_attestations": attestation_entries,
        "source_scope_binding": _binding_payload(binding),
    }
    return sha256_bytes(canonical_json_bytes(identity))


def _workspace_file_entries(root: Path) -> list[dict[str, Any]]:
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
    if _is_reparse_point(root, root_metadata) or not stat.S_ISDIR(root_metadata.st_mode):
        raise _fail(FailureCategory.PUBLICATION_FAILED)

    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
            if _is_reparse_point(path, metadata):
                raise _fail(FailureCategory.PUBLICATION_FAILED)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(path)
            else:
                raise _fail(FailureCategory.PUBLICATION_FAILED)

    result: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative_path = path.relative_to(root).as_posix()
        sha256, byte_size = _hash_regular_file(path)
        result.append(
            {"relative_path": relative_path, "sha256": sha256, "byte_size": byte_size}
        )
    return result


def compute_workspace_fingerprint(workspace_root: Path) -> str:
    """Independently recompute the path-and-byte identity of a workspace."""

    root = _normalized_absolute_root(workspace_root)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "files": _workspace_file_entries(root),
    }
    return sha256_bytes(canonical_json_bytes(payload))


def _safe_cleanup(stage_root: Path | None, destination_parent: Path) -> None:
    if stage_root is None or not os.path.lexists(stage_root):
        return
    if stage_root.parent != destination_parent or not stage_root.name.startswith(
        ".continuity-approved-stage-"
    ):
        return
    try:
        shutil.rmtree(stage_root)
    except OSError:
        # The original failure remains authoritative; cleanup is best effort.
        pass


def materialize_approved_workspace(
    request: ApprovedWorkspaceRequest,
    *,
    _test_hooks: _MaterializationTestHooks | None = None,
) -> MaterializationReceipt:
    """Build, verify, and atomically publish one approved-only workspace."""

    try:
        validated = _validate_request(request)
    except ApprovedWorkspaceMaterializationError:
        raise
    except Exception as exc:
        raise _fail(FailureCategory.INVALID_INPUT) from exc
    destination_parent = validated.destination_root.parent
    stage_root: Path | None = None
    try:
        stage_root = Path(
            tempfile.mkdtemp(
                prefix=".continuity-approved-stage-",
                dir=destination_parent,
            )
        )

        artifact_entries: list[dict[str, Any]] = []
        for artifact in validated.artifacts:
            source_path = validated.source_root.joinpath(
                *PurePosixPath(artifact.source_relative_path).parts
            )
            staged_path = stage_root.joinpath(
                *PurePosixPath(artifact.source_relative_path).parts
            )
            observed_sha256, byte_size = _copy_and_hash_source(
                validated.source_root, artifact, staged_path
            )
            artifact_entries.append(
                {
                    "evidence_id": artifact.evidence_id,
                    "relative_path": artifact.source_relative_path,
                    "sha256": observed_sha256,
                    "byte_size": byte_size,
                }
            )
            if _test_hooks and _test_hooks.after_artifact_copied:
                _test_hooks.after_artifact_copied(artifact, source_path, staged_path)

        attestation_payload, attestation_manifest_entries = _attestation_payload(
            validated.attestations
        )
        attestation_bytes = canonical_json_bytes(attestation_payload)
        attestation_path = stage_root / APPROVED_ATTESTATIONS_RELATIVE_PATH
        attestation_path.parent.mkdir(parents=True, exist_ok=True)
        attestation_path.write_bytes(attestation_bytes)

        approved_workspace_id = _workspace_id(
            artifact_entries,
            attestation_manifest_entries,
            validated.source_scope_binding,
        )
        manifest_payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "approved_workspace_id": approved_workspace_id,
            "approved_artifacts": artifact_entries,
            "approved_attestations": {
                "entries": attestation_manifest_entries,
                "generated_file": {
                    "relative_path": APPROVED_ATTESTATIONS_RELATIVE_PATH.as_posix(),
                    "sha256": sha256_bytes(attestation_bytes),
                    "byte_size": len(attestation_bytes),
                },
            },
        }
        binding_payload = _binding_payload(validated.source_scope_binding)
        if binding_payload is not None:
            manifest_payload["source_scope_binding"] = binding_payload
        manifest_bytes = canonical_json_bytes(manifest_payload)
        manifest_path = stage_root / APPROVED_MANIFEST_RELATIVE_PATH
        manifest_path.write_bytes(manifest_bytes)
        manifest_fingerprint = sha256_bytes(manifest_bytes)

        final_workspace_fingerprint = compute_workspace_fingerprint(stage_root)

        for artifact in validated.artifacts:
            source_sha256, source_size = _rehash_source(
                validated.source_root, artifact
            )
            if source_sha256 != artifact.expected_sha256 or (
                artifact.expected_byte_size is not None
                and source_size != artifact.expected_byte_size
            ):
                raise _fail(FailureCategory.SOURCE_MUTATED)

        if _test_hooks and _test_hooks.before_publish:
            _test_hooks.before_publish(stage_root, validated.destination_root)

        for artifact_entry in artifact_entries:
            staged_artifact = stage_root.joinpath(
                *PurePosixPath(artifact_entry["relative_path"]).parts
            )
            staged_sha256, staged_size = _hash_regular_file(staged_artifact)
            if (
                staged_sha256 != artifact_entry["sha256"]
                or staged_size != artifact_entry["byte_size"]
            ):
                raise _fail(FailureCategory.PUBLICATION_FAILED)
        final_attestation_sha256, final_attestation_size = _hash_regular_file(
            attestation_path
        )
        if (
            final_attestation_sha256 != sha256_bytes(attestation_bytes)
            or final_attestation_size != len(attestation_bytes)
        ):
            raise _fail(FailureCategory.PUBLICATION_FAILED)
        final_manifest_sha256, final_manifest_size = _hash_regular_file(manifest_path)
        if (
            final_manifest_sha256 != manifest_fingerprint
            or final_manifest_size != len(manifest_bytes)
        ):
            raise _fail(FailureCategory.PUBLICATION_FAILED)
        if compute_workspace_fingerprint(stage_root) != final_workspace_fingerprint:
            raise _fail(FailureCategory.PUBLICATION_FAILED)

        _validate_directory_chain(
            destination_parent, FailureCategory.DESTINATION_PARENT_UNSAFE
        )
        if os.path.lexists(validated.destination_root):
            raise _fail(FailureCategory.DESTINATION_EXISTS)

        receipt = MaterializationReceipt(
            schema_version=SCHEMA_VERSION,
            approved_workspace_id=approved_workspace_id,
            destination_root=validated.destination_root,
            final_workspace_fingerprint=final_workspace_fingerprint,
            manifest_fingerprint=manifest_fingerprint,
            approved_artifact_count=len(validated.artifacts),
            approved_attestation_count=len(validated.attestations),
            source_scope_binding=validated.source_scope_binding,
            publication_status=PublicationStatus.PUBLISHED,
        )
        os.rename(stage_root, validated.destination_root)
        stage_root = None
        return receipt
    except ApprovedWorkspaceMaterializationError:
        _safe_cleanup(stage_root, destination_parent)
        raise
    except Exception as exc:
        _safe_cleanup(stage_root, destination_parent)
        raise _fail(FailureCategory.PUBLICATION_FAILED) from exc
