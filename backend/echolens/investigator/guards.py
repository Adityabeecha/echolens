"""Deterministic honesty + budget guards (PRD §5.6–5.7, §14).

These run in code, never in prompts. The agent cannot talk its way past them.
"""
from __future__ import annotations

import re

from echolens.config import (
    INSUFFICIENT_CONFIDENCE,
    CROSS_POST_SIMILARITY,
    MIN_CROSS_POST_WORDS,
    MIN_DISTINCT_SOURCES,
    MIN_INDEPENDENT_EVIDENCE,
    SUPPORT_CONFIDENCE,
)
from echolens.investigator.state import Budget
from echolens.textkit import STOPWORDS, tokenize


_GENERIC_ANOMALY_TERMS = {
    "app", "application", "complaint", "complaints", "feedback", "issue", "issues",
    "latest", "negative", "problem", "problems", "product", "recent", "report",
    "reports", "review", "reviews", "spike", "surge", "theme", "update", "user",
    "users", "volume",
}

CAUSAL_MARKERS = re.compile(
    r"\b(caus(?:e|es|ed|ing)|driv(?:es|en|ing)|because|due to|led to|leads to|"
    r"result(?:s|ed)? (?:in|from)|root cause|responsible for|triggered|"
    # Added after the audit: all of these state a cause in plain English and
    # every one of them published unblocked.
    r"stems? from|stemmed from|attributable to|attributed to|the trigger for|"
    r"the reason(?: (?:that|why))?|owing to|thanks to|brought about by|"
    r"introduced by|down to|explains?(?: why)?|arises? from|arose from|"
    r"originates? from|traced? (?:back )?to|blame[ds]? on|"
    # Added 2026-10-22: blame and breakage phrasing that still published
    # uncited — "is the culprit", "broke sync", "a direct consequence of".
    r"culprit|to blame|consequence of|broke|breaks|broken by|"
    r"introduc(?:e|es|ed|ing)\b.{0,40}?\b(?:bug|regression|issue|problem|crash|drain|leak)|"
    r"regress(?:ed|ion) (?:in|since|after|with)|"
    r"(?:kills?|killed|drains?|drained) (?:the )?(?:battery|app|performance)|"
    r"since (?:the )?(?:update|release|upgrade|v?\d+\.\d+))\b",
    re.IGNORECASE,
)
EVIDENCE_REF = re.compile(r"\bev_\d+\b")


def hypothesis_relevant(hypothesis: dict, trigger: dict) -> bool:
    """Keep causal guesses tied to the actual complaint being investigated.

    Product names rarely describe what a product does, while the detected metric
    and customer-language description do. When those fields contain specific
    anchors, a proposed hypothesis (or its next test) must retain at least one.
    Vague volume-only anomalies have no anchors and stay permissive.
    """
    # Aggregate detectors say only that ratings or negative volume moved; they
    # deliberately do not name the underlying complaint. Lexically policing a
    # cause against words such as "star", "daily" or "baseline" would reject
    # every useful product-level explanation. Complaint-specific detectors do
    # carry a customer-derived theme, so only those can support this guard.
    if trigger.get("type") in {"negative_review_spike", "rating_drop"}:
        return True
    trigger_text = f"{trigger.get('metric', '')} {trigger.get('description', '')}"
    anchors = {
        term for term in tokenize(trigger_text)
        if len(term) > 2 and term not in STOPWORDS and term not in _GENERIC_ANOMALY_TERMS
    }
    if not anchors:
        return True
    proposal = set(tokenize(
        f"{hypothesis.get('statement', '')} {hypothesis.get('next_test', '')}"
    ))
    return bool(anchors & proposal)

# Clause boundary for the claim-grounding scan.
#
# Terminal punctuation, a line break, OR a clause separator — `;` `:` and a
# comma before a conjunction. Splitting on `.!?` alone let a causal claim ride
# on a citation that belonged to a DIFFERENT clause of the same sentence:
#
#     "Sync is broken [ev_001]; the crash was caused by the v3.2 release."
#
# is one sentence to a `.`-only splitter, so the uncited second half inherited
# ev_001 and published unchallenged. Each clause now has to carry its own
# citation.
SENTENCE_SPLIT = re.compile(
    r"(?<=[.!?])\s+"                       # sentence end
    r"|\n+"                                # line break
    r"|\s*[;:]\s*"                         # clause separator
    r"|,\s+(?=(?:which|and|so|but|because|since|as)\b)"  # comma + conjunction
)


def budget_exceeded(budget: Budget) -> list[str]:
    """Return the list of exhausted limits (empty = within budget). Caps are
    scaled by the one-time extension factor (v2.0), plus any headroom a
    reviewer explicitly granted (v15) — still a hard ceiling either way."""
    reasons = []
    if budget.iterations >= budget.cap_iterations():
        reasons.append(f"iterations {budget.iterations}/{int(budget.cap_iterations())}")
    if budget.tool_calls >= budget.cap_tool_calls():
        reasons.append(f"tool_calls {budget.tool_calls}/{int(budget.cap_tool_calls())}")
    if budget.tokens >= budget.cap_tokens():
        reasons.append(f"tokens {budget.tokens}/{int(budget.cap_tokens())}")
    if budget.cost_usd >= budget.cap_cost_usd():
        reasons.append(f"cost ${budget.cost_usd:.2f}/${budget.cap_cost_usd():.2f}")
    # elapsed includes wall-clock spent before a restart (restored from checkpoint),
    # so a resumed investigation can't get its full time budget over again.
    if budget.elapsed_s() >= budget.cap_wall_s():
        reasons.append(f"wall_clock >= {int(budget.cap_wall_s())}s")
    return reasons


# v2.0 Bayesian update: the LLM proposes how strongly evidence bears on a
# hypothesis (a likelihood label); the math enforces a consistent posterior from
# the prior, so confidence can't drift arbitrarily.
_LIKELIHOOD_RATIOS = {
    "strong_support": 6.0, "moderate_support": 3.0, "weak_support": 1.5,
    "neutral": 1.0,
    "weak_against": 1 / 1.5, "moderate_against": 1 / 3.0, "strong_against": 1 / 6.0,
}


def bayesian_update(prior: float, likelihood_label: str) -> float:
    """posterior from prior × likelihood ratio, in odds space. Clamped."""
    lr = _LIKELIHOOD_RATIOS.get(likelihood_label, 1.0)
    prior = min(max(prior, 0.01), 0.99)
    odds = prior / (1 - prior) * lr
    posterior = odds / (1 + odds)
    return round(min(max(posterior, 0.01), 0.99), 3)


def _fingerprint(text: str) -> str:
    """Normalised word set, for spotting the same complaint posted twice."""
    words = sorted(set(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split()))
    return " ".join(words)


def normalise_quote(text: str) -> str:
    """Case, punctuation and spacing folded away: the identity of a quote.
    "It works fine, no complaints" and "it works fine — no complaints!" are one
    quote; reordering its words is not (that is the Jaccard check's job)."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


# ── evidence intake ─────────────────────────────────────────────────────

# A happy review is not a complaint. The assessor could cite a 5★ "works
# great, love the new sync" as SUPPORT for "the new sync drains battery", and
# the two-source rule counted it like any other quote. Only these intents —
# from echolens.intent, the same deterministic classifier the Cases screen
# uses — carry a complaint cue a 4–5★ review needs before it can support a
# problem hypothesis.
COMPLAINT_INTENTS = frozenset({"bug", "ux_confusion"})
POSITIVE_RATING_MIN = 4


def positive_without_complaint(text: str | None, rating) -> bool:
    """True for a 4–5★ review with no bug or confusion cue in it. Such a review
    may be COUNTER-evidence for a problem hypothesis, never support for it."""
    from echolens.intent import classify
    if not isinstance(rating, int) or rating < POSITIVE_RATING_MIN:
        return False
    return classify(text, rating) not in COMPLAINT_INTENTS


def two_source_rule(hypothesis: dict, evidence: list[dict],
                    ignore_sources: frozenset[str] = frozenset()) -> bool:
    """`supported` requires >=2 independent evidence items from >=2 distinct
    sources (PRD §5.2). Anything less stays `active` at best.

    `ignore_sources` are left out of the distinct-SOURCE count (the items still
    count as items). A single-channel product passes {"release_notes",
    "github_commits"}: a release note says what shipped, not that users are
    hurting, so on its own it is not a second channel corroborating them.

    "Independent" now means textually distinct as well as differently-sourced.
    A vocal user who files a GitHub issue AND posts the same words as a review
    produced two items from two sources, which satisfied both halves of this
    rule — unlocking `resolved` at >=0.80 confidence on one person saying one
    thing twice. Near-identical text is collapsed here rather than at evidence
    intake, because merging it there would DISCARD the second channel and
    destroy the corroboration signal this rule exists to measure.
    """
    by_id = {e["id"]: e for e in evidence}
    items = [by_id[eid] for eid in hypothesis.get("evidence_for", []) if eid in by_id]
    if len(items) < MIN_INDEPENDENT_EVIDENCE:
        return False

    distinct: list[dict] = []
    seen: list[set[str]] = []
    for e in items:
        words = set(_fingerprint(e.get("snippet", "")).split())
        # Too short to judge, EVEN IF IDENTICAL.
        #
        # The audit flagged this exemption as a hole — two identical four-word
        # posts satisfying the rule. On reflection the original reasoning holds
        # and the finding does not: short complaints are SUPPOSED to collide.
        # "battery dies" on GitHub and on the Play Store is the single most
        # likely way two genuinely different people describe the same fault, and
        # collapsing them would discard exactly the corroboration this rule
        # exists to measure. The real cross-post risk is a distinctive sentence
        # repeated verbatim, which needs enough words to be distinctive — and
        # that case is caught by the Jaccard check below.
        if len(words) < MIN_CROSS_POST_WORDS:
            distinct.append(e)
            continue
        # Jaccard over word sets: the same sentence re-posted scores ~1.0.
        dup = any(
            len(words & prior) / max(1, len(words | prior)) >= CROSS_POST_SIMILARITY
            for prior in seen
        )
        if not dup:
            distinct.append(e)
            seen.append(words)

    if len(distinct) < MIN_INDEPENDENT_EVIDENCE:
        return False
    # Case- and whitespace-insensitive: "github" and "GitHub" are one source,
    # and exact string equality counted them as two independent ones.
    return len({str(e["source"]).strip().lower()
                for e in distinct}
               - set(ignore_sources)) >= MIN_DISTINCT_SOURCES


def resolvable_hypothesis(hypotheses: list[dict], evidence: list[dict],
                          ignore_sources: frozenset[str] = frozenset()) -> dict | None:
    """The hypothesis that satisfies confidence + two-source rule, if any."""
    for h in hypotheses:
        # A parked hypothesis is out of the active set; it cannot resolve the
        # case until the model brings it back.
        if h["status"] in ("rejected", "parked"):
            continue
        if h["confidence"] >= SUPPORT_CONFIDENCE and two_source_rule(h, evidence, ignore_sources):
            return h
    return None


# ── single-channel products ─────────────────────────────────────────────
#
# A small app with only Play Store reviews connected can never meet the
# two-source rule: there is no second channel to corroborate from. Refusing
# every such case outright is honest but useless; granting them "supported" is
# useful but dishonest. The middle is a DIFFERENT, labelled outcome —
# "supported (single channel)" — with a hard confidence cap, reached only by a
# stricter within-channel bar:
#   A. >= 3 textually distinct reviews AND a release note published 0–14 days
#      before at least one of them, or
#   B. >= 5 textually distinct reviews spread over >= 3 different days or
#      >= 3 different versions (not one bad afternoon, not one build).
# Multi-channel products never take this path.

SINGLE_CHANNEL_STATUS = "supported_single_channel"
SINGLE_CHANNEL_LABEL = "Supported (single channel)"
SINGLE_CHANNEL_CONFIDENCE_CAP = 0.75
# Below the full bar (0.80) on purpose — the cap is 0.75 — but still clearly
# better than a coin flip.
SINGLE_CHANNEL_MIN_CONFIDENCE = 0.65
SINGLE_CHANNEL_NON_FEEDBACK = frozenset({"release_notes", "github_commits"})
REVIEW_SOURCES = frozenset({"play_store", "app_store"})
RELEASE_MATCH_DAYS = 14


def _distinct_quotes(items: list[dict]) -> list[dict]:
    """Textually distinct items from ONE channel. Unlike two_source_rule, short
    identical quotes collapse here: within a single source, the same five words
    twice is one data point, not corroboration."""
    out: list[dict] = []
    seen_exact: set[str] = set()
    seen_words: list[set[str]] = []
    for e in items:
        text = e.get("snippet", "")
        exact = normalise_quote(text)
        if not exact or exact in seen_exact:
            continue
        words = set(_fingerprint(text).split())
        if len(words) >= MIN_CROSS_POST_WORDS and any(
                len(words & p) / max(1, len(words | p)) >= CROSS_POST_SIMILARITY
                for p in seen_words):
            continue
        seen_exact.add(exact)
        seen_words.append(words)
        out.append(e)
    return out


def _day(value) -> str | None:
    return str(value)[:10] if value else None


def single_channel_support(hypothesis: dict, evidence: list[dict]) -> str | None:
    """The basis on which `hypothesis` meets the single-channel bar, or None."""
    from datetime import date

    by_id = {e["id"]: e for e in evidence}
    items = [by_id[eid] for eid in hypothesis.get("evidence_for", []) if eid in by_id]
    reviews = _distinct_quotes([e for e in items
                                if str(e.get("source", "")).lower() in REVIEW_SOURCES])
    releases = [e for e in items if str(e.get("source", "")).lower() == "release_notes"]

    def parse(d):
        try:
            return date.fromisoformat(d) if d else None
        except ValueError:
            return None

    review_days = [parse(_day((e.get("meta") or {}).get("date"))) for e in reviews]
    if len(reviews) >= 3:
        for rel in releases:
            shipped = parse(_day((rel.get("meta") or {}).get("released_at")))
            if shipped is None:
                continue
            if any(d is not None and 0 <= (d - shipped).days <= RELEASE_MATCH_DAYS
                   for d in review_days):
                return (f"{len(reviews)} distinct reviews, at least one within "
                        f"{RELEASE_MATCH_DAYS} days after the {shipped.isoformat()} release")
    if len(reviews) >= 5:
        days = {d for d in review_days if d is not None}
        versions = {(e.get("meta") or {}).get("version") for e in reviews} - {None, ""}
        if len(days) >= 3 or len(versions) >= 3:
            spread = (f"{len(days)} different days" if len(days) >= 3
                      else f"{len(versions)} different versions")
            return f"{len(reviews)} distinct reviews across {spread}"
    return None


def single_channel_winner(hypotheses: list[dict], evidence: list[dict]) -> tuple[dict, str] | None:
    """(hypothesis, basis) for the first live hypothesis that clears the
    single-channel bar at >= SINGLE_CHANNEL_MIN_CONFIDENCE."""
    for h in hypotheses:
        if h["status"] in ("rejected", "parked"):
            continue
        if h["confidence"] < SINGLE_CHANNEL_MIN_CONFIDENCE:
            continue
        basis = single_channel_support(h, evidence)
        if basis:
            return h, basis
    return None


def conflicting_evidence(hypotheses: list[dict]) -> bool:
    """Strong conflict: some non-rejected hypothesis has both meaningful
    support and meaningful contradiction (>=2 each) -> a human should look."""
    return any(
        len(h.get("evidence_for", [])) >= 2 and len(h.get("evidence_against", [])) >= 2
        for h in hypotheses
        if h["status"] != "rejected"
    )


def best_confidence(hypotheses: list[dict]) -> float:
    live = [h["confidence"] for h in hypotheses if h["status"] != "rejected"]
    return max(live, default=0.0)


def classify_end_state(hypotheses: list[dict]) -> tuple[str, str]:
    """Outcome when the budget ends the investigation (PRD §5.6)."""
    best = best_confidence(hypotheses)
    if best < INSUFFICIENT_CONFIDENCE:
        return "insufficient_evidence", f"best confidence {best:.2f} < {INSUFFICIENT_CONFIDENCE}"
    return "needs_human", (f"best confidence {best:.2f} at budget end without meeting "
                           f"the two-source rule at ≥ {SUPPORT_CONFIDENCE}")


def unsupported_claims(prose: str, evidence_ids: set[str]) -> list[str]:
    """Claim-grounding scan (Closebrief-guard analog): every causal sentence
    must reference at least one evidence id that actually exists."""
    # Split on newlines as well as sentence punctuation. Prose that uses line
    # breaks without terminal punctuation was treated as ONE sentence, so a
    # single inline citation anywhere in the block grounded every causal claim
    # in it.
    violations = []
    for sentence in re.split(SENTENCE_SPLIT, prose):
        if not sentence.strip() or not CAUSAL_MARKERS.search(sentence):
            continue
        refs = set(EVIDENCE_REF.findall(sentence))
        if not refs or not refs <= evidence_ids:
            violations.append(sentence.strip())
    return violations


WORKING_HYPOTHESIS_LABEL = "Working hypothesis — not yet supported by evidence"
_WHOLE_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def strip_ungrounded(prose: str, evidence_ids: set[str]) -> tuple[str, list[str], bool]:
    """Split a draft into what may be published and what may not.

    Returns (kept prose, removed sentences, kept prose cites real evidence).
    A sentence goes if ANY of its clauses is an uncited causal claim — the scan
    is clause-level, removal is sentence-level, so no half-sentence is left
    behind. One uncited sentence used to block the whole finding, discarding
    every grounded sentence with it; now only the offending ones go, and the
    caller shows them separately, labelled as unproven, never as conclusions.
    """
    kept: list[str] = []
    removed: list[str] = []
    for sentence in _WHOLE_SENTENCE.split(prose or ""):
        s = sentence.strip()
        if not s:
            continue
        (removed if unsupported_claims(s, evidence_ids) else kept).append(s)
    grounded = any(set(EVIDENCE_REF.findall(s)) and set(EVIDENCE_REF.findall(s)) <= evidence_ids
                   for s in kept)
    return " ".join(kept), removed, grounded


# ── user-facing text hygiene ────────────────────────────────────────────
#
# The finding is read by a PM, not by the guard. Two kinds of internal
# vocabulary leaked straight into it: the hypothesis label ("H1 supported:
# release v3.2.0 …" became the case title everywhere) and guard bookkeeping
# ("This satisfies the two-source rule with 0.90 confidence."). Both are
# stripped here, deterministically, after the model drafts.

_HYP_PREFIX = re.compile(
    r"^\s*H\d+\b[\s,]*(?:is\s+)?(?:supported|confirmed|rejected|active|wins?)?\s*[:\-—]\s*",
    re.IGNORECASE)
_META_SENTENCE = re.compile(
    r"two[- ]source rule|claim[- ]grounding|honesty guard|budget (?:cap|guard)|"
    r"\bH\d+\b(?: is)? (?:supported|rejected)|confidence (?:threshold|of) 0?\.\d+",
    re.IGNORECASE)
_CODE_SPAN = re.compile(r"`([^`\n]{1,80})`")


def tidy_summary(summary: str) -> str:
    """'H1 supported: release v3.2.0 introduced…' -> 'Release v3.2.0 introduced…'."""
    text = _HYP_PREFIX.sub("", summary or "").strip()
    return text[:1].upper() + text[1:] if text else (summary or "")


def tidy_prose(prose: str) -> str:
    """Drop sentences that narrate the guards rather than the product."""
    kept = [s for s in re.split(r"(?<=[.!?])\s+", prose or "")
            if s.strip() and not _META_SENTENCE.search(s)]
    return " ".join(kept) if kept else (prose or "")


def unseen_code_spans(text: str, corpus: str) -> str:
    """Un-format `identifiers` that appear nowhere in the evidence.

    A recommendation said to disable `automatic_background_photo_sync` — a flag
    name that exists in no evidence. Rendered as code it reads as a verified
    config key. Spans the evidence does contain are kept; the rest become plain
    words so they read as a description, not a fact."""
    lowered = (corpus or "").lower()

    def repl(m: re.Match) -> str:
        span = m.group(1)
        if span.lower() in lowered:
            return m.group(0)
        return span.replace("_", " ")
    return _CODE_SPAN.sub(repl, text or "")


def dedupe_refs(refs) -> list:
    """Evidence ids in first-seen order, each once ('ev_001, ev_001' bug)."""
    seen: list = []
    for r in refs or []:
        if r not in seen:
            seen.append(r)
    return seen
