"""Cross-investigation memory (v2.0): the agent remembers what it already proved.

When a new investigation starts, it gets a short digest of past confirmed
findings whose theme overlaps this anomaly — so it can check whether a fresh
spike is the same known cause or a genuinely new one, instead of re-deriving
everything from scratch. Deterministic (no LLM): ranks prior findings by term
overlap with the anomaly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Finding, HypothesisRow, Investigation
from echolens.tools._util import terms_of


def _overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


def digest_for(session: Session, anomaly: AnomalyEvent, exclude_investigation_id: int | None = None,
               limit: int = 3) -> list[dict]:
    """Related product findings and human corrections, with their support kept explicit."""
    signal = set(terms_of(f"{anomaly.metric} {anomaly.description}"))
    if not signal:
        return []

    rows = session.scalars(
        select(Finding).join(Investigation, Finding.investigation_id == Investigation.id)
        .where(Investigation.status == "resolved", Investigation.product_id == anomaly.product_id,
               Finding.status != "challenged")
    ).all()

    scored = []
    for f in rows:
        if exclude_investigation_id and f.investigation_id == exclude_investigation_id:
            continue
        if not f.json.get("supported_hypothesis") or f.json.get("needs_review"):
            continue
        cause_terms = set(terms_of(f.summary))
        score = _overlap(signal, cause_terms)
        if score > 0:
            scored.append((score, f))

    out = []
    scored.sort(key=lambda item: (-item[0], -item[1].id))
    for score, f in scored[:limit]:
        inv = session.get(Investigation, f.investigation_id)
        hyp = session.scalars(select(HypothesisRow).where(
            HypothesisRow.investigation_id == f.investigation_id,
            HypothesisRow.hid == f.json["supported_hypothesis"])).first()
        single = (f.json.get("support_level") == "single_channel"
                  or f.json.get("status") == "supported_single_channel"
                  or (hyp is not None and hyp.status == "supported_single_channel"))
        out.append((score, f.id, {
            "case": f"#{f.investigation_id}",
            "confirmed_cause": f.summary,
            "confidence": round(f.confidence, 2),
            "resolved_at": inv.resolved_at.date().isoformat() if inv and inv.resolved_at else None,
            "source": "finding", "support": "single_channel" if single else "supported",
        }))
    from echolens.brain import human_cause_priors
    for prior in human_cause_priors(session, anomaly.product_id):
        if prior["case_id"] == exclude_investigation_id:
            continue
        score = _overlap(signal, set(terms_of(prior["theme"])))
        if score:
            out.append((score, prior["case_id"], {
                "case": f"#{prior['case_id']}", "confirmed_cause": prior["cause"],
                "confidence": None, "resolved_at": None,
                "source": "human_provided", "support": "human_provided",
            }))
    out.sort(key=lambda item: (-item[0], -item[1]))
    return [item[2] for item in out[:limit]]


def digest_text(session: Session, anomaly: AnomalyEvent, exclude_investigation_id: int | None = None) -> str | None:
    items = digest_for(session, anomaly, exclude_investigation_id)
    if not items:
        return None
    lines = []
    for d in items:
        label = ("human-provided cause, not evidence" if d["source"] == "human_provided" else
                 "single-channel finding; needs independent corroboration" if d["support"] == "single_channel"
                 else "supported finding")
        lines.append(f"- {d['case']} ({label}): {d['confirmed_cause']}")
    return (
        "You have investigated related signals before. Check whether this anomaly is the SAME "
        "known cause (if so, say so and corroborate) or genuinely NEW. Human-provided "
        "causes are priors to test, not evidence or confirmed conclusions:\n" + "\n".join(lines)
    )
