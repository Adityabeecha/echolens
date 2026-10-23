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


def two_source_rule(hypothesis: dict, evidence: list[dict]) -> bool:
    """`supported` requires >=2 independent evidence items from >=2 distinct
    sources (PRD §5.2). Anything less stays `active` at best.

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
                for e in distinct}) >= MIN_DISTINCT_SOURCES


def resolvable_hypothesis(hypotheses: list[dict], evidence: list[dict]) -> dict | None:
    """The hypothesis that satisfies confidence + two-source rule, if any."""
    for h in hypotheses:
        # A parked hypothesis is out of the active set; it cannot resolve the
        # case until the model brings it back.
        if h["status"] in ("rejected", "parked"):
            continue
        if h["confidence"] >= SUPPORT_CONFIDENCE and two_source_rule(h, evidence):
            return h
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
