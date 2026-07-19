"""Canonical JSON and hashing shared by approved-workspace metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a validated JSON value deterministically as UTF-8 plus LF."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 hex digest."""

    return hashlib.sha256(data).hexdigest()


def normalize_json_value(value: Any) -> Any:
    """Copy supported JSON into deterministic containers, rejecting ambiguity."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError("Floating-point attestation data is not canonical.")
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or key in normalized:
                raise TypeError("Attestation object keys must be unique strings.")
            normalized[key] = normalize_json_value(item)
        return dict(sorted(normalized.items()))
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [normalize_json_value(item) for item in value]
    raise TypeError("Attestation data contains a non-JSON value.")
