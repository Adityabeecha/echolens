"""Deterministic honesty + budget guards (PRD §5.6–5.7, §14).

These run in code, never in prompts. The agent cannot talk its way past them.
"""
from __future__ import annotations

import re

from echolens.config import (
    INSUFFICIENT_CONFIDENCE,
    MIN_DISTINCT_SOURCES,
    MIN_INDEPENDENT_EVIDENCE,
    SUPPORT_CONFIDENCE,
)
from echolens.investigator.state import Budget

CAUSAL_MARKERS = re.compile(
    r"\b(caus(?:e|es|ed|ing)|driv(?:es|en|ing)|because|due to|led to|leads to|"
    r"result(?:s|ed)? (?:in|from)|root cause|responsible for|triggered)\b",
    re.IGNORECASE,
)
EVIDENCE_REF = re.compile(r"\bev_\d+\b")


def budget_exceeded(budget: Budget) -> list[str]:
    """Return the list of exhausted limits (empty = within budget). Caps are
    scaled by the one-time extension factor (v2.0)."""
    t = budget.tier
    f = budget.extension_factor
    reasons = []
    if budget.iterations >= t.max_iterations * f:
        reasons.append(f"iterations {budget.iterations}/{int(t.max_iterations * f)}")
    if budget.tool_calls >= t.max_tool_calls * f:
        reasons.append(f"tool_calls {budget.tool_calls}/{int(t.max_tool_calls * f)}")
    if budget.tokens >= t.max_tokens * f:
        reasons.append(f"tokens {budget.tokens}/{int(t.max_tokens * f)}")
    if budget.cost_usd >= t.max_cost_usd * f:
        reasons.append(f"cost ${budget.cost_usd:.2f}/${t.max_cost_usd * f:.2f}")
    # elapsed includes wall-clock spent before a restart (restored from checkpoint),
    # so a resumed investigation can't get its full time budget over again.
    if budget.elapsed_s() >= t.max_wall_clock_s * f:
        reasons.append(f"wall_clock >= {int(t.max_wall_clock_s * f)}s")
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


def two_source_rule(hypothesis: dict, evidence: list[dict]) -> bool:
    """`supported` requires >=2 independent evidence items from >=2 distinct
    sources (PRD §5.2). Anything less stays `active` at best."""
    by_id = {e["id"]: e for e in evidence}
    items = [by_id[eid] for eid in hypothesis.get("evidence_for", []) if eid in by_id]
    if len(items) < MIN_INDEPENDENT_EVIDENCE:
        return False
    return len({e["source"] for e in items}) >= MIN_DISTINCT_SOURCES


def resolvable_hypothesis(hypotheses: list[dict], evidence: list[dict]) -> dict | None:
    """The hypothesis that satisfies confidence + two-source rule, if any."""
    for h in hypotheses:
        if h["status"] == "rejected":
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
    violations = []
    for sentence in re.split(r"(?<=[.!?])\s+", prose):
        if not sentence.strip() or not CAUSAL_MARKERS.search(sentence):
            continue
        refs = set(EVIDENCE_REF.findall(sentence))
        if not refs or not refs <= evidence_ids:
            violations.append(sentence.strip())
    return violations
