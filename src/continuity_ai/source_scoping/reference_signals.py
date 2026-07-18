"""Generic signal extraction for the deterministic reference provider."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

PROJECT_MENTION = re.compile(r"\bProject\s+([A-Z][A-Za-z0-9_-]{1,63})\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{3,}")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CODE = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]{2,})+\b")
_STOP = frozenset({
    "about", "after", "before", "briefing", "current", "document", "evidence",
    "final", "from", "general", "latest", "location", "meeting", "notes",
    "project", "record", "return", "source", "status", "the", "this", "update",
    "version", "with", "without", "workstream",
})


def fold(value: str) -> str:
    return " ".join(value.casefold().split())


def signals(text: str, target_project: str) -> frozenset[str]:
    target_parts = set(fold(target_project).split())
    words = {
        word.casefold()
        for word in _WORD.findall(text)
        if word.casefold() not in _STOP and word.casefold() not in target_parts
    }
    dates = {f"date:{value}" for value in _DATE.findall(text)}
    codes = {f"code:{value.casefold()}" for value in _CODE.findall(text)}
    return frozenset(words | dates | codes)


def spans_by_evidence(spans: tuple[Any, ...]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for span in spans:
        grouped[span.evidence_id].append(span)
    return grouped
