"""Deterministic display labels; raw discovery statements remain evidence.

Identity comes from discovery, never from these display transformations. Legacy
cached results are formatted on read so a title change needs no model request.
"""
from __future__ import annotations

import re

from echolens.textkit import STOPWORDS

MAX_TITLE_CHARS = 60
_PRONOUNS = {"i", "me", "my", "mine", "myself", "we", "us", "our", "ours",
             "ourselves", "you", "your", "yours", "yourself", "he", "his", "him",
             "she", "her", "hers", "they", "them", "their", "theirs", "it", "its"}
_FILLER = {"keep", "keeps", "kept", "always", "constantly", "repeatedly"}
_COMPLAINT_FORMS = {
    "crashing": "crash", "crashes": "crash", "crashed": "crash",
    "freezing": "freeze", "freezes": "freeze", "frozen": "freeze", "froze": "freeze",
    "hanging": "hang", "hangs": "hang", "hung": "hang",
    "lagging": "lag", "lags": "lag", "lagged": "lag",
    "failing": "fail", "fails": "fail", "failed": "fail",
}
_ACTIONS = {"open": "opening", "load": "loading", "play": "playing",
            "save": "saving", "upload": "uploading", "download": "downloading",
            "clear": "clearing", "start": "starting", "switch": "switching",
            "sync": "syncing", "close": "closing", "edit": "editing"}
_CONTENT_FORMS = {**_COMPLAINT_FORMS, **{v: k for k, v in _ACTIONS.items()}}
# Keep negation as content rather than discarding it as a stopword.
_GLUE = (STOPWORDS - {"not"}) | _PRONOUNS | _FILLER | {
    "a", "an", "to", "of", "in", "on", "at", "by", "as", "is", "am", "be",
    "before", "during", "whenever", "and", "or", "the",
}


def _label_words(text: str) -> list[str]:
    text = text.lower().replace("\u2019", "'")
    text = re.sub(r"\b(i|we|you|they|he|she|it)'(?:m|re|ve|d|ll|s)\b", r"\1", text)
    text = re.sub(r"\bcan't\b", "cannot", text)
    text = re.sub(r"\bwon't\b", "will not", text)
    text = re.sub(r"\b([a-z]+)n't\b", r"\1 not", text)
    # Preserve the action as a condition, rather than producing "when open".
    text = re.sub(r"\bwhenever\b", "when", text)
    actions = "|".join(_ACTIONS)
    text = re.sub(rf"\b(when|after|before|while)\s+(?:i|we|you|they)\s+({actions})\b",
                  lambda m: f"{m[1]} {_ACTIONS[m[2]]}", text)
    words = re.findall(r"[^\W_]+(?:'[^\W_]+)?", text, flags=re.UNICODE)
    words = [_COMPLAINT_FORMS.get(w, w) for w in words
             if w not in _PRONOUNS | _FILLER | {"a", "an", "the", "am"}]
    phrase = " ".join(words)
    # Common complaint constructions need a noun phrase, not just pronoun
    # deletion ("have to restart" must not become "to restart").
    phrase = re.sub(r"^(?:have|need) to restart (.+?) every time$",
                    r"repeated \1 restart required", phrase)
    phrase = re.sub(r"^(?:do|does) not like (.+)$", r"dislike of \1", phrase)
    phrase = re.sub(r"^(?:lost|losing) (?:all )?(.+)$", r"loss of \1", phrase)
    phrase = re.sub(r"^cannot (.+)$", r"failure to \1", phrase)
    playback = re.fullmatch(r"(videos?|audio|music) (?:are |is |will |does |do )?not (?:play|playing)", phrase)
    if playback:
        medium = "video" if playback[1] == "videos" else playback[1]
        phrase = f"{medium} playback failure"
    words = phrase.split()
    while words and words[0] in {"and", "is", "are", "was", "were", "have", "been", "app"}:
        words.pop(0)
    return words


def theme_title(text: str) -> str:
    """A sentence-case label bounded at a word boundary, with no model call."""
    label = " ".join(_label_words(text)) or "Recurring complaint"
    if len(label) > MAX_TITLE_CHARS:
        label = label[:MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0] + "\u2026"
    return label[0].upper() + label[1:]


def _content_words(text: str) -> set[str]:
    words = set()
    for word in _label_words(text):
        if word in _GLUE:
            continue
        word = _CONTENT_FORMS.get(word, word)
        if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        words.add(word)
    return words


def display_themes(result: dict, *, preferred_slugs: set[str] | None = None) -> dict:
    """Merge wording variants and format titles without mutating stored evidence.

    Compare full content (before truncation), with Jaccard >= 0.6. Connected
    components merge transitive wording variants. Prefer an identity already
    queued/investigated, else retain the first; other slugs remain aliases.
    """
    themes = result.get("themes") or []
    content = [_content_words(t.get("statement", "")) for t in themes]
    parents = list(range(len(themes)))

    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i

    for i, words in enumerate(content):
        for j in range(i):
            union = words | content[j]
            if union and len(words & content[j]) / len(union) >= 0.6:
                left, right = root(i), root(j)
                parents[max(left, right)] = min(left, right)

    groups: dict[int, list[dict]] = {}
    for i, theme in enumerate(themes):
        groups.setdefault(root(i), []).append(theme)
    out = []
    for group in groups.values():
        representative = next((t for t in group if t["slug"] in (preferred_slugs or set())), group[0])
        title = dict(representative)
        title["statement"] = theme_title(title.get("statement", ""))
        if len(group) > 1:
            if all("_review_ids" in t for t in group):
                title["count"] = len({rid for t in group for rid in t["_review_ids"]})
            else:
                # Legacy caches lack membership: retain their aggregate counts.
                title["count"] = sum(t["count"] for t in group)
            title["verbatims"] = list(dict.fromkeys(v for t in group for v in t.get("verbatims", [])))[:3]
            for field, choose in (("first_seen", min), ("last_seen", max)):
                dates = [t[field] for t in group if t.get(field)]
                title[field] = choose(dates) if dates else None
            title["merged_slugs"] = list(dict.fromkeys(
                slug for t in group for slug in [t["slug"], *t.get("merged_slugs", [])]
                if slug != title["slug"]))
            trends = {t.get("trend", "flat") for t in group}
            title["trend"] = next(iter(trends)) if len(trends) == 1 else "flat"
        title.pop("_review_ids", None)
        out.append(title)
    displayed = {**result, "themes": out}
    if themes and all("_review_ids" in t for t in themes):
        clustered = len({rid for t in themes for rid in t["_review_ids"]})
        displayed.update(clustered=clustered, other=result["reviews_considered"] - clustered)
    return displayed
