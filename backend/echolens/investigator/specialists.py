"""Specialist sub-agents (v2.0). Single-pass LLMs the investigator delegates to
when a hypothesis needs analysis the basic search tools can't do.

Each specialist is ONE LLM call with its own prompt + output schema — not a
loop. It produces *analysis* (sentiment breakdown, a reconstructed timeline),
never new evidence: hypothesis confidence still only moves on cited evidence via
the normal update node, so the honesty guards stay intact. The specialist's job
is to sharpen the investigator's thinking about evidence it already has.
"""
from __future__ import annotations

from echolens.llm.client import LLMClient, LLMFormatError

SENTIMENT_SYSTEM = """You are the Sentiment Analyst specialist on a product-feedback investigation. \
Given a set of negative reviews, break down the emotional tone and WHAT users are actually angry \
about — separate distinct complaint themes, note their relative weight, and flag the sharpest \
quotes. Be concrete and quantitative where you can. Respond with JSON only."""

SENTIMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "dominant_theme": {"type": "string"},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "share": {"type": "string", "description": "rough % or 'most'/'some'/'few'"},
                    "tone": {"type": "string"},
                },
                "required": ["theme", "tone"],
            },
        },
        "sharpest_quote": {"type": "string"},
        "takeaway": {"type": "string", "description": "one line for the investigator"},
    },
    "required": ["dominant_theme", "themes", "takeaway"],
}

TIMELINE_SYSTEM = """You are the Timeline Reconstructor specialist. Given scattered dated events \
(releases, issue reports, complaint-rate changes), build a precise ordered timeline and identify \
the inflection point — the moment the problem began — and what immediately preceded it. Respond \
with JSON only."""

TIMELINE_SCHEMA = {
    "type": "object",
    "properties": {
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"date": {"type": "string"}, "event": {"type": "string"}},
                "required": ["date", "event"],
            },
        },
        "inflection_date": {"type": "string"},
        "immediately_before": {"type": "string", "description": "the event just before the inflection"},
        "takeaway": {"type": "string"},
    },
    "required": ["timeline", "inflection_date", "takeaway"],
}

SPECIALISTS = {
    "sentiment_analyst": (SENTIMENT_SYSTEM, SENTIMENT_SCHEMA),
    "timeline_reconstructor": (TIMELINE_SYSTEM, TIMELINE_SCHEMA),
}


def run_specialist(llm: LLMClient, name: str, context: str) -> dict | None:
    """One LLM call. Returns the specialist's structured analysis, or None on failure."""
    spec = SPECIALISTS.get(name)
    if spec is None:
        return None
    system, schema = spec
    try:
        res = llm.complete_json(system, context, schema, f"specialist.{name}")
    except LLMFormatError:
        return None
    return res.parsed
