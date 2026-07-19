"""Audit-only tests for approved_workspace/materializer.py.

Independent adversarial audit of audit/approved-only-workspace-v0.1 at
01ded4552e570856f155dbee1c94a5a53a663083. These tests supplement (never
replace) tests/approved_workspace/test_materializer.py and target gaps in
the required audit checklist that were not already exercised: input-contract
edge cases, Windows path boundaries, real junction-based reparse checks,
TOCTOU windows, attestation leakage semantics, manifest identity, and
source-scope binding semantics.

No production code is modified by this file.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from continuity_ai.approved_workspace import (
    ApprovedArtifactSelection,
    ApprovedHumanAttestation,
    ApprovedWorkspaceMaterializationError,
    ApprovedWorkspaceRequest,
    AttestationApprovalStatus,
    FailureCategory,
    SourceScopeBinding,
    materialize_approved_workspace,
)
from continuity_ai.approved_workspace.materializer import _MaterializationTestHooks


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _selection(evidence_id: str, relative_path: str, data: bytes, *, size: int | None = -1) -> ApprovedArtifactSelection:
    return ApprovedArtifactSelection(
        evidence_id=evidence_id,
        source_relative_path=relative_path,
        expected_sha256=_sha256(data),
        expected_byte_size=len(data) if size == -1 else size,
    )


def _attestation(
    *,
    attestation_id: str = "attestation-1",
    downstream_data: Any = None,
    human_actor_id: str = "reviewer-1",
    approval_reference: str = "approval-1",
    status: AttestationApprovalStatus = AttestationApprovalStatus.APPROVED,
) -> ApprovedHumanAttestation:
    return ApprovedHumanAttestation(
        attestation_id=attestation_id,
        downstream_data=downstream_data if downstream_data is not None else {"assertion": "human-approved fact"},
        human_actor_id=human_actor_id,
        approval_reference=approval_reference,
        approval_status=status,
    )


def _request(
    source: Path,
    destination: Path,
    artifacts: tuple[ApprovedArtifactSelection, ...],
    attestations: tuple[ApprovedHumanAttestation, ...] = (),
    binding: SourceScopeBinding | None = None,
) -> ApprovedWorkspaceRequest:
    return ApprovedWorkspaceRequest(
        original_workspace_root=source,
        approved_artifacts=artifacts,
        approved_attestations=attestations,
        destination_workspace_root=destination,
        source_scope_binding=binding,
    )


def _write(source: Path, relative_path: str, data: bytes) -> None:
    path = source.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _assert_category(
    category: FailureCategory,
    request: ApprovedWorkspaceRequest,
    *,
    hooks: _MaterializationTestHooks | None = None,
) -> None:
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(request, _test_hooks=hooks)
    assert raised.value.category is category
    assert not request.destination_workspace_root.exists()


def _mklink_junction(link: Path, target: Path) -> bool:
    """Create a real Windows directory junction. Returns False if unavailable."""

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and link.exists()


# ---------------------------------------------------------------------------
# INPUT CONTRACT
# ---------------------------------------------------------------------------


def test_wrong_runtime_type_request_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(SimpleNamespace(foo="bar"))  # type: ignore[arg-type]
    assert raised.value.category is FailureCategory.INVALID_INPUT


def test_wrong_runtime_type_dict_request_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace({"original_workspace_root": tmp_path})  # type: ignore[arg-type]
    assert raised.value.category is FailureCategory.INVALID_INPUT


def test_subclass_of_request_is_accepted_isinstance_is_structural(tmp_path: Path) -> None:
    """Documents behavior: isinstance() accepts subclasses; this is not a bypass
    because every field is still independently re-validated by content."""

    class _RequestSubclass(ApprovedWorkspaceRequest):
        pass

    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "record", data)
    subclass_request = _RequestSubclass(
        original_workspace_root=source,
        approved_artifacts=(_selection("evidence", "record", data),),
        approved_attestations=(),
        destination_workspace_root=tmp_path / "destination",
        source_scope_binding=None,
    )
    receipt = materialize_approved_workspace(subclass_request)
    assert receipt.approved_artifact_count == 1


def test_duplicate_evidence_id_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data_a = b"aaa"
    data_b = b"bbb"
    _write(source, "a.txt", data_a)
    _write(source, "b.txt", data_b)
    request = _request(
        source,
        tmp_path / "destination",
        (
            _selection("same-evidence-id", "a.txt", data_a),
            _selection("same-evidence-id", "b.txt", data_b),
        ),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_duplicate_attestation_id_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (
            _attestation(attestation_id="dup", downstream_data={"fact": "one"}),
            _attestation(attestation_id="dup", downstream_data={"fact": "two"}),
        ),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_two_evidence_ids_selecting_same_path_is_a_path_collision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (
            _selection("evidence-one", "record", data),
            _selection("evidence-two", "record", data),
        ),
    )
    _assert_category(FailureCategory.PATH_COLLISION, request)


def test_two_paths_with_identical_bytes_is_allowed_not_a_collision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"shared content"
    _write(source, "one/record.txt", data)
    _write(source, "two/record.txt", data)
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (
                _selection("evidence-one", "one/record.txt", data),
                _selection("evidence-two", "two/record.txt", data),
            ),
        )
    )
    assert receipt.approved_artifact_count == 2
    assert (receipt.destination_root / "one/record.txt").read_bytes() == data
    assert (receipt.destination_root / "two/record.txt").read_bytes() == data


def test_file_versus_parent_path_collision_is_rejected(tmp_path: Path) -> None:
    """'a' as a file and 'a/b' as a nested file can never coexist on disk, so
    'a/b' cannot be physically written for this test. The collision check is
    fused into the same per-artifact loop as physical validation (not a
    separate full pre-pass), so it only surfaces as PATH_COLLISION here
    because 'a' is listed (and physically validated) FIRST, recording its
    path-parts before 'a/b' is reached. See
    test_file_versus_parent_collision_category_depends_on_order below for the
    documented, still-fail-closed, order-dependent counterpart."""

    source = tmp_path / "source"
    source.mkdir()
    _write(source, "a", b"data-a")
    request = _request(
        source,
        tmp_path / "destination",
        (
            _selection("evidence-a", "a", b"data-a"),
            _selection("evidence-ab", "a/b", b"data-b"),
        ),
    )
    _assert_category(FailureCategory.PATH_COLLISION, request)


def test_file_versus_parent_collision_category_depends_on_order(tmp_path: Path) -> None:
    """Documents a minor, non-security determinism nuance: when the CHILD path
    ('a/b') is listed first, the physical walk rejects it as
    SOURCE_NOT_REGULAR/SOURCE_MISSING before the pairwise collision check
    ever runs, instead of PATH_COLLISION. Every ordering still fails closed
    (no publish, sanitized category) -- only the reported category varies."""

    source = tmp_path / "source"
    source.mkdir()
    _write(source, "a", b"data-a")
    request = _request(
        source,
        tmp_path / "destination",
        (
            _selection("evidence-ab", "a/b", b"data-b"),
            _selection("evidence-a", "a", b"data-a"),
        ),
    )
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(request)
    assert raised.value.category in (
        FailureCategory.SOURCE_NOT_REGULAR,
        FailureCategory.SOURCE_MISSING,
        FailureCategory.PATH_COLLISION,
    )
    assert not request.destination_workspace_root.exists()


def test_binding_with_incomplete_fingerprint_set_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    first = b"first"
    second = b"second"
    _write(source, "one", first)
    _write(source, "two", second)
    binding = SourceScopeBinding("a" * 64, (_sha256(first),))  # missing second
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("id-1", "one", first), _selection("id-2", "two", second)),
        binding=binding,
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_binding_duplicate_fingerprints_matching_multiset_is_allowed(tmp_path: Path) -> None:
    """SourceScopeBinding is a multiset-of-hashes check; two approved artifacts
    with identical content and a binding that lists the hash twice must match."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"same bytes"
    _write(source, "one", data)
    _write(source, "two", data)
    binding = SourceScopeBinding("b" * 64, (_sha256(data), _sha256(data)))
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("id-1", "one", data), _selection("id-2", "two", data)),
            binding=binding,
        )
    )
    assert receipt.approved_artifact_count == 2


def test_malformed_uppercase_sha256_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    selection = ApprovedArtifactSelection("evidence", "record", _sha256(data).upper(), len(data))
    _assert_category(FailureCategory.INVALID_INPUT, _request(source, tmp_path / "destination", (selection,)))


def test_malformed_short_sha256_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    selection = ApprovedArtifactSelection("evidence", "record", "ab" * 16, len(data))
    _assert_category(FailureCategory.INVALID_INPUT, _request(source, tmp_path / "destination", (selection,)))


def test_negative_byte_size_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    selection = ApprovedArtifactSelection("evidence", "record", _sha256(data), -1)
    _assert_category(FailureCategory.INVALID_INPUT, _request(source, tmp_path / "destination", (selection,)))


def test_boolean_byte_size_is_rejected(tmp_path: Path) -> None:
    """bool is a subclass of int in Python; must not silently coerce to 0/1."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    selection = ApprovedArtifactSelection("evidence", "record", _sha256(data), True)  # type: ignore[arg-type]
    _assert_category(FailureCategory.INVALID_INPUT, _request(source, tmp_path / "destination", (selection,)))


def test_unknown_enum_like_approval_status_string_is_rejected(tmp_path: Path) -> None:
    """A raw string equal to the enum's value must not satisfy the identity check
    the production code performs (`is not AttestationApprovalStatus.APPROVED`)."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (_attestation(status="approved"),),  # type: ignore[arg-type]
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_non_string_json_object_key_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (_attestation(downstream_data={123: "value"}),),  # type: ignore[dict-item]
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_nested_mutable_containers_are_canonicalized_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    nested_a = {"list": [{"z": 1, "a": 2}, {"y": [3, 4, {"nested": True}]}]}
    nested_b = {"list": [{"a": 2, "z": 1}, {"y": [3, 4, {"nested": True}]}]}
    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", (_selection("id", "record", data),), (_attestation(downstream_data=nested_a),))
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", (_selection("id", "record", data),), (_attestation(downstream_data=nested_b),))
    )
    assert first.final_workspace_fingerprint == second.final_workspace_fingerprint


def test_large_interoperable_range_integer_is_preserved_exactly(tmp_path: Path) -> None:
    """Not a security defect: documents that arbitrary-precision Python ints pass
    through unchanged and are hashed exactly as serialized (no silent truncation)."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    huge = 2**100 + 7
    receipt = materialize_approved_workspace(
        _request(source, tmp_path / "destination", (_selection("id", "record", data),), (_attestation(downstream_data={"n": huge}),))
    )
    manifest = json.loads((receipt.destination_root / ".continuity/approved_attestations.json").read_bytes())
    assert manifest["attestations"][0]["downstream_data"]["n"] == huge


@pytest.mark.parametrize("bad_float", [1.5, float("nan"), float("inf"), float("-inf")])
def test_floats_nan_and_infinity_are_rejected(tmp_path: Path, bad_float: float) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (_attestation(downstream_data={"value": bad_float}),),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_bytes_value_in_attestation_data_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (_attestation(downstream_data={"value": b"raw-bytes"}),),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_path_object_value_in_attestation_data_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (_attestation(downstream_data={"value": Path("some/path")}),),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_custom_mapping_value_is_normalized_like_a_dict(tmp_path: Path) -> None:
    from collections.abc import Mapping

    class _CustomMapping(Mapping):
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def __getitem__(self, key: str) -> Any:
            return self._data[key]

        def __iter__(self):
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("id", "record", data),),
            (_attestation(downstream_data=_CustomMapping({"fact": "value"})),),
        )
    )
    manifest = json.loads((receipt.destination_root / ".continuity/approved_attestations.json").read_bytes())
    assert manifest["attestations"][0]["downstream_data"] == {"fact": "value"}


# ---------------------------------------------------------------------------
# PATH AND WINDOWS BOUNDARY
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unsafe_path",
    [
        r"\\server\share\file.txt",  # UNC
        r"\\?\C:\Windows\file.txt",  # extended-length prefix
        "file.txt:hidden-stream",  # alternate data stream syntax
        r"folder\file.txt",  # backslash separator
        r"folder\mixed/file.txt",  # mixed separators
    ],
)
def test_windows_specific_unsafe_paths_are_rejected(tmp_path: Path, unsafe_path: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    request = _request(source, tmp_path / "destination", (_selection("evidence", unsafe_path, b"data"),))
    _assert_category(FailureCategory.UNSAFE_PATH, request)


def test_nfd_unicode_variant_path_is_rejected(tmp_path: Path) -> None:
    import unicodedata

    source = tmp_path / "source"
    source.mkdir()
    nfd_name = unicodedata.normalize("NFD", "café.txt")
    assert nfd_name != unicodedata.normalize("NFC", nfd_name)
    request = _request(source, tmp_path / "destination", (_selection("evidence", nfd_name, b"data"),))
    _assert_category(FailureCategory.UNSAFE_PATH, request)


@pytest.mark.parametrize(
    "reserved_path",
    ["CON", "com1.log", "LPT3", "notes.", "notes ", "sub/AUX/file.txt"],
)
def test_windows_reserved_names_and_trailing_dot_space_are_rejected(tmp_path: Path, reserved_path: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    request = _request(source, tmp_path / "destination", (_selection("evidence", reserved_path, b"data"),))
    _assert_category(FailureCategory.UNSAFE_PATH, request)


def test_control_character_in_path_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    request = _request(source, tmp_path / "destination", (_selection("evidence", "file\x01name.txt", b"data"),))
    _assert_category(FailureCategory.UNSAFE_PATH, request)


@pytest.mark.parametrize("dotcontinuity_path", [".continuity/evil.json", ".CONTINUITY/evil.json"])
def test_top_level_dot_continuity_namespace_is_rejected(tmp_path: Path, dotcontinuity_path: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    request = _request(source, tmp_path / "destination", (_selection("evidence", dotcontinuity_path, b"data"),))
    _assert_category(FailureCategory.UNSAFE_PATH, request)


def test_nested_dot_continuity_directory_name_is_allowed(tmp_path: Path) -> None:
    """Only the TOP-LEVEL '.continuity' component is reserved: it cannot collide
    with the materializer's own generated files at stage_root/.continuity/*."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"nested"
    _write(source, "foo/.continuity/thing.txt", data)
    receipt = materialize_approved_workspace(
        _request(source, tmp_path / "destination", (_selection("evidence", "foo/.continuity/thing.txt", data),))
    )
    assert (receipt.destination_root / "foo/.continuity/thing.txt").read_bytes() == data
    assert (receipt.destination_root / ".continuity/approved_workspace_manifest.json").exists()


def test_destination_equal_to_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(source, source, (_selection("evidence", "record", data),))
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(request)
    assert raised.value.category is FailureCategory.DESTINATION_OVERLAP
    assert source.exists()  # source itself is untouched, not "leaked" by the check


def test_destination_case_alias_on_windows_is_rejected(tmp_path: Path) -> None:
    if os.path.normcase("A") != os.path.normcase("a"):
        pytest.skip("Host filesystem is case-sensitive")
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    existing = tmp_path / "dest"
    existing.mkdir()
    sentinel = existing / "sentinel"
    sentinel.write_bytes(b"unchanged")
    request = _request(source, tmp_path / "DEST", (_selection("evidence", "record", data),))
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(request)
    assert raised.value.category is FailureCategory.DESTINATION_EXISTS
    assert sentinel.read_bytes() == b"unchanged"
    assert not (existing / "record").exists()


def test_hardlinked_source_file_is_accepted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"hardlinked content"
    original = source / "original.txt"
    original.write_bytes(data)
    linked = source / "linked.txt"
    try:
        os.link(original, linked)
    except OSError:
        pytest.skip("Hard links are unavailable on this host/filesystem")
    receipt = materialize_approved_workspace(
        _request(source, tmp_path / "destination", (_selection("evidence", "linked.txt", data),))
    )
    assert (receipt.destination_root / "linked.txt").read_bytes() == data


def test_source_root_itself_as_junction_is_rejected(tmp_path: Path) -> None:
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    (real_target / "record").write_bytes(b"outside")
    junction_root = tmp_path / "junction-root"
    if not _mklink_junction(junction_root, real_target):
        pytest.skip("Directory junctions are unavailable on this host")
    request = _request(
        junction_root,
        tmp_path / "destination",
        (_selection("evidence", "record", b"outside"),),
    )
    _assert_category(FailureCategory.SOURCE_LINK, request)


def test_ancestor_of_source_root_as_junction_is_rejected(tmp_path: Path) -> None:
    """Real junction test (claim 6 / Windows reparse-point section): an ancestor
    directory of source_root, not source_root itself, is a reparse point."""

    real_base = tmp_path / "real-base"
    real_base.mkdir()
    nested_source = real_base / "nested" / "source"
    nested_source.mkdir(parents=True)
    (nested_source / "record").write_bytes(b"inside")

    junction_link = tmp_path / "junction-ancestor"
    if not _mklink_junction(junction_link, real_base):
        pytest.skip("Directory junctions are unavailable on this host")

    source_root_via_junction = junction_link / "nested" / "source"
    request = _request(
        source_root_via_junction,
        tmp_path / "destination",
        (_selection("evidence", "record", b"inside"),),
    )
    _assert_category(FailureCategory.SOURCE_LINK, request)


def test_junction_swapped_in_after_initial_validation_is_caught_by_final_rehash(tmp_path: Path) -> None:
    """TOCTOU probe: a subdirectory of source_root is replaced by a real Windows
    junction AFTER the artifact is copied but BEFORE the final pre-publish
    rehash pass. The final rehash must re-walk the path and detect the reparse
    point rather than trusting the earlier validation."""

    import shutil

    source = tmp_path / "source"
    source.mkdir()
    real_dir = source / "linked"
    real_dir.mkdir()
    data = b"original bytes"
    (real_dir / "record").write_bytes(data)

    outside = tmp_path / "outside-target"
    outside.mkdir()
    (outside / "record").write_bytes(b"attacker bytes!!")

    if not _mklink_junction(tmp_path / "junction-probe", outside):
        pytest.skip("Directory junctions are unavailable on this host")
    (tmp_path / "junction-probe").rmdir() if False else None  # no-op guard

    def swap_to_junction(_artifact, _source_path: Path, _staged: Path) -> None:
        shutil.rmtree(real_dir)
        if not _mklink_junction(real_dir, outside):
            raise AssertionError("junction swap failed inside test hook")

    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "linked/record", data),),
    )
    _assert_category(
        FailureCategory.SOURCE_LINK,
        request,
        hooks=_MaterializationTestHooks(after_artifact_copied=swap_to_junction),
    )


# ---------------------------------------------------------------------------
# COPY AND TOCTOU
# ---------------------------------------------------------------------------


def test_source_identity_change_with_identical_bytes_after_copy_still_succeeds(tmp_path: Path) -> None:
    """Distinguishes source-state freshness from destination evidence integrity:
    if the source inode changes but bytes remain byte-identical, publication
    must still succeed (the published bytes match the required hash)."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"stable content"
    record_path = source / "record"
    record_path.write_bytes(data)

    def replace_with_new_inode_same_bytes(_artifact, source_path: Path, _staged: Path) -> None:
        replacement = source_path.with_suffix(".replacement")
        replacement.write_bytes(data)
        os.replace(replacement, source_path)

    request = _request(source, tmp_path / "destination", (_selection("evidence", "record", data),))
    receipt = materialize_approved_workspace(
        request,
        _test_hooks=_MaterializationTestHooks(after_artifact_copied=replace_with_new_inode_same_bytes),
    )
    assert (receipt.destination_root / "record").read_bytes() == data


def test_destination_created_between_preflight_and_rename_fails_closed(tmp_path: Path) -> None:
    """Injects a concurrent-writer simulation: something creates the destination
    path after all staging/verification but before the rename. Production must
    not publish, must not overwrite, and must report failure (not success)."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    destination = tmp_path / "destination"

    def create_destination_concurrently(_stage: Path, destination_root: Path) -> None:
        destination_root.mkdir()
        (destination_root / "attacker-sentinel").write_bytes(b"should not be touched")

    request = _request(source, destination, (_selection("evidence", "record", data),))
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(
            request,
            _test_hooks=_MaterializationTestHooks(before_publish=create_destination_concurrently),
        )
    assert raised.value.category in (FailureCategory.DESTINATION_EXISTS, FailureCategory.PUBLICATION_FAILED)
    assert (destination / "attacker-sentinel").exists(), "concurrent writer's own directory must survive untouched"
    assert not (destination / "record").exists(), "approved content must not have been published into it"
    assert not list(tmp_path.glob(".continuity-approved-stage-*")), "stage must be cleaned up"


def test_destination_parent_replaced_by_junction_after_validation_fails_closed(tmp_path: Path) -> None:
    """The destination parent directory chain is re-validated immediately before
    publish via _validate_directory_chain(destination_parent, ...). Simulate a
    real junction replacing destination_parent in that window.

    Because materialize_approved_workspace always stages into
    tempfile.mkdtemp(dir=destination_parent), stage_root is structurally a
    CHILD of destination_parent -- so an attacker who replaces
    destination_parent necessarily destroys/detaches the stage as collateral
    damage. In practice that means the earlier per-artifact/manifest re-hash
    checks fail first (PUBLICATION_FAILED, staged files now missing) rather
    than the later explicit DESTINATION_PARENT_UNSAFE check ever being
    reached. Both are sanitized, fail-closed categories with no publish; this
    test asserts the invariant (fail closed, no leak) rather than pinning an
    unreachable specific category."""

    import shutil

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    destination = real_parent / "approved-out"

    outside = tmp_path / "elsewhere"
    outside.mkdir()

    if not _mklink_junction(tmp_path / "junction-availability-probe", outside):
        pytest.skip("Directory junctions are unavailable on this host")
    os.rmdir(tmp_path / "junction-availability-probe")

    def replace_parent_with_junction(_stage: Path, _destination_root: Path) -> None:
        shutil.rmtree(real_parent)
        if not _mklink_junction(real_parent, outside):
            raise AssertionError("junction swap failed inside test hook")

    request = _request(source, destination, (_selection("evidence", "record", data),))
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(
            request,
            _test_hooks=_MaterializationTestHooks(before_publish=replace_parent_with_junction),
        )
    assert raised.value.category in (
        FailureCategory.DESTINATION_PARENT_UNSAFE,
        FailureCategory.PUBLICATION_FAILED,
    )
    assert not (outside / "approved-out").exists()


def test_exception_after_some_files_copied_leaves_no_partial_publish(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    good = b"good bytes"
    bad = b"actual bytes"
    _write(source, "good.txt", good)
    _write(source, "bad.txt", bad)
    bad_selection = ApprovedArtifactSelection("bad-evidence", "bad.txt", "0" * 64, len(bad))
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("good-evidence", "good.txt", good), bad_selection),
    )
    _assert_category(FailureCategory.SOURCE_FINGERPRINT_MISMATCH, request)
    assert not list(tmp_path.glob(".continuity-approved-stage-*"))
    assert not (tmp_path / "destination").exists()


def test_cleanup_never_touches_unrelated_stage_prefixed_sibling(tmp_path: Path) -> None:
    """_safe_cleanup must only remove the exact stage directory this run owns,
    never a look-alike sibling created by another process/run."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    destination = tmp_path / "destination"

    decoy = tmp_path / ".continuity-approved-stage-decoy"
    decoy.mkdir()
    (decoy / "unrelated").write_bytes(b"must survive")

    def fail_publication(_stage: Path, _destination: Path) -> None:
        raise OSError("injected publication failure")

    request = _request(source, destination, (_selection("evidence", "record", data),))
    _assert_category(
        FailureCategory.PUBLICATION_FAILED,
        request,
        hooks=_MaterializationTestHooks(before_publish=fail_publication),
    )
    assert decoy.exists()
    assert (decoy / "unrelated").read_bytes() == b"must survive"


def test_windows_rename_onto_existing_empty_directory_fails_closed() -> None:
    """Characterizes the OS-level guarantee the atomic-publish step depends on.
    On POSIX, rename(2) can silently replace an EMPTY destination directory;
    on Windows, os.rename (MoveFileExW without REPLACE_EXISTING) must fail
    instead. This is what makes the destination-exists TOCTOU window in
    materialize_approved_workspace benign on this platform. This test is a
    platform-behavior proof, not a test of production code directly."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src_dir = root / "src_dir"
        src_dir.mkdir()
        (src_dir / "f.txt").write_bytes(b"hello")
        dst_dir = root / "dst_dir"
        dst_dir.mkdir()
        with pytest.raises(FileExistsError):
            os.rename(src_dir, dst_dir)
        assert list(dst_dir.iterdir()) == []
        assert (src_dir / "f.txt").exists()


# ---------------------------------------------------------------------------
# ATTESTATION LEAKAGE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sensitive_key",
    ["API_KEY", "Api-Key", "session key", "SESSION-KEY", "Owner_Secret", "  password  ".strip()],
)
def test_sensitive_key_capitalization_and_separator_variants_are_rejected(tmp_path: Path, sensitive_key: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
        (_attestation(downstream_data={"nested": {sensitive_key: "should-be-blocked"}}),),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_secret_shaped_value_under_innocent_key_is_not_caught_caller_responsibility(tmp_path: Path) -> None:
    """The materializer only inspects FIELD NAMES for the fixed sensitive-key
    list; it does not perform content-level secret scanning of values. This
    is the caller's residual responsibility, and this test proves it (the
    module makes no documented promise of content-level secret exclusion)."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    secret_like_value = "AKIAABCDEFGHIJKLMNOP"  # AWS-access-key-shaped string
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("evidence", "record", data),),
            (_attestation(downstream_data={"note": secret_like_value}),),
        )
    )
    output_bytes = (receipt.destination_root / ".continuity/approved_attestations.json").read_bytes()
    assert secret_like_value.encode("utf-8") in output_bytes


def test_secret_shaped_value_inside_list_element_is_not_caught(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    secret_like_value = "ghp_1234567890abcdefghijklmnopqrstuv"
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("evidence", "record", data),),
            (_attestation(downstream_data={"items": ["fine", secret_like_value]}),),
        )
    )
    output_bytes = (receipt.destination_root / ".continuity/approved_attestations.json").read_bytes()
    assert secret_like_value.encode("utf-8") in output_bytes


def test_secret_shaped_value_inside_human_actor_id_is_not_caught(tmp_path: Path) -> None:
    """human_actor_id and approval_reference only go through canonical-text
    formatting checks, never the sensitive-key/content scan."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    secret_like_value = "reviewer-token=sk_live_51ABCDEFGHIJKLMNOP"
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("evidence", "record", data),),
            (_attestation(human_actor_id=secret_like_value),),
        )
    )
    output_bytes = (receipt.destination_root / ".continuity/approved_attestations.json").read_bytes()
    assert secret_like_value.encode("utf-8") in output_bytes


def test_secret_shaped_value_inside_approval_reference_is_not_caught(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    secret_like_value = "ref-Bearer-eyJhbGciOiJIUzI1NiJ9.secretpayload"
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("evidence", "record", data),),
            (_attestation(approval_reference=secret_like_value),),
        )
    )
    output_bytes = (receipt.destination_root / ".continuity/approved_attestations.json").read_bytes()
    assert secret_like_value.encode("utf-8") in output_bytes


# ---------------------------------------------------------------------------
# MANIFEST AND IDENTITY
# ---------------------------------------------------------------------------


def test_changing_evidence_id_changes_workspace_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", (_selection("evidence-a", "record", data),))
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", (_selection("evidence-b", "record", data),))
    )
    assert first.approved_workspace_id != second.approved_workspace_id


def test_changing_attestation_provenance_field_changes_workspace_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    first = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "first",
            (_selection("id", "record", data),),
            (_attestation(human_actor_id="reviewer-a"),),
        )
    )
    second = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "second",
            (_selection("id", "record", data),),
            (_attestation(human_actor_id="reviewer-b"),),
        )
    )
    assert first.approved_workspace_id != second.approved_workspace_id


def test_changing_only_destination_machine_path_preserves_workspace_id(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    (tmp_path / "machine-a").mkdir()
    (tmp_path / "totally" / "different").mkdir(parents=True)
    first = materialize_approved_workspace(
        _request(source, tmp_path / "machine-a" / "out", (_selection("id", "record", data),))
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "totally" / "different" / "machine-b-path", (_selection("id", "record", data),))
    )
    assert first.approved_workspace_id == second.approved_workspace_id


def test_manifest_is_not_self_referential(tmp_path: Path) -> None:
    """The manifest's own fingerprint must be computed OVER the published bytes,
    not embedded inside itself (which would make the hash unrecomputable)."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    receipt = materialize_approved_workspace(
        _request(source, tmp_path / "destination", (_selection("id", "record", data),))
    )
    manifest_bytes = (receipt.destination_root / ".continuity/approved_workspace_manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert "manifest_fingerprint" not in manifest
    assert _sha256(manifest_bytes) == receipt.manifest_fingerprint


def test_changing_one_approved_byte_changes_final_fingerprint(tmp_path: Path) -> None:
    first_source = tmp_path / "source-1"
    second_source = tmp_path / "source-2"
    first_source.mkdir()
    second_source.mkdir()
    _write(first_source, "record", b"aaaa")
    _write(second_source, "record", b"aaab")
    first = materialize_approved_workspace(
        _request(first_source, tmp_path / "first", (_selection("id", "record", b"aaaa"),))
    )
    second = materialize_approved_workspace(
        _request(second_source, tmp_path / "second", (_selection("id", "record", b"aaab"),))
    )
    assert first.final_workspace_fingerprint != second.final_workspace_fingerprint


def test_changing_one_approved_path_changes_workspace_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "one.txt", data)
    _write(source, "two.txt", data)
    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", (_selection("id", "one.txt", data),))
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", (_selection("id", "two.txt", data),))
    )
    assert first.approved_workspace_id != second.approved_workspace_id


# ---------------------------------------------------------------------------
# SOURCE-SCOPE BINDING SEMANTICS
# ---------------------------------------------------------------------------


def test_binding_cannot_distinguish_which_evidence_id_owns_which_hash(tmp_path: Path) -> None:
    """Documents the precise, non-blocking semantic limit: SourceScopeBinding
    proves only that the MULTISET of approved content hashes matches what
    Source Scoping expected. It carries no path or evidence-id information
    (by design, per its docstring), so two requests with the SAME hash
    multiset but SWAPPED evidence_id/path assignments both validate against
    an identical binding. Safe integration with an external Source Scoping
    system that needs to pin specific evidence_id -> hash assignments would
    require additional fields; this is a scope limitation, not a bug within
    the v0.1 contract as written."""

    source = tmp_path / "source"
    source.mkdir()
    content_x = b"content-X"
    content_y = b"content-Y"
    _write(source, "path-one", content_x)
    _write(source, "path-two", content_y)

    binding = SourceScopeBinding(
        "c" * 64,
        tuple(sorted((_sha256(content_x), _sha256(content_y)))),
    )

    assignment_a = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "assignment-a",
            (
                _selection("evidence-alpha", "path-one", content_x),
                _selection("evidence-beta", "path-two", content_y),
            ),
            binding=binding,
        )
    )
    assignment_b = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "assignment-b",
            (
                _selection("evidence-beta", "path-one", content_x),
                _selection("evidence-alpha", "path-two", content_y),
            ),
            binding=binding,
        )
    )
    assert assignment_a.publication_status == assignment_b.publication_status
    assert assignment_a.approved_workspace_id != assignment_b.approved_workspace_id, (
        "workspace identity itself still differs by evidence_id, "
        "even though the same opaque binding validated both"
    )


def test_binding_sha256_field_is_opaque_and_unverified_beyond_shape(tmp_path: Path) -> None:
    """binding_sha256 is only shape-checked (64 lowercase hex chars); it is
    never recomputed or checked for correctness against anything by the
    materializer, consistent with its 'opaque hash from Source Scoping'
    contract. Any syntactically valid value is accepted."""

    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    arbitrary_but_well_formed = "f" * 64
    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("id", "record", data),),
            binding=SourceScopeBinding(arbitrary_but_well_formed, ()),
        )
    )
    assert receipt.source_scope_binding is not None
    assert receipt.source_scope_binding.binding_sha256 == arbitrary_but_well_formed


# ---------------------------------------------------------------------------
# PRODUCTION SCOPE / NO INTEGRATION CHECK (belt-and-suspenders alongside the
# existing production test_production_implementation_has_no_fixture_... test)
# ---------------------------------------------------------------------------


def test_materializer_module_has_no_integration_imports() -> None:
    import ast

    implementation_root = Path("src/continuity_ai/approved_workspace")
    forbidden_module_fragments = (
        "bridge",
        "source_scoping",
        "codex_session",
        "codex_process",
        "desktop",
        "project_report",
        "openai_provider",
        "codex",
    )
    for path in implementation_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                lowered = name.casefold()
                for fragment in forbidden_module_fragments:
                    assert fragment not in lowered, f"{path}: forbidden import fragment '{fragment}' in '{name}'"
