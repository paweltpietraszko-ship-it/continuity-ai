"""Safe artifact input helpers for production reasoning code."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

_TEST_ONLY_DIRECTORY = "test_only"
_TEST_ONLY_FILENAME = "ground_truth.json"


class GroundTruthAccessError(RuntimeError):
    """Raised when production code is directed at test-only ground truth data."""


def validate_production_artifact_root(project_root: Path) -> None:
    """Reject production inputs that contain or point at test-only ground truth data.

    Forbidden directory and filename checks are case-insensitive, and the whole
    subtree is scanned so a forbidden path is rejected even if nothing in the
    manifest references it.
    """

    lowered_root_parts = {part.lower() for part in project_root.parts}
    if _TEST_ONLY_DIRECTORY in lowered_root_parts:
        raise GroundTruthAccessError("Production reasoning cannot receive the test-only directory.")

    for path in project_root.rglob("*"):
        if path.is_dir() and path.name.lower() == _TEST_ONLY_DIRECTORY:
            raise GroundTruthAccessError("Production artifact input cannot contain a test-only directory.")
        if path.is_file() and path.name.lower() == _TEST_ONLY_FILENAME:
            raise GroundTruthAccessError("Production artifact input cannot contain test-only ground truth.")


@contextmanager
def open_production_artifact(path: Path) -> Iterator[BinaryIO]:
    """Open a legitimate artifact while blocking test-only ground truth by filename, case-insensitively."""

    if path.name.lower() == _TEST_ONLY_FILENAME:
        raise GroundTruthAccessError("Production reasoning cannot open test-only ground truth.")
    with path.open("rb") as handle:
        yield handle
