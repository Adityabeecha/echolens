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

from echolens.db.models import AnomalyEvent, Finding, Investigation
from echolens.tools._util import terms_of


def _overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


def digest_for(session: Session, anomaly: AnomalyEvent, exclude_investigation_id: int | None = None,
               limit: int = 3) -> list[dict]:
    """Past confirmed findings related to this anomaly, most-relevant first."""
    signal = set(terms_of(f"{anomaly.metric} {anomaly.description}"))
    if not signal:
        return []

    rows = session.scalars(
        select(Finding).join(Investigation, Finding.investigation_id == Investigation.id)
        .where(Investigation.status == "resolved")
    ).all()

    scored = []
    for f in rows:
        if exclude_investigation_id and f.investigation_id == exclude_investigation_id:
            continue
        if not f.json.get("supported_hypothesis"):
            continue
        cause_terms = set(terms_of(f.summary))
        score = _overlap(signal, cause_terms)
        if score > 0:
            scored.append((score, f))

    scored.sort(key=lambda sf: (-sf[0], -sf[1].id))
    out = []
    for _score, f in scored[:limit]:
        inv = session.get(Investigation, f.investigation_id)
        out.append({
            "case": f"#{f.investigation_id}",
            "confirmed_cause": f.summary,
            "confidence": round(f.confidence, 2),
            "resolved_at": inv.resolved_at.date().isoformat() if inv and inv.resolved_at else None,
        })
    return out


def digest_text(session: Session, anomaly: AnomalyEvent, exclude_investigation_id: int | None = None) -> str | None:
    items = digest_for(session, anomaly, exclude_investigation_id)
    if not items:
        return None
    lines = [
        f"- {d['case']} (resolved {d['resolved_at']}, confidence {d['confidence']}): {d['confirmed_cause']}"
        for d in items
    ]
    return (
        "You have investigated related signals before. Check whether this anomaly is the SAME "
        "known cause (if so, say so and corroborate) or genuinely NEW:\n" + "\n".join(lines)
    )
