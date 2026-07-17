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
    """Reject production inputs that contain or point at test-only ground truth data."""

    resolved_parts = set(project_root.parts)
    if _TEST_ONLY_DIRECTORY in resolved_parts:
        raise GroundTruthAccessError("Production reasoning cannot receive the test-only directory.")
    if any(path.name == _TEST_ONLY_FILENAME for path in project_root.rglob(_TEST_ONLY_FILENAME)):
        raise GroundTruthAccessError("Production artifact input cannot contain test-only ground truth.")


@contextmanager
def open_production_artifact(path: Path) -> Iterator[BinaryIO]:
    """Open a legitimate artifact while blocking test-only ground truth by filename."""

    if path.name == _TEST_ONLY_FILENAME:
        raise GroundTruthAccessError("Production reasoning cannot open test-only ground truth.")
    with path.open("rb") as handle:
        yield handle
