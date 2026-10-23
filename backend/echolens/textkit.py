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


# ── language detection ──────────────────────────────────────────────────
#
# Good enough to decide "translate this or not", not a linguistics library.
# Non-Latin scripts are identified by Unicode block; Latin-script languages by
# which function words (and a few telltale letters) the text contains. A text
# too short or too ambiguous to call is "und" — undetermined — and is left
# alone rather than sent to translation on a guess.

UNDETERMINED = "und"

LANG_NAMES = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French",
    "de": "German", "it": "Italian", "nl": "Dutch", "tr": "Turkish",
    "id": "Indonesian", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
    "ar": "Arabic", "hi": "Hindi", "ja": "Japanese", "zh": "Chinese",
    "ko": "Korean", "th": "Thai", "el": "Greek", "he": "Hebrew",
}

# (language, first codepoint, last codepoint). Any kana makes it Japanese even
# though Japanese also uses Han characters, so that is checked first.
_SCRIPTS = [
    ("ja", 0x3040, 0x30FF), ("ko", 0xAC00, 0xD7AF), ("ko", 0x1100, 0x11FF),
    ("zh", 0x4E00, 0x9FFF), ("ru", 0x0400, 0x04FF), ("ar", 0x0600, 0x06FF),
    ("hi", 0x0900, 0x097F), ("th", 0x0E00, 0x0E7F), ("el", 0x0370, 0x03FF),
    ("he", 0x0590, 0x05FF),
]

_FUNCTION_WORDS: dict[str, set[str]] = {
    "en": set("the and is it my to of this that in on for not but was you with have are so "
              "when just very can after since it's i'm i".split()),
    "es": set("el la los las que y en un una es por con para no muy pero mi lo se del al "
              "como más está desde cuando también porque".split()),
    "pt": set("o os as que e em um uma é não com para muito mas meu do da dos das no na "
              "está quando também porque".split()),
    "fr": set("le la les des et est un une que pas pour avec ne je il mais très sur dans "
              "du au ce cette depuis".split()),
    "de": set("der die das und ist nicht ich ein eine mit es zu auf für sehr aber den dem "
              "wenn seit auch".split()),
    "it": set("il lo la gli le di che è un una non per con mi molto ma del della sono "
              "quando anche".split()),
    "nl": set("de het een en is niet ik van op met voor maar heel als dat zijn ook".split()),
    "tr": set("ve bir bu çok için ama ile değil ben gibi daha neden".split()),
    "id": set("dan yang ini itu tidak saya dengan untuk sangat tapi ada ke bisa".split()),
    "pl": set("i w nie się na to jest że z do jak ale bardzo".split()),
}

# Letters that all but settle it. Worth two function words each.
_TELLTALE = {"es": "ñ¿¡", "pt": "ãõ", "de": "ß", "tr": "ğşı", "pl": "łąęśżźćń"}
_LATIN_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def detect_language(text: str | None) -> str:
    """An ISO 639-1 code for `text`, or "und" when it cannot be called."""
    letters = [c for c in (text or "") if c.isalpha()]
    if len(letters) < 3:
        return UNDETERMINED
    script: Counter[str] = Counter()
    for c in letters:
        cp = ord(c)
        for lang, lo, hi in _SCRIPTS:
            if lo <= cp <= hi:
                script[lang] += 1
                break
    if sum(script.values()) / len(letters) >= 0.3:
        if script["ja"]:
            return "ja"
        lang = script.most_common(1)[0][0]
        if lang == "ru" and any(c in "іїєґ" for c in (text or "").lower()):
            return "uk"
        return lang

    low = (text or "").lower()
    words = _LATIN_WORD_RE.findall(low)
    scores = {lang: sum(1 for w in words if w in fw) for lang, fw in _FUNCTION_WORDS.items()}
    for lang, chars in _TELLTALE.items():
        if any(c in low for c in chars):
            scores[lang] += 2
    best = max(scores, key=lambda k: (scores[k], k == "en"))
    if scores[best] == 0 or (scores[best] < 2 and len(words) >= 6):
        return UNDETERMINED
    # English wins ties: a mostly-English review with one "de" in it is English.
    return "en" if scores["en"] >= scores[best] else best


def language_name(code: str | None) -> str:
    return LANG_NAMES.get(code or "", code or "an unknown language")


def needs_translation(code: str | None) -> bool:
    return bool(code) and code not in ("en", UNDETERMINED)


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
