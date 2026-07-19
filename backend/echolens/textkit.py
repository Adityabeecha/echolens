"""Zero-dependency text hygiene for real, messy feedback (v3.0).

Synthetic Lumo is clean English; real app reviews are not. These helpers let
the pipeline tolerate mixed languages, emoji-only reviews, and version strings
that don't parse — deterministically, with no heavyweight NLP dependency.

Design: NEVER crash on garbage input, and be transparent about what got
skipped (the caller reports "N non-English reviews excluded", it doesn't
silently swallow them).
"""
from __future__ import annotations

import re
from collections import Counter

# Small English stopword set — enough to make emergent themes readable without
# pulling in a corpus. Deliberately conservative.
STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his", "how",
    "its", "may", "new", "now", "old", "see", "two", "way", "who", "did", "yes",
    "this", "that", "with", "have", "from", "they", "been", "were", "your", "when",
    "what", "them", "than", "then", "some", "just", "like", "very", "will", "more",
    "into", "over", "even", "also", "app", "still", "would", "could", "there",
    "their", "about", "after", "since", "really", "much", "back", "want", "cant",
    "dont", "doesnt", "isnt", "im", "ive", "its",
}

_WORD_RE = re.compile(r"[a-zA-Z']+")
_VER_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def is_probably_english(text: str | None) -> bool:
    """Heuristic language gate — no model, no network. True when the text has
    enough Latin-script letters to be worth keyword-matching. Emoji-only and
    empty reviews return False (they carry a rating but no analyzable text);
    CJK / Cyrillic / Arabic reviews return False (Latin share too low)."""
    text = (text or "").strip()
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters) >= 0.6


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    """Extract (major, minor, patch) from a version string, tolerating prefixes
    and suffixes ('v3.2', '3.2.0-beta', 'build 3.2'). Returns None if there is
    no numeric version at all — callers must handle None rather than assuming a
    parse always succeeds."""
    if not value:
        return None
    m = _VER_RE.search(str(value))
    if not m:
        return None
    return tuple(int(g) if g else 0 for g in m.groups())  # type: ignore[return-value]


def tokenize(text: str | None) -> list[str]:
    """Lowercase content words (len > 2, not a stopword)."""
    return [t for t in _WORD_RE.findall((text or "").lower())
            if len(t) > 2 and t not in STOPWORDS]


def top_themes(texts: list[str], k: int = 6) -> list[dict]:
    """Emergent complaint themes with NO fixed keyword list — so it works on any
    app, not just Lumo. Ranks bigrams (specific, weighted higher) above unigrams
    and drops a unigram already covered by a chosen bigram.

    Returns [{"label": str, "count": int}] most-frequent first."""
    uni: Counter[str] = Counter()
    bi: Counter[str] = Counter()
    for t in texts:
        toks = tokenize(t)
        uni.update(toks)
        for a, b in zip(toks, toks[1:]):
            bi[f"{a} {b}"] += 1

    scored: list[tuple[float, int, str]] = []
    for phrase, c in bi.items():
        if c >= 2:                       # a bigram worth surfacing recurs
            scored.append((c * 2.0, c, phrase))
    covered = {w for _, _, p in scored for w in p.split()}
    for word, c in uni.items():
        if word not in covered:
            scored.append((float(c), c, word))

    scored.sort(key=lambda x: (-x[0], x[2]))
    return [{"label": phrase, "count": count} for _, count, phrase in scored[:k]]
