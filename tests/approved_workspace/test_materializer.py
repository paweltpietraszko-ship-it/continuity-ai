from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from continuity_ai.approved_workspace import (
    APPROVED_ATTESTATIONS_RELATIVE_PATH,
    APPROVED_MANIFEST_RELATIVE_PATH,
    ApprovedArtifactSelection,
    ApprovedHumanAttestation,
    ApprovedWorkspaceMaterializationError,
    ApprovedWorkspaceRequest,
    AttestationApprovalStatus,
    FailureCategory,
    PublicationStatus,
    SourceScopeBinding,
    compute_workspace_fingerprint,
    materialize_approved_workspace,
)
from continuity_ai.approved_workspace.materializer import (
    _MaterializationTestHooks,
    _is_reparse_point,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _selection(evidence_id: str, relative_path: str, data: bytes) -> ApprovedArtifactSelection:
    return ApprovedArtifactSelection(
        evidence_id=evidence_id,
        source_relative_path=relative_path,
        expected_sha256=_sha256(data),
        expected_byte_size=len(data),
    )


def _attestation(
    *,
    attestation_id: str = "attestation-1",
    downstream_data: dict[str, object] | None = None,
    status: AttestationApprovalStatus = AttestationApprovalStatus.APPROVED,
) -> ApprovedHumanAttestation:
    return ApprovedHumanAttestation(
        attestation_id=attestation_id,
        downstream_data=downstream_data or {"assertion": "Human-approved fact"},
        human_actor_id="reviewer-1",
        approval_reference="approval-1",
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


def _metadata_bytes(root: Path) -> tuple[bytes, bytes]:
    return (
        (root / APPROVED_ATTESTATIONS_RELATIVE_PATH).read_bytes(),
        (root / APPROVED_MANIFEST_RELATIVE_PATH).read_bytes(),
    )


def _source_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


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


def test_one_approved_file_is_copied_byte_for_byte_and_receipt_is_immutable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    data = b"\x00approved\r\nbytes\xff"
    _write(source, "records/approved.bin", data)

    receipt = materialize_approved_workspace(
        _request(
            source,
            tmp_path / "approved-only",
            (_selection("evidence-1", "records/approved.bin", data),),
        )
    )

    assert (receipt.destination_root / "records/approved.bin").read_bytes() == data
    assert receipt.publication_status is PublicationStatus.PUBLISHED
    assert receipt.approved_artifact_count == 1
    assert receipt.approved_attestation_count == 0
    assert receipt.failure_category is None
    with pytest.raises(FrozenInstanceError):
        receipt.approved_artifact_count = 2  # type: ignore[misc]


def test_multiple_files_preserve_paths_without_including_neighbours(tmp_path: Path) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    first = b"first approved"
    second = b"second approved"
    excluded = b"must remain outside"
    deferred = b"must remain outside too"
    _write(source, "one/record.txt", first)
    _write(source, "two/deep/record.dat", second)
    _write(source, "one/excluded-name.txt", excluded)
    _write(source, "two/deferred-name.txt", deferred)

    destination = tmp_path / "approved"
    materialize_approved_workspace(
        _request(
            source,
            destination,
            (
                _selection("approved-first", "one/record.txt", first),
                _selection("approved-second", "two/deep/record.dat", second),
            ),
        )
    )

    assert (destination / "one/record.txt").read_bytes() == first
    assert (destination / "two/deep/record.dat").read_bytes() == second
    assert not (destination / "one/excluded-name.txt").exists()
    assert not (destination / "two/deferred-name.txt").exists()


def test_excluded_names_and_ids_are_absent_from_all_generated_output(tmp_path: Path) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    approved = b"neutral approved bytes"
    _write(source, "selected.bin", approved)
    _write(source, "excluded-private-name.txt", b"excluded")
    _write(source, "deferred-private-name.txt", b"deferred")
    destination = tmp_path / "approved"

    materialize_approved_workspace(
        _request(
            source,
            destination,
            (_selection("approved-id", "selected.bin", approved),),
            (_attestation(),),
        )
    )

    all_output = b"\n".join(
        path.relative_to(destination).as_posix().encode("utf-8") + b"\n" + path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    )
    for forbidden in (
        b"excluded-private-name",
        b"deferred-private-name",
        b"excluded-evidence-id",
        b"deferred-evidence-id",
    ):
        assert forbidden not in all_output


def test_unselected_broken_link_is_not_enumerated_or_opened(tmp_path: Path) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    approved = b"approved"
    _write(source, "approved.txt", approved)
    try:
        (source / "excluded-link").symlink_to(source / "missing-target")
    except OSError:
        pytest.skip("Symbolic links are unavailable on this host")

    destination = tmp_path / "approved"
    materialize_approved_workspace(
        _request(
            source,
            destination,
            (_selection("approved", "approved.txt", approved),),
        )
    )
    assert (destination / "approved.txt").read_bytes() == approved


def test_attestations_are_canonical_deterministic_and_human_marked(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "approved", data)
    first = tmp_path / "first"
    second = tmp_path / "second"
    attestations = (
        _attestation(attestation_id="zeta", downstream_data={"z": 1, "a": {"y": 2, "x": 3}}),
        _attestation(attestation_id="alpha", downstream_data={"fact": "approved"}),
    )

    materialize_approved_workspace(
        _request(source, first, (_selection("evidence", "approved", data),), attestations)
    )
    materialize_approved_workspace(
        _request(source, second, (_selection("evidence", "approved", data),), tuple(reversed(attestations)))
    )

    assert _metadata_bytes(first) == _metadata_bytes(second)
    payload = json.loads((first / APPROVED_ATTESTATIONS_RELATIVE_PATH).read_bytes())
    assert [item["attestation_id"] for item in payload["attestations"]] == ["alpha", "zeta"]
    assert all(item["provenance"]["type"] == "human_attestation" for item in payload["attestations"])


@pytest.mark.parametrize(
    "status",
    [AttestationApprovalStatus.PENDING, AttestationApprovalStatus.REJECTED],
)
def test_pending_or_rejected_attestation_cannot_enter_output(
    tmp_path: Path, status: AttestationApprovalStatus
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "approved", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "approved", data),),
        (_attestation(status=status),),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


@pytest.mark.parametrize("sensitive_key", ["password", "session-key", "owner secret", "api_key"])
def test_sensitive_attestation_fields_are_rejected(tmp_path: Path, sensitive_key: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "approved", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "approved", data),),
        (_attestation(downstream_data={"nested": {sensitive_key: "not allowed"}}),),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_same_inputs_produce_same_manifest_and_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"stable"
    _write(source, "approved.txt", data)
    binding = SourceScopeBinding(
        binding_sha256="1" * 64,
        expected_source_fingerprints=(_sha256(data),),
    )

    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", (_selection("id", "approved.txt", data),), (_attestation(),), binding)
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", (_selection("id", "approved.txt", data),), (_attestation(),), binding)
    )

    assert (first.destination_root / APPROVED_MANIFEST_RELATIVE_PATH).read_bytes() == (
        second.destination_root / APPROVED_MANIFEST_RELATIVE_PATH
    ).read_bytes()
    assert first.manifest_fingerprint == second.manifest_fingerprint
    assert first.final_workspace_fingerprint == second.final_workspace_fingerprint
    assert first.approved_workspace_id == second.approved_workspace_id


def test_mismatched_caller_source_fingerprint_set_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"stable"
    _write(source, "approved", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("id", "approved", data),),
        binding=SourceScopeBinding("1" * 64, ("2" * 64,)),
    )
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_dictionary_order_does_not_affect_generated_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"stable"
    _write(source, "approved", data)
    first_attestation = _attestation(downstream_data={"b": 2, "a": {"d": 4, "c": 3}})
    second_attestation = _attestation(downstream_data={"a": {"c": 3, "d": 4}, "b": 2})

    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", (_selection("id", "approved", data),), (first_attestation,))
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", (_selection("id", "approved", data),), (second_attestation,))
    )
    assert _metadata_bytes(first.destination_root) == _metadata_bytes(second.destination_root)
    assert first.final_workspace_fingerprint == second.final_workspace_fingerprint


@pytest.mark.parametrize(
    "unsafe_path",
    ["/absolute.txt", "C:/absolute.txt", "C:drive-relative.txt", "folder/../escape.txt"],
)
def test_absolute_and_traversal_paths_are_rejected(tmp_path: Path, unsafe_path: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", unsafe_path, data),),
    )
    _assert_category(FailureCategory.UNSAFE_PATH, request)


def test_noncanonical_path_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "folder//record.txt", data),),
    )
    _assert_category(FailureCategory.UNSAFE_PATH, request)


def test_missing_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "missing.txt", b"expected"),),
    )
    _assert_category(FailureCategory.SOURCE_MISSING, request)


def test_directory_source_is_rejected_as_unsupported_file_type(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "directory").mkdir(parents=True)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "directory", b""),),
    )
    _assert_category(FailureCategory.SOURCE_NOT_REGULAR, request)


def test_wrong_expected_hash_is_rejected_and_stage_is_cleaned(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"actual"
    _write(source, "record", data)
    selection = ApprovedArtifactSelection("evidence", "record", "0" * 64, len(data))
    request = _request(source, tmp_path / "destination", (selection,))

    _assert_category(FailureCategory.SOURCE_FINGERPRINT_MISMATCH, request)
    assert not list(tmp_path.glob(".continuity-approved-stage-*"))


def test_wrong_expected_size_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"actual"
    _write(source, "record", data)
    selection = ApprovedArtifactSelection(
        "evidence", "record", _sha256(data), len(data) + 1
    )
    request = _request(source, tmp_path / "destination", (selection,))
    _assert_category(FailureCategory.SOURCE_FINGERPRINT_MISMATCH, request)


def test_source_mutation_after_copy_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"before"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
    )

    def mutate_source(
        _selection_value: ApprovedArtifactSelection, source_path: Path, _staged: Path
    ) -> None:
        source_path.write_bytes(b"after!")

    _assert_category(
        FailureCategory.SOURCE_MUTATED,
        request,
        hooks=_MaterializationTestHooks(after_artifact_copied=mutate_source),
    )


def test_selected_symbolic_link_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = tmp_path / "outside"
    target.write_bytes(b"outside")
    try:
        (source / "linked").symlink_to(target)
    except OSError:
        pytest.skip("Symbolic links are unavailable on this host")
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "linked", b"outside"),),
    )
    _assert_category(FailureCategory.SOURCE_LINK, request)


def test_reparse_point_directory_traversal_is_rejected_where_supported(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "record").write_bytes(b"outside")
    link = source / "linked-directory"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory reparse points are unavailable on this host")
    metadata = link.lstat()
    assert stat.S_ISLNK(metadata.st_mode) or (
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "linked-directory/record", b"outside"),),
    )
    _assert_category(FailureCategory.SOURCE_LINK, request)


def test_windows_reparse_attribute_is_rejected_without_following() -> None:
    metadata = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
    )
    assert _is_reparse_point(Path("not-opened"), metadata) is True  # type: ignore[arg-type]


def test_case_insensitive_path_collision_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    lower = b"lower"
    upper = b"upper"
    _write(source, "Folder/record.txt", lower)
    # A case-sensitive host can hold both; validation is deliberately portable.
    if os.path.normcase("A") != os.path.normcase("a"):
        _write(source, "folder/RECORD.TXT", upper)
    request = _request(
        source,
        tmp_path / "destination",
        (
            _selection("one", "Folder/record.txt", lower),
            _selection("two", "folder/RECORD.TXT", upper),
        ),
    )
    _assert_category(FailureCategory.PATH_COLLISION, request)


def test_destination_inside_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        source / "approved",
        (_selection("evidence", "record", data),),
    )
    _assert_category(FailureCategory.DESTINATION_OVERLAP, request)


def test_source_inside_destination_is_rejected(tmp_path: Path) -> None:
    destination = tmp_path / "destination"
    source = destination / "source"
    source.mkdir(parents=True)
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        destination,
        (_selection("evidence", "record", data),),
    )
    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(request)
    assert raised.value.category is FailureCategory.DESTINATION_OVERLAP


def test_existing_destination_is_rejected_without_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_bytes(b"unchanged")
    data = b"data"
    _write(source, "record", data)
    request = _request(source, destination, (_selection("evidence", "record", data),))

    with pytest.raises(ApprovedWorkspaceMaterializationError) as raised:
        materialize_approved_workspace(request)
    assert raised.value.category is FailureCategory.DESTINATION_EXISTS
    assert sentinel.read_bytes() == b"unchanged"


def test_publication_failure_leaves_no_destination_or_stage(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
    )

    def fail_publication(_stage: Path, _destination: Path) -> None:
        raise OSError("injected publication failure")

    _assert_category(
        FailureCategory.PUBLICATION_FAILED,
        request,
        hooks=_MaterializationTestHooks(before_publish=fail_publication),
    )
    assert not list(tmp_path.glob(".continuity-approved-stage-*"))


def test_staged_file_mutation_before_publication_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"data"
    _write(source, "record", data)
    request = _request(
        source,
        tmp_path / "destination",
        (_selection("evidence", "record", data),),
    )

    def mutate_stage(stage: Path, _destination: Path) -> None:
        (stage / "record").write_bytes(b"evil")

    _assert_category(
        FailureCategory.PUBLICATION_FAILED,
        request,
        hooks=_MaterializationTestHooks(before_publish=mutate_stage),
    )
    assert not list(tmp_path.glob(".continuity-approved-stage-*"))


def test_manifest_contains_only_approved_entries_and_opaque_binding(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "approved/record", data)
    _write(source, "excluded/record", b"not selected")
    binding = SourceScopeBinding("a" * 64, (_sha256(data),))
    destination = tmp_path / "destination"
    materialize_approved_workspace(
        _request(
            source,
            destination,
            (_selection("approved-evidence", "approved/record", data),),
            (_attestation(attestation_id="approved-attestation"),),
            binding,
        )
    )

    manifest = json.loads((destination / APPROVED_MANIFEST_RELATIVE_PATH).read_bytes())
    assert manifest["schema_version"] == "1.0"
    assert manifest["approved_artifacts"] == [
        {
            "byte_size": len(data),
            "evidence_id": "approved-evidence",
            "relative_path": "approved/record",
            "sha256": _sha256(data),
        }
    ]
    assert manifest["approved_attestations"]["entries"][0]["attestation_id"] == "approved-attestation"
    assert manifest["source_scope_binding"]["expected_source_fingerprints"] == [_sha256(data)]
    manifest_text = json.dumps(manifest)
    assert "excluded" not in manifest_text
    assert str(source) not in manifest_text
    assert str(destination) not in manifest_text


def test_workspace_fingerprint_changes_with_approved_file_bytes(tmp_path: Path) -> None:
    first_source = tmp_path / "source-one"
    second_source = tmp_path / "source-two"
    first_source.mkdir()
    second_source.mkdir()
    _write(first_source, "record", b"first")
    _write(second_source, "record", b"second")
    first = materialize_approved_workspace(
        _request(first_source, tmp_path / "first", (_selection("id", "record", b"first"),))
    )
    second = materialize_approved_workspace(
        _request(second_source, tmp_path / "second", (_selection("id", "record", b"second"),))
    )
    assert first.final_workspace_fingerprint != second.final_workspace_fingerprint


def test_workspace_fingerprint_changes_with_approved_attestation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"same"
    _write(source, "record", data)
    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", (_selection("id", "record", data),), (_attestation(downstream_data={"fact": "one"}),))
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", (_selection("id", "record", data),), (_attestation(downstream_data={"fact": "two"}),))
    )
    assert first.final_workspace_fingerprint != second.final_workspace_fingerprint


def test_fingerprint_does_not_depend_on_absolute_machine_path(tmp_path: Path) -> None:
    first_source = tmp_path / "machine-a" / "source"
    second_source = tmp_path / "machine-b" / "different" / "source"
    first_source.mkdir(parents=True)
    second_source.mkdir(parents=True)
    data = b"identical"
    _write(first_source, "nested/record", data)
    _write(second_source, "nested/record", data)
    first = materialize_approved_workspace(
        _request(first_source, tmp_path / "output-a", (_selection("id", "nested/record", data),))
    )
    second = materialize_approved_workspace(
        _request(second_source, tmp_path / "output-b", (_selection("id", "nested/record", data),))
    )
    assert _metadata_bytes(first.destination_root) == _metadata_bytes(second.destination_root)
    assert first.final_workspace_fingerprint == second.final_workspace_fingerprint


def test_approved_artifact_input_order_does_not_affect_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    alpha = b"alpha"
    bravo = b"bravo"
    _write(source, "alpha", alpha)
    _write(source, "nested/bravo", bravo)
    selections = (
        _selection("alpha-id", "alpha", alpha),
        _selection("bravo-id", "nested/bravo", bravo),
    )
    first = materialize_approved_workspace(
        _request(source, tmp_path / "first", selections)
    )
    second = materialize_approved_workspace(
        _request(source, tmp_path / "second", tuple(reversed(selections)))
    )
    assert _metadata_bytes(first.destination_root) == _metadata_bytes(
        second.destination_root
    )
    assert first.final_workspace_fingerprint == second.final_workspace_fingerprint


@pytest.mark.parametrize("attestations", [(), (_attestation(),)])
def test_empty_artifact_approval_fails_closed(
    tmp_path: Path, attestations: tuple[ApprovedHumanAttestation, ...]
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    request = _request(source, tmp_path / "destination", (), attestations)
    _assert_category(FailureCategory.INVALID_INPUT, request)


def test_original_workspace_remains_byte_identical(tmp_path: Path) -> None:
    source = tmp_path / "mixed"
    source.mkdir()
    approved = b"approved"
    _write(source, "approved/record", approved)
    _write(source, "excluded/record", b"excluded")
    _write(source, "deferred/record", b"deferred")
    before = _source_snapshot(source)

    materialize_approved_workspace(
        _request(
            source,
            tmp_path / "destination",
            (_selection("approved", "approved/record", approved),),
            (_attestation(),),
        )
    )
    assert _source_snapshot(source) == before


def test_receipt_fingerprint_can_be_recomputed_independently(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    data = b"approved"
    _write(source, "record", data)
    receipt = materialize_approved_workspace(
        _request(source, tmp_path / "destination", (_selection("id", "record", data),))
    )
    assert compute_workspace_fingerprint(receipt.destination_root) == receipt.final_workspace_fingerprint
    assert _sha256((receipt.destination_root / APPROVED_MANIFEST_RELATIVE_PATH).read_bytes()) == receipt.manifest_fingerprint


def test_production_implementation_has_no_fixture_specific_names_or_integrations() -> None:
    implementation_root = Path("src/continuity_ai/approved_workspace")
    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in implementation_root.glob("*.py")
    ).casefold()
    for forbidden in (
        "aurora",
        "meridian",
        "ember",
        "fixture",
        "continuity_ai.source_scoping",
        "continuity_ai.codex_session",
        "continuity_ai.bridge",
    ):
        assert forbidden not in production_text
