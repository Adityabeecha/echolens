"""Shared helpers for the deterministic tool layer.

Token discipline lives HERE (PRD §5.4): every tool truncates its output
(top-k items, char-capped snippets) before anything reaches LLM context.
"""
from __future__ import annotations

from datetime import datetime, timezone

from echolens.config import TOOL_RESULT_MAX_ITEMS, TOOL_SNIPPET_MAX_CHARS


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def snippet(text: str, cap: int = TOOL_SNIPPET_MAX_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= cap else text[: cap - 1] + "…"


def cap_items(items: list, limit: int | None = None) -> tuple[list, int]:
    """Return (top-k items, total count before truncation)."""
    k = min(limit or TOOL_RESULT_MAX_ITEMS, TOOL_RESULT_MAX_ITEMS)
    return items[:k], len(items)


def terms_of(query: str) -> list[str]:
    return [t.lower() for t in query.split() if len(t) > 2]


def match_score(text: str, terms: list[str]) -> int:
    """Deterministic keyword rank: number of distinct query terms present."""
    lower = text.lower()
    return sum(1 for t in terms if t in lower)
