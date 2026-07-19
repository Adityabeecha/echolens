"""Conversational layer (v7.0) — ask the accumulated, verified knowledge anything.

RAG over EchoLens's own findings. The grounding rule is unchanged from the rest
of the product: no claim without a retrievable reference. Every answer cites the
case(s) it came from, and "I haven't investigated that yet" is a valid — and
honest — answer. Deterministic retrieval, so a chat answer can never hallucinate
a cause the product didn't actually verify.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Finding, Investigation
from echolens.impact import decision_doc
from echolens.textkit import tokenize

# the user is asking us to go find something out (→ launch an investigation)
INVESTIGATE_MARKERS = (
    "why did", "why are", "why is", "why has", "investigate", "look into",
    "what caused", "what's causing", "whats causing", "dig into", "find out",
)
# the user wants a ranked/aggregate view (→ answer from open problems by impact)
RANK_MARKERS = (
    "biggest", "worst", "top ", "most ", "highest", "what should we fix",
    "what to fix", "prioriti", "unresolved",
)


def _knowledge(session: Session) -> list[tuple[Finding, Investigation]]:
    """Every finding backed by a real cause (resolved case or approved finding)."""
    out = []
    for f in session.scalars(select(Finding)).all():
        inv = session.get(Investigation, f.investigation_id)
        if inv is None:
            continue
        if inv.status == "resolved" or f.status == "approved":
            out.append((f, inv))
    return out


def retrieve(session: Session, message: str, k: int = 4) -> list[tuple[Finding, Investigation]]:
    terms = set(tokenize(message))
    if not terms:
        return []
    scored = []
    for f, inv in _knowledge(session):
        ftoks = set(tokenize(f.summary + " " + (f.json or {}).get("prose", "")))
        overlap = len(terms & ftoks)
        if overlap:
            scored.append((overlap, f, inv))
    scored.sort(key=lambda x: (-x[0], -x[1].id))
    return [(f, inv) for _, f, inv in scored[:k]]


def _open_problems(session: Session) -> list[tuple[Finding, Investigation]]:
    """Resolved cases not yet confirmed-fixed, ranked by impact."""
    from echolens.db.models import FixWatch
    confirmed = {w.investigation_id for w in session.scalars(
        select(FixWatch).where(FixWatch.status == "confirmed")).all()}
    rows = []
    for inv in session.scalars(select(Investigation).where(Investigation.status == "resolved")).all():
        if inv.id in confirmed:
            continue
        f = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if f is not None:
            rows.append((f, inv))
    rows.sort(key=lambda fi: -(fi[0].json or {}).get("impact", {}).get("impact_score", 0.0))
    return rows


def _cite(f: Finding, inv: Investigation) -> dict:
    impact = (f.json or {}).get("impact", {})
    return {"investigation_id": inv.id, "finding_id": f.id, "summary": f.summary,
            "affected_pct": impact.get("affected_pct")}


def route(session: Session, message: str) -> dict:
    """Decide how to answer. Returns one of:
      {"type": "answer", "text", "citations": [...]}
      {"type": "launch", "description": <what to investigate>}
    The endpoint executes a launch (creates the anomaly + investigation)."""
    msg = (message or "").lower().strip()
    if not msg:
        return {"type": "answer", "text": "Ask me about a complaint, a cause, or what to fix next.", "citations": []}

    # 1) ranking / aggregate view → answer from open problems by impact
    if any(m in msg for m in RANK_MARKERS):
        probs = _open_problems(session)
        if not probs:
            return {"type": "answer",
                    "text": "No open problems on record — every resolved case is fixed or in verification.",
                    "citations": []}
        f, inv = probs[0]
        cites = [_cite(f, inv) for f, inv in probs[:3]]
        top = cites[0]
        pct = f" (≈{top['affected_pct']}% of recent negatives)" if top.get("affected_pct") else ""
        return {"type": "answer",
                "text": f"Your biggest unresolved problem is “{top['summary']}”{pct} — case #{top['investigation_id']}. "
                        + (f"{len(cites)-1} more open below." if len(cites) > 1 else ""),
                "citations": cites}

    # 2) explicit ask to investigate something → launch
    if any(m in msg for m in INVESTIGATE_MARKERS):
        return {"type": "launch", "description": message.strip()}

    # 3) topic question → cite matching verified findings
    hits = retrieve(session, message)
    if hits:
        cites = [_cite(f, inv) for f, inv in hits]
        lead = hits[0]
        d = decision_doc(lead[0].json or {}, [], (lead[0].json or {}).get("impact", {}), "resolved")
        return {"type": "answer",
                "text": f"{d['whats_broken']} — case #{lead[1].id}."
                        + (f" (+{len(cites)-1} related)" if len(cites) > 1 else ""),
                "citations": cites}

    # 4) nothing on record — honest, and offer to investigate
    return {"type": "answer",
            "text": "I haven't investigated that yet. Ask me to \"investigate …\" and I'll open a case.",
            "citations": []}


def followup(session: Session, finding: Finding, question: str) -> dict:
    """A targeted finding follow-up (v7.0): e.g. 'does this affect iOS too?'.
    Runs a deterministic cohort tool and appends the result as a finding ADDENDUM
    — no full re-investigation. Cited to the finding."""
    from echolens.impact import theme_terms
    from echolens.tools.compare_cohorts import compare_cohorts

    inv = session.get(Investigation, finding.investigation_id)
    anomaly = None
    if inv is not None:
        from echolens.db.models import AnomalyEvent
        anomaly = session.get(AnomalyEvent, inv.anomaly_id)
    terms = theme_terms(anomaly, finding.json or {})
    query = " ".join(terms[:3]) or finding.summary[:40]
    q = question.lower()
    dimension = "os" if any(w in q for w in ("ios", "android", "os", "device", "platform")) else "version"
    res = compare_cohorts(session, term=query, dimension=dimension)
    top = res.get("highest_cohort")
    ratio = res.get("highest_vs_next_ratio")
    if top and top != "unknown":
        answer = (f"On the {dimension} split, “{query}” concentrates in {top}"
                  + (f" ({ratio}× the next cohort)." if ratio else " (largely exclusive).")
                  + " Other cohorts are comparatively clean.")
    else:
        answer = f"Not enough {dimension}-tagged data to split “{query}” across cohorts."

    fj = dict(finding.json or {})
    addenda = list(fj.get("addenda", []))
    addenda.append({"question": question, "answer": answer, "dimension": dimension})
    fj["addenda"] = addenda
    finding.json = fj
    session.flush()
    return {"question": question, "answer": answer, "investigation_id": finding.investigation_id}
