"""What a review is FOR — bug, feature request, UX confusion, praise, or other.

Everything upstream of this treated a review as a complaint, which is only true
of the 1-2 star half. A 4-star "love it, but please add dark mode" is a product
request, a 3-star "I can't find where to export" is a usability problem, and
neither should be counted as a crash.

Deterministic on purpose: rating plus cue phrases, no model. The same review
always gets the same label, so counts on a card never drift between page loads,
and it costs nothing to run over every signal on every request.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

BUG = "bug"
FEATURE_REQUEST = "feature_request"
UX_CONFUSION = "ux_confusion"
PRAISE = "praise"
OTHER = "other"

INTENTS = (BUG, FEATURE_REQUEST, UX_CONFUSION, PRAISE, OTHER)


def _cues(*phrases: str) -> re.Pattern:
    # Word-bounded so "add" never matches "address" and "lag" never "flag".
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE)


BUG_CUES = _cues(
    r"crash(?:es|ed|ing)?", r"doesn'?t work", r"does not work", r"not working",
    r"stopped working", r"won'?t (?:open|load|start|sync|work)", r"broken", r"bug(?:gy|s)?",
    r"freez(?:e|es|ing)", r"froze", r"error", r"fail(?:s|ed|ing)?", r"glitch(?:es|y)?",
    r"keeps? (?:closing|crashing|logging me out)", r"force clos(?:e|es)", r"lost (?:all )?my",
    r"disappear(?:ed|s)?", r"drain(?:s|ing)?", r"unusable", r"can'?t (?:log ?in|sign ?in|open)",
    r"lag(?:s|gy)?", r"slow",
)
REQUEST_CUES = _cues(
    r"i wish", r"wish (?:it|you|there)", r"please add", r"pls add", r"would love",
    r"it would be (?:great|nice|awesome|helpful)", r"would be (?:great|nice|awesome|helpful) (?:if|to)",
    r"can you (?:please )?add", r"could you (?:please )?add", r"feature request",
    r"hope (?:you|they) add", r"should (?:add|have|include)", r"needs? (?:an? )?option",
    r"add (?:an? )?option", r"bring back",
)
# Weaker cues: a request in a 3-5 star review, but in a 1-2 star one "my notes
# are missing" is data loss, not a wish list.
WEAK_REQUEST_CUES = _cues(r"missing", r"option to", r"support for", r"dark mode", r"widget")
UX_CUES = _cues(
    r"confus(?:ing|ed)", r"can'?t find", r"cannot find", r"couldn'?t find", r"how do i",
    r"how to", r"where is", r"where do i", r"hard to (?:find|use|navigate|understand)",
    r"not intuitive", r"unintuitive", r"no idea how", r"figure out", r"hidden",
)
PRAISE_CUES = _cues(
    r"love", r"great", r"awesome", r"excellent", r"amazing", r"perfect", r"best",
    r"fantastic", r"helpful", r"easy to use", r"works (?:well|great|perfectly)", r"thank(?:s| you)",
)


def classify(text: str | None, rating: int | None = None) -> str:
    """One intent per review.

    Precedence is the order a PM would triage in: something broken outranks a
    wish, a wish outranks confusion, and praise is only praise when nothing in
    the review asks for anything. A 5-star "great app but it crashes on export"
    is a bug report in a good mood, not praise.
    """
    t = " ".join((text or "").split())
    r = rating if isinstance(rating, int) else None
    bug = bool(BUG_CUES.search(t))
    request = bool(REQUEST_CUES.search(t)) or (
        (r is None or r >= 3) and bool(WEAK_REQUEST_CUES.search(t)))
    ux = bool(UX_CUES.search(t))

    if bug and (r is None or r <= 3 or not request):
        return BUG
    if request:
        return FEATURE_REQUEST
    if ux:
        return UX_CONFUSION
    if r is not None and r >= 4 and (PRAISE_CUES.search(t) or not t):
        return PRAISE
    if r is not None and r <= 2 and t:
        # A low star with no cue is still a complaint about something broken
        # more often than not — but say "other" rather than guess "bug" when the
        # text is empty.
        return BUG
    return OTHER


def empty_counts() -> dict[str, int]:
    return {k: 0 for k in INTENTS}


def count_intents(items: Iterable[tuple[str | None, int | None]]) -> dict[str, int]:
    """{intent: n} over (text, rating) pairs. Every key is always present so the
    UI never has to guess whether a missing key means zero."""
    out = empty_counts()
    for text, rating in items:
        out[classify(text, rating)] += 1
    return out


def primary_intent(counts: dict[str, int] | None) -> str | None:
    """The intent with the most reviews, ties broken by INTENTS order. None
    when there is nothing counted at all."""
    if not counts or not any(counts.values()):
        return None
    return max(INTENTS, key=lambda k: (counts.get(k, 0), -INTENTS.index(k)))


# ── performance: slow or draining ───────────────────────────────────────
#
# A sixth reading used to GROUP spikes on the Problems screen ("Slow or
# draining"), deliberately kept out of `classify` and INTENTS: the honesty
# guards and the detector treat a slow or draining app as a bug complaint, and
# every intent count in the app keeps its five keys. A review that names a
# crash or an error stays a bug even when it also says "slow".

PERFORMANCE = "performance"

PERFORMANCE_CUES = _cues(
    r"slow(?:s|er|ly|ness|ed)?", r"lag(?:s|gy|ging)?", r"laggy", r"sluggish",
    r"freez(?:e|es|ing)", r"froze(?:n)?", r"hang(?:s|ing)?", r"stutter(?:s|ing)?",
    r"takes? (?:forever|ages)", r"loading (?:forever|takes)",
    r"battery", r"drain(?:s|ed|ing)?", r"overheat(?:s|ed|ing)?", r"heat(?:s|ing)? up",
    r"(?:gets?|getting|runs?|running) (?:very |so |really )?hot", r"hot to the touch",
    r"memory", r"ram", r"storage hog", r"cpu", r"power hungry",
)
# What still makes it a bug: something broke rather than ran badly.
HARD_BUG_CUES = _cues(
    r"crash(?:es|ed|ing)?", r"doesn'?t work", r"does not work", r"not working",
    r"stopped working", r"broken", r"error", r"force clos(?:e|es)", r"lost (?:all )?my",
    r"disappear(?:ed|s)?", r"won'?t (?:open|load|start|sync|work)",
    r"can'?t (?:log ?in|sign ?in|open)", r"keeps? (?:closing|crashing|logging me out)",
)

# The four groups a new spike can land in, in triage order.
SPIKE_CATEGORIES = (BUG, UX_CONFUSION, PERFORMANCE, FEATURE_REQUEST)


def is_performance(text: str | None) -> bool:
    """True when the text is about speed, freezing, heat, battery or memory and
    names nothing that actually broke."""
    t = " ".join((text or "").split())
    return bool(PERFORMANCE_CUES.search(t)) and not HARD_BUG_CUES.search(t)


def classify_detail(text: str | None, rating: int | None = None) -> str:
    """`classify`, with the bugs that are really about performance split out.
    Only a review `classify` calls a bug can become PERFORMANCE, so every other
    intent is exactly what `classify` says."""
    label = classify(text, rating)
    return PERFORMANCE if label == BUG and is_performance(text) else label


def spike_category(texts: Iterable[str | None], counts: dict[str, int] | None = None) -> str:
    """Which of SPIKE_CATEGORIES a spike or theme belongs to.

    `texts` are what describes it (its title, a theme's quotes); `counts` the
    intents of the reviews behind it, when known. A spike led by requests is a
    request and one led by confusion is confusion; otherwise it is about
    performance when most of its texts are, and a bug by default — a GitHub
    burst with no reviews behind it is a bug report.
    """
    lead = primary_intent(counts)
    if lead == FEATURE_REQUEST:
        return FEATURE_REQUEST
    if lead == UX_CONFUSION:
        return UX_CONFUSION
    written = [t for t in texts if t and t.strip()]
    if written and sum(is_performance(t) for t in written) * 2 >= len(written):
        return PERFORMANCE
    return BUG
