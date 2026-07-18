"""Recommender agent (PRD §4.1): one LLM pass over a resolved finding →
2–4 ranked actions with effort/impact guesses. No tool loop — pure drafting.

This is a single-pass agent, not a loop, because the judgment ("given this
root cause, what should we do") needs an LLM but not runtime tool selection.
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from echolens.db.models import EvidenceRow, Finding, HypothesisRow, Recommendation
from echolens.llm.client import LLMClient, LLMFormatError

RECOMMEND_SYSTEM = """You turn a confirmed product-feedback root cause into an action plan. \
Produce 2–4 concrete, ranked engineering/product actions. Each action:
- is specific enough to file as a ticket (name the feature, flag, or component),
- has an impact guess (HIGH/MED/LOW) and an effort guess (LOW/MED/HIGH),
- is ordered rank 1..N with rank 1 = best impact-to-effort ratio (usually a fast mitigation \
before a deeper fix).
Ground the plan in the finding's evidence; do not invent mechanisms the evidence doesn't support.
Respond with JSON only."""

RECOMMEND_SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "action": {"type": "string"},
                    "rationale": {"type": "string"},
                    "impact": {"type": "string", "enum": ["HIGH", "MED", "LOW"]},
                    "effort": {"type": "string", "enum": ["LOW", "MED", "HIGH"]},
                },
                "required": ["rank", "action", "impact", "effort"],
            },
        }
    },
    "required": ["actions"],
}


def recommend(session: Session, finding: Finding, llm: LLMClient | None = None) -> list[Recommendation]:
    """Draft and persist ranked actions for a finding. Only resolved findings
    get an action plan; for anything else, drafting a fix would be premature."""
    if finding.json.get("supported_hypothesis") is None:
        return []  # no confirmed cause → nothing to act on yet (honesty over hustle)

    if llm is None:
        from echolens.llm.openai_client import OpenAIClient
        llm = OpenAIClient(on_call=lambda *a: None)

    hyps = session.query(HypothesisRow).filter_by(investigation_id=finding.investigation_id).all()
    evs = session.query(EvidenceRow).filter_by(investigation_id=finding.investigation_id).all()
    prompt = (
        f"FINDING:\n{json.dumps(finding.json, indent=1)}\n\n"
        f"SUPPORTED HYPOTHESES:\n" + json.dumps([
            {"id": h.hid, "statement": h.statement, "confidence": h.confidence}
            for h in hyps if h.status == "supported"
        ], indent=1) + "\n\nEVIDENCE:\n" + json.dumps([
            {"id": e.eid, "source": e.source, "snippet": e.snippet} for e in evs
        ], indent=1)
    )
    try:
        res = llm.complete_json(RECOMMEND_SYSTEM, prompt, RECOMMEND_SCHEMA, "recommender")
        actions = res.parsed.get("actions", [])
    except LLMFormatError:
        return []

    out: list[Recommendation] = []
    for a in sorted(actions, key=lambda x: x.get("rank", 99))[:4]:
        rec = Recommendation(
            finding_id=finding.id, action=a.get("action", ""),
            rationale=a.get("rationale", ""), effort=a.get("effort", "MED"),
            impact=a.get("impact", "MED"), rank=int(a.get("rank", len(out) + 1)),
        )
        session.add(rec)
        out.append(rec)
    session.flush()
    return out
