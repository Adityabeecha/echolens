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


# ── theme names ─────────────────────────────────────────────────────────
#
# Emergent theme labels used to be two salient words, alphabetised and
# title-cased: "Behind Cost", "Further Google", "Appear Background". A label is
# a noun phrase or nothing. No tagger download: small closed-class word lists
# decide what may not start or end a phrase, and the head must be noun-like.

THEME_LABEL_MAX = 40

_PREPOSITIONS = frozenset(
    "about above across after against along among around as at before behind below "
    "beneath beside between beyond by despite down during except for from in inside "
    "into near of off on onto out outside over past per since than through to toward "
    "towards under until unlike up upon via with within without".split())
_CONJUNCTIONS = frozenset(
    "although and because but either even if neither nor or so though unless whereas "
    "whether while yet".split())
_ADVERBS = frozenset(
    "again ago almost already also always anymore anyway away else ever everywhere "
    "further furthermore here however instead later maybe meanwhile never often once "
    "perhaps quite rather sometimes somewhere soon still then there today tomorrow too "
    "twice very yesterday".split())
# Verbs that are never a complaint noun. Words that are both ("crash", "drain",
# "sync", "update") are deliberately absent: "battery drain" is a noun phrase.
_VERBS = frozenset(
    "appear appears appeared become becomes came come comes did does doing done gave "
    "get gets give gives go goes going gone got happen happens happened help keep "
    "keeps know let made make makes need needs put said say says see seem seems "
    "seemed show shows take takes tell think tried tries try trying use used uses "
    "using want wanted went work works worked".split())
# Adjectives may modify a head ("automatic backup") but are never a head. Bare
# -ly words are adverbs except for the listed nouns.
_ADJECTIVES = frozenset(
    "actual annoying automatic available awful bad best better big black blank broken "
    "constant current different difficult easy empty endless entire extra fake fast "
    "few free frequent full good great hard high horrible huge impossible latest "
    "little long low main many multiple new old other poor possible previous random "
    "real recent same several short simple slow small stupid sudden terrible "
    "unable unavailable useless whole worse worst wrong".split())
_LY_NOUNS = frozenset({"family", "reply", "supply", "assembly", "anomaly", "rally", "ally"})


def _not_noun(word: str) -> bool:
    """True for words that cannot head (or close) a noun phrase."""
    return (len(word) < 3 or word in STOPWORDS or word in _PREPOSITIONS
            or word in _CONJUNCTIONS or word in _ADVERBS or word in _VERBS
            or word in _ADJECTIVES or not word.isalpha()
            or (word.endswith("ly") and word not in _LY_NOUNS))


def _modifier_ok(word: str) -> bool:
    """An adjective or noun that may open a noun phrase."""
    return word in _ADJECTIVES or not _not_noun(word)


def _sentence_case(phrase: str) -> str:
    if len(phrase) > THEME_LABEL_MAX:
        phrase = phrase[:THEME_LABEL_MAX].rsplit(" ", 1)[0]
    return phrase[:1].upper() + phrase[1:]


def theme_label(terms: list[str] | None, text: str | None = None) -> str | None:
    """A noun-phrase name for an emergent theme, or None if none exists.

    `terms` are the theme's salient words, most salient first. A two-word
    phrase is preferred when `text` (the complaint itself) has two terms side
    by side, e.g. "background sync"; without text, adjacent terms only pair when
    both are nouns — an adjective beside a noun in a bag of keywords is weak
    evidence it was ever said together. Otherwise the theme's top content noun.
    Sentence case (first word only), at most THEME_LABEL_MAX characters.
    """
    words = [w.strip("'\"").lower() for w in (terms or []) if w and w.strip("'\"")]
    rank = {w: i for i, w in reversed(list(enumerate(words)))}
    pairs: list[tuple[int, str]] = []
    if text:
        seq = _WORD_RE.findall(text.lower())
        for a, b in zip(seq, seq[1:]):
            if a in rank and b in rank and a != b and _modifier_ok(a) and not _not_noun(b):
                pairs.append((min(rank[a], rank[b]), f"{a} {b}"))
    if not pairs:
        for i, (a, b) in enumerate(zip(words, words[1:])):
            if a != b and not _not_noun(a) and not _not_noun(b):
                pairs.append((i, f"{a} {b}"))
    if pairs:
        return _sentence_case(min(pairs)[1])
    noun = next((w for w in words if not _not_noun(w)), None)
    return _sentence_case(noun) if noun else None


# ── case headlines ──────────────────────────────────────────────────────

_CITATION_RE = re.compile(r"\s*\[(?:ev|evidence)[_-]?[\w-]*\]", re.IGNORECASE)
_QUOTES = str.maketrans({"‘": "'", "’": "'", "‛": "'", "′": "'",
                         "“": '"', "”": '"', "‟": '"', "″": '"'})
# "V3.2.0's" is a capitalised sentence start, not how anyone writes a version.
_CAPITAL_VERSION_RE = re.compile(r"(?<![\w.])V(?=\d+(?:\.\d+)+)")


def clean_headline(text: str | None) -> str:
    """The one-line title of a case, ready for a card, brief, Slack or email.

    Inline citation tags ("[ev_001][ev_002]") belong in the prose, where each
    can be followed; in a headline they are noise. Curly quotes become straight
    so one title is never spelled two ways, and version strings keep their
    lowercase "v". For titles only — prose bodies keep their citations.
    """
    out = _CITATION_RE.sub("", text or "").translate(_QUOTES)
    out = re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s{2,}", " ", out)).strip()
    return _CAPITAL_VERSION_RE.sub("v", out)


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


# ── GitHub issue templates ───────────────────────────────────────────────
#
# Repos file every issue through a template ("### Brief Summary", "- [x] I have
# searched existing issues…"). Counted as text, that boilerplate is the most
# common phrase in the tracker, so it surfaced as spikes ("'searched existing'
# issue reports piling up"). These helpers drop it before themes are mined.

_TEMPLATE_LINE = re.compile(
    r"^\s*(#{1,6}\s|[-*]\s*\[[ xX]\]|<!--|-->|\|?\s*:?-{3,}|\[[^\]]+\]:\s*#)")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# Links, fenced code and inline code are pasted context (logs, stack traces,
# URLs), not the reporter's words: "github com" was a top "theme".
_NOISE = re.compile(r"```.*?```|`[^`\n]*`|!\[[^\]]*\]\([^)]*\)|<[^>\n]+>|https?://\S+|www\.\S+", re.S)
# Build and environment stamps ("Brave: 1.95.102 Chromium: 153.0.8010.48
# (Official Build) (64-bit) Revision: 72a3…") are pasted into most reports;
# "official build" became a spike on Brave.
_ENV = re.compile(r"\b(?:chromium|revision|build|version)\b\s*[:|]?\s*\d\S*|\(official build\)|\(\d{2}-bit\)"
                  r"|\b\d+(?:\.\d+){2,}\S*", re.I)


def _norm_line(line: str) -> str:
    return re.sub(r"\W+", " ", line.lower()).strip()


# "- Brand/model: OnePlus 11", "OS: macOS 15": a form field and its answer.
_FIELD = re.compile(r"^\s*[-*]?\s*([A-Za-z][\w /()-]{1,30}?)\s*:\s*\S")


def _field_key(line: str) -> str | None:
    m = _FIELD.match(line)
    return f"field:{_norm_line(m.group(1))}" if m and len(m.group(1).split()) <= 4 else None


def issue_boilerplate(bodies: list[str], share: float = 0.08, min_issues: int = 5) -> set[str]:
    """Normalised lines repeated word for word across many issues (at least
    `share` of them, and never fewer than 8): the repo's issue and PR
    templates, whatever their wording. People describing a bug never repeat
    each other line for line; templates always do."""
    if len(bodies) < min_issues:
        return set()
    counts: Counter = Counter()
    for body in bodies:
        lines = _COMMENT.sub(" ", body or "").splitlines()
        # A field label repeated across issues is the template asking for
        # environment details ("Brand/model:", "Operating system:"); the
        # answers differ, so the whole line never repeats word for word.
        counts.update({_norm_line(l) for l in lines if _norm_line(l)}
                      | {k for l in lines if (k := _field_key(l))})
    floor = max(8, int(len(bodies) * share))
    return {line for line, n in counts.items() if n >= floor}


def issue_text(title: str | None, body: str | None, boilerplate: set[str] | None = None) -> str:
    """An issue's own words: its title plus body lines that are not template
    headings, checklists, comments or repo-wide boilerplate."""
    keep = []
    for line in _ENV.sub(" ", _NOISE.sub(" ", _COMMENT.sub(" ", body or ""))).splitlines():
        norm = _norm_line(line)
        if not norm or _TEMPLATE_LINE.match(line) or (boilerplate and (
                norm in boilerplate or _field_key(line) in boilerplate)):
            continue
        keep.append(line.strip())
    return " ".join([title or "", *keep]).strip()
