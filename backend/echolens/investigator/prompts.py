"""Prompts + JSON schemas for the investigator's LLM steps.

Prompts explain the rules; the guards in guards.py ENFORCE them.
"""
from __future__ import annotations

import json

from echolens.tools.registry import tool_catalog

PLAN_SYSTEM = """You are the EchoLens investigator: a rigorous, skeptical product-feedback \
detective. You investigate one anomaly by forming competing hypotheses and testing them \
with deterministic data tools. Rules you operate under (enforced in code — violating them \
just wastes budget):
- Max 4 active hypotheses. Always consider at least one alternative/decoy explanation.
- A hypothesis can only be confirmed with >=2 independent evidence items from >=2 distinct \
sources (e.g. reviews + github). Design tool calls to satisfy or break that.
- Every tool call must name which hypothesis it tests.
- Prefer segmentation to settle decoys (e.g. does the complaint rate rise for users NOT on \
the suspect version?).
- Never declare resolution without the two-source rule satisfied at >=0.8 confidence. \
Once one source supports your leading hypothesis, your next move is corroboration in a \
DIFFERENT source type — search github/reddit using the suspected feature's own words \
(e.g. "background sync battery"), not abstract categories.
- Each tool call must be a NEW test — never repeat a query you already ran; the result \
will not change.
- If evidence is genuinely thin, say so and conclude insufficient_evidence — honest \
uncertainty beats a confident guess. If evidence strongly conflicts, conclude needs_human.
- Be economical: you have a hard budget; don't repeat near-identical queries.

Your response MUST include the payload matching your action, or the step is wasted:
- action="call_tool"          -> include "tool": {{"name", "args", "tests_hypothesis"}}
- action="revise_hypotheses"  -> include "hypotheses": the FULL revised list. Set initial
  confidence to prior plausibility (typically 0.3-0.6), never 0.
- action="conclude"           -> include "conclusion": {{"status", "reason"}}

Investigation craft: anchor on the timeline first (get_release_notes around the anomaly
window), search the actual complaint text with likely user words (e.g. "battery", "crash",
"slow" — not abstract words like "bug"), then use review_stats/compare_periods to turn
anecdotes into rates.

Available tools:
{catalog}

Specialists you may `delegate` to for analysis the tools can't do (each is a single expert pass):
- sentiment_analyst: breaks a set of negative reviews into distinct complaint themes and tone.
- timeline_reconstructor: orders scattered dated events and pinpoints when the problem began.
Delegation gives you ANALYSIS, not evidence — hypothesis confidence still only moves on cited evidence.

Example of a good tool step:
{{"thought": "If v3.2 caused this, negative reviews after Jul 8 should name the new feature; testing H1.",
  "action": "call_tool",
  "tool": {{"name": "search_reviews",
           "args": {{"query": "battery drain", "date_from": "2026-07-08", "rating_max": 2}},
           "tests_hypothesis": "H1"}}}}

Respond with JSON only."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "description": "your reasoning for this step, 1-3 sentences"},
        "action": {"type": "string", "enum": ["call_tool", "revise_hypotheses", "delegate", "conclude"]},
        "delegate": {
            "type": "object",
            "description": "when action=delegate: hand a hard sub-analysis to a specialist",
            "properties": {
                "specialist": {"type": "string", "enum": ["sentiment_analyst", "timeline_reconstructor"]},
                "focus": {"type": "string", "description": "the term/theme to analyze"},
                "tests_hypothesis": {"type": "string"},
            },
            "required": ["specialist", "focus"],
        },
        "tool": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "args": {"type": "object"},
                "tests_hypothesis": {"type": "string"},
            },
            "required": ["name", "args", "tests_hypothesis"],
        },
        "hypotheses": {
            "type": "array",
            "description": "full revised hypothesis list when action=revise_hypotheses",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string"},
                    "confidence": {"type": "number"},
                    "status": {"type": "string", "enum": ["active", "supported", "rejected"]},
                    "next_test": {"type": "string"},
                    "boost_if_rejected": {
                        "type": "array", "items": {"type": "string"},
                        "description": "ids of competing hypotheses whose REJECTION should raise "
                                       "this one's confidence (mutually-exclusive explanations)",
                    },
                },
                "required": ["id", "statement", "confidence", "status"],
            },
        },
        "conclusion": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["resolved", "insufficient_evidence", "needs_human"]},
                "reason": {"type": "string"},
                "supported_hypothesis": {"type": "string"},
            },
            "required": ["status", "reason"],
        },
    },
    "required": ["thought", "action"],
}

UPDATE_SYSTEM = """You are the evidence assessor of the EchoLens investigator. A tool just \
returned data. Your job:
1. Extract at most 3 items worth keeping as evidence. Each MUST use a `ref` value copied \
VERBATIM from the tool result (that makes it re-retrievable) and a short verbatim snippet. \
Never paraphrase data into the record. If nothing in the result is evidential, return none.
2. Revise hypothesis confidences. Every change must cite the refs that caused it. \
Move confidence decisively when evidence is strong, including DOWN when a hypothesis is \
contradicted (e.g. a segment that should show the effect doesn't). Cap confidence at 0.9 \
unless the hypothesis is corroborated by two DIFFERENT source types; never use 1.0 — \
certainty is not available in this business.

Respond with JSON only."""

UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "verbatim ref from the tool result"},
                    "snippet": {"type": "string"},
                    "supports": {"type": "array", "items": {"type": "string"}},
                    "contradicts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["ref", "snippet", "supports", "contradicts"],
            },
        },
        "hypothesis_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "likelihood": {
                        "type": "string",
                        "enum": ["strong_support", "moderate_support", "weak_support", "neutral",
                                 "weak_against", "moderate_against", "strong_against"],
                        "description": "how strongly THIS evidence bears on the hypothesis; the "
                                       "posterior confidence is computed from it (preferred)",
                    },
                    "new_confidence": {"type": "number", "description": "optional direct override"},
                    "new_status": {"type": "string", "enum": ["active", "supported", "rejected"]},
                    "based_on_refs": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
                "required": ["id", "based_on_refs", "note"],
            },
        },
    },
    "required": ["evidence", "hypothesis_updates"],
}

FINDING_SYSTEM = """You draft the final finding of an EchoLens investigation. Hard rules:
- Every causal sentence in `prose` MUST cite evidence ids inline like [ev_003]. A \
deterministic scanner rejects findings with uncited causal claims.
- Only cite evidence ids that exist in the state you are given.
- If the outcome is insufficient_evidence or budget_exhausted: make NO causal claims. \
State plainly what was checked and what evidence would settle the question.
- If the outcome is needs_human: describe the conflict or uncertainty precisely.
Respond with JSON only."""

FINDING_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "one-line headline"},
        "prose": {"type": "string", "description": "3-6 sentences; causal claims cite [ev_x] inline"},
        "confidence": {"type": "number"},
        "supported_hypothesis": {"type": ["string", "null"]},
        "checked": {"type": "array", "items": {"type": "string"}},
        "what_would_settle_it": {"type": "string"},
    },
    "required": ["summary", "prose", "confidence", "checked", "what_would_settle_it"],
}


def plan_system(guidance: str = "") -> str:
    base = PLAN_SYSTEM.format(catalog=tool_catalog())
    if guidance.strip():
        base += ("\n\nLEARNED GUIDANCE (from past human reviews of your findings — apply it):\n"
                 + guidance.strip())
    return base


def render_state(trigger: dict, hypotheses: list[dict], evidence: list[dict],
                 budget: dict, recent: list[str]) -> str:
    return (
        f"ANOMALY UNDER INVESTIGATION:\n{json.dumps(trigger, indent=1)}\n\n"
        f"HYPOTHESES:\n{json.dumps(hypotheses, indent=1) if hypotheses else '(none yet — form some)'}\n\n"
        f"EVIDENCE SO FAR:\n{json.dumps(evidence, indent=1) if evidence else '(none yet)'}\n\n"
        f"BUDGET REMAINING:\n{json.dumps(budget)}\n\n"
        f"RECENT STEPS:\n" + ("\n".join(recent[-6:]) if recent else "(first step)")
    )
