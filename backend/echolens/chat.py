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
# a direct instruction to open a case now, as opposed to a "why" question,
# which gets a confirm card first (an investigation costs money)
COMMAND_MARKERS = ("investigate", "look into", "dig into", "find out")
# the user wants a ranked/aggregate view (→ answer from open problems by impact)
RANK_MARKERS = (
    "biggest", "worst", "top ", "most ", "highest", "what should we fix",
    "what to fix", "prioriti", "unresolved",
)


def _knowledge(session: Session, product_id: int | None = None) -> list[tuple[Finding, Investigation]]:
    """Every finding in THIS product backed by a real cause."""
    # One join, not one session.get per finding: Ask's statement count grew with
    # the number of cases on record.
    stmt = (select(Finding, Investigation)
            .join(Investigation, Investigation.id == Finding.investigation_id)
            .where((Investigation.status == "resolved") | (Finding.status == "approved"))
            .order_by(Finding.id))
    if product_id is not None:
        stmt = stmt.where(Finding.product_id == product_id)
    return [(f, inv) for f, inv in session.execute(stmt).all()]


def retrieve(session: Session, message: str, k: int = 4,
             product_id: int | None = None) -> list[tuple[Finding, Investigation]]:
    terms = set(tokenize(message))
    if not terms:
        return []
    scored = []
    for f, inv in _knowledge(session, product_id):
        ftoks = set(tokenize(f.summary + " " + (f.json or {}).get("prose", "")))
        overlap = len(terms & ftoks)
        if overlap:
            scored.append((overlap, f, inv))
    scored.sort(key=lambda x: (-x[0], -x[1].id))
    return [(f, inv) for _, f, inv in scored[:k]]


def _open_problems(session: Session, product_id: int | None = None) -> list[tuple[Finding, Investigation]]:
    """Resolved cases not yet confirmed-fixed, ranked by impact (this product)."""
    from echolens.db.models import FixWatch
    fw = select(FixWatch).where(FixWatch.status == "confirmed")
    inv_stmt = select(Investigation).where(Investigation.status == "resolved")
    if product_id is not None:
        fw = fw.where(FixWatch.product_id == product_id)
        inv_stmt = inv_stmt.where(Investigation.product_id == product_id)
    confirmed = {w.investigation_id for w in session.scalars(fw).all()}
    invs = [i for i in session.scalars(inv_stmt).all() if i.id not in confirmed]
    latest: dict[int, Finding] = {}
    if invs:
        for f in session.scalars(select(Finding).where(
                Finding.investigation_id.in_([i.id for i in invs])).order_by(Finding.id)).all():
            latest[f.investigation_id] = f          # ascending: newest wins
    rows = [(latest[i.id], i) for i in invs if i.id in latest]
    rows.sort(key=lambda fi: -(fi[0].json or {}).get("impact", {}).get("impact_score", 0.0))
    return rows


def _cite(f: Finding, inv: Investigation) -> dict:
    impact = (f.json or {}).get("impact", {})
    return {"investigation_id": inv.id, "finding_id": f.id, "summary": f.summary,
            "affected_pct": impact.get("affected_pct")}


# ── provenance: where an answer came from ───────────────────────────────
# Every Ask answer carries a `basis` so the reader can tell a verified cause
# from a keyword count. The kinds, strongest first:
#   investigation — a resolved/approved case backs it (cites case #N)
#   signals       — matches something EchoLens detected but never investigated
#   raw_search    — the agent queried the raw feedback; numbers, not causes
#   none          — nothing on record backs it
RAW_CAUTION = ("Raw feedback search, not an investigation — these are counts and quotes, "
               "not a verified cause.")
SIGNAL_CAUTION = ("Signals are patterns EchoLens detected, not explanations. "
                  "Investigate to find the cause.")
NONE_CAUTION = "Nothing on record backs this — treat it as unverified."


def basis_investigation(case_id: int) -> dict:
    return {"kind": "investigation", "case_id": case_id,
            "label": f"From verified investigation (case #{case_id})", "caution": None}


def basis_raw_search() -> dict:
    return {"kind": "raw_search", "case_id": None,
            "label": "From raw feedback search (not investigated)", "caution": RAW_CAUTION}


def basis_signals() -> dict:
    return {"kind": "signals", "case_id": None,
            "label": "From waiting signals (not investigated)", "caution": SIGNAL_CAUTION}


def basis_none(caution: str | None = None) -> dict:
    return {"kind": "none", "case_id": None, "label": "Not investigated yet",
            "caution": caution}


def basis_for_citations(citations: list[dict] | None) -> dict | None:
    """Investigation basis when the answer cites at least one case."""
    if citations:
        return basis_investigation(int(citations[0]["investigation_id"]))
    return None


def matching_signals(session: Session, message: str, product_id: int | None = None,
                     k: int = 3) -> list[dict]:
    """Waiting (detected, never investigated, not dismissed) signals whose
    headline shares words with the question, best match first."""
    from echolens.detector.incidents import waiting_rows

    terms = set(tokenize(message))
    if not terms:
        return []
    scored = []
    for i, row in enumerate(waiting_rows(session, product_id)):
        toks = set(tokenize(" ".join(row["member_topics"])))
        overlap = len(terms & toks)
        if overlap:
            scored.append((overlap, i, row))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [row for _, _, row in scored[:k]]


def _signals_answer(hits: list[dict], prefix: str = "") -> dict:
    lead = hits[0]
    more = f" (+{len(hits) - 1} other incidents)" if len(hits) > 1 else ""
    # grounded: built from the product's own signals, so the endpoint answers
    # with it directly instead of spending a model call.
    return {"type": "answer", "citations": [], "signals": hits, "basis": basis_signals(),
            "grounded": True,
            "text": f"{prefix}EchoLens noticed “{lead['title']}”{more}, but hasn't "
                    "investigated it — so there's no verified cause yet."}


# the user wants to know what people are SAYING (→ answer from the reviews)
FEEDBACK_MARKERS = (
    "complaining", "complain about", "review", "users say", "people say", "saying",
    "feedback", "users hate", "users want", "asking for", "users like",
)
# Words that make up "what are users complaining about in the store reviews?"
# itself. Anything left over is a topic ("…about tabs"), which goes to search.
_GENERAL_WORDS = {
    "what", "are", "is", "the", "our", "my", "users", "user", "people", "customers", "complaining",
    "complain", "complaint", "complaints", "about", "most", "mostly", "main", "top", "biggest",
    "in", "on", "google", "play", "app", "apple", "store", "stores", "and", "reviews", "review",
    "saying", "say", "said", "feedback", "hate", "want", "like", "asking", "for", "lately",
    "recently", "this", "week", "month", "do", "does", "of", "all", "with", "from",
}


def _not_confirmed_yet(session: Session, product_id: int | None, label: str) -> str:
    """"Nothing investigated" was said even after two cases had run and landed
    as hunches; say what actually happened."""
    stmt = select(Investigation.id)
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    n = len(session.scalars(stmt).all())
    if not n:
        return f"Nothing{label} has been investigated yet, so I can't name a cause."
    return (f"EchoLens has looked into {n} problem{'s' if n != 1 else ''}{label}, but none is "
            "confirmed yet, so I can't name a proven cause.")


def _feedback_answer(session: Session, product_id: int | None, product_name: str | None) -> dict | None:
    """What the reviews themselves say, counted, with one quote per theme. It
    reads the reviews EchoLens collected instead of only its case records, and
    says plainly that this is what people wrote, not a verified cause."""
    from datetime import timedelta
    from sqlalchemy import func
    from echolens.db.models import Review
    from echolens.detector.detect import reference_now
    from echolens.textkit import is_probably_english, top_themes
    from echolens.tools._util import snippet
    days = 90
    since = reference_now(session, product_name) - timedelta(days=days)
    scope = [Review.created_at >= since] + ([Review.product == product_name] if product_name else [])
    # Two bounded queries, whatever the size of the corpus.
    total = session.scalar(select(func.count(Review.id)).where(*scope)) or 0
    rows = session.execute(select(Review.ext_id, Review.rating, Review.text)
                           .where(*scope, Review.rating <= 2)
                           .order_by(Review.created_at.desc()).limit(2000)).all()
    negatives = [r for r in rows if is_probably_english(r.text)]
    themes = [t for t in top_themes([r.text or "" for r in negatives], k=6) if t.get("count", 0) >= 2][:3]
    if not themes:
        return None
    snap = {"window_days": days, "negatives": len(rows), "reviews": total}
    parts, quotes = [], []
    for t in themes:
        words = t["label"].lower().split()
        quote = next((r for r in negatives if all(w in (r.text or "").lower() for w in words)), None)
        parts.append(f"“{t['label']}” ({t['count']} reviews)")
        if quote is not None:
            quotes.append({"theme": t["label"], "ref": quote.ext_id, "rating": quote.rating,
                           "text": snippet(quote.text or "", 180)})
    lead = quotes[0] if quotes else None
    return {"type": "answer", "citations": [], "grounded": True, "basis": basis_raw_search(),
            "quotes": quotes,
            "text": (f"In the last {snap['window_days']} days, {snap['negatives']} of {snap['reviews']} reviews"
                     f"{' for ' + product_name if product_name else ''} were 1–2★. The most common complaints: "
                     + ", ".join(parts) + "."
                     + (f" One reviewer: “{lead['text']}”" if lead else "")
                     + " This is what people wrote, not a verified cause — ask me to investigate one to find out why.")}


def route(session: Session, message: str, product_id: int | None = None,
          product_name: str | None = None) -> dict:
    """Decide how to answer, using ONLY the active product's cases. Returns:
      {"type": "answer", "text", "citations": [...], "basis": {...}}
      {"type": "launch", "description": <what to investigate>}
    The endpoint executes a launch (creates the anomaly + investigation)."""
    msg = (message or "").lower().strip()
    label = f" for {product_name}" if product_name else ""
    if not msg:
        return {"type": "answer", "text": "Ask me about a complaint, a cause, or what to fix next.",
                "citations": [], "basis": basis_none()}

    # "What are users complaining about most?" is a question about the reviews,
    # not about cases. The "most" sent it down the ranking path, which answered
    # from GitHub spike titles while 364 store reviews sat unread.
    if (any(m in msg for m in FEEDBACK_MARKERS) and not any(m in msg for m in INVESTIGATE_MARKERS)
            and not set(tokenize(msg)) - _GENERAL_WORDS):
        said = _feedback_answer(session, product_id, product_name)
        if said is not None:
            return said

    # A ranking question with nothing investigated yet used to fall through to
    # "No investigations yet" — or, via the ask agent, five model calls and
    # "I couldn't work that out" — while the product had strong signals
    # waiting. Answer from the signals instead, labelled as uninvestigated.
    if any(m in msg for m in RANK_MARKERS) and not _open_problems(session, product_id):
        from echolens.detector.incidents import waiting_rows
        waiting = waiting_rows(session, product_id)
        signals = waiting[:3]
        if signals:
            top = signals[0]
            rest = " and ".join(f"“{a['title']}”" for a in signals[1:3])
            n = len(waiting)
            return {"type": "answer", "citations": [], "grounded": True,
                    "basis": basis_signals(), "signals": signals, "signal_count": n,
                    "text": (_not_confirmed_yet(session, product_id, label) + " "
                             f"There {'is' if n == 1 else 'are'} {n} incident{'s' if n != 1 else ''} waiting. "
                             f"The strongest incident is “{top['title']}”"
                             + (f", followed by {rest}" if rest else "") +
                             ". Investigate it to find the cause.")}

    # nothing investigated yet in this product — say so explicitly, but still
    # surface a detected signal on the topic if there is one
    if not _knowledge(session, product_id) and not any(m in msg for m in INVESTIGATE_MARKERS):
        sig = matching_signals(session, message, product_id)
        if sig:
            return _signals_answer(sig, prefix=f"No investigations{label} yet. ")
        return {"type": "answer", "citations": [], "basis": basis_none(),
                "text": f"No investigations{label} yet. Ask me to \"investigate …\" and I'll open the first case."}

    # 1) ranking / aggregate view → answer from open problems by impact
    if any(m in msg for m in RANK_MARKERS):
        probs = _open_problems(session, product_id)
        if not probs:
            return {"type": "answer",
                    "text": f"No open problems{label} — every resolved case is fixed or in verification.",
                    "citations": [],
                    "basis": {"kind": "investigation", "case_id": None,
                              "label": "From your case records", "caution": None}}
        f, inv = probs[0]
        cites = [_cite(f, inv) for f, inv in probs[:3]]
        top = cites[0]
        pct = f" (≈{top['affected_pct']}% of recent negatives)" if top.get("affected_pct") else ""
        return {"type": "answer",
                "text": f"Your biggest unresolved problem is “{top['summary']}”{pct} — case #{top['investigation_id']}. "
                        + (f"{len(cites)-1} more open below." if len(cites) > 1 else ""),
                "citations": cites, "basis": basis_investigation(top["investigation_id"])}

    # 2) explicit ask to investigate something → launch
    if any(m in msg for m in INVESTIGATE_MARKERS):
        return {"type": "launch", "description": message.strip()}

    # 3) topic question → cite matching verified findings
    hits = retrieve(session, message, product_id=product_id)
    if hits:
        cites = [_cite(f, inv) for f, inv in hits]
        lead = hits[0]
        d = decision_doc(lead[0].json or {}, [], (lead[0].json or {}).get("impact", {}), "resolved")
        # decision_doc reads json["summary"], which is schema-required but absent
        # on a finding whose JSON was never written or arrived malformed. That
        # produced the subject-less answer " — case #1.", so fall back to the
        # Finding.summary COLUMN, which is populated from the same value.
        headline = (d["whats_broken"] or "").strip() or (lead[0].summary or "").strip()
        stem = f"{headline} — case #{lead[1].id}." if headline else f"See case #{lead[1].id}."
        return {"type": "answer",
                "text": stem + (f" (+{len(cites)-1} related)" if len(cites) > 1 else ""),
                "citations": cites, "basis": basis_investigation(lead[1].id)}

    # 4) not investigated, but EchoLens may have noticed it
    sig = matching_signals(session, message, product_id)
    if sig:
        return _signals_answer(sig)

    # 5) nothing on record — honest, and offer to investigate
    return {"type": "answer", "basis": basis_none(),
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
    if inv is not None and inv.anomaly_id is not None:
        from echolens.db.models import AnomalyEvent
        anomaly = session.get(AnomalyEvent, inv.anomaly_id)
    terms = theme_terms(anomaly, finding.json or {})
    query = " ".join(terms[:3]) or finding.summary[:40]
    q = question.lower()
    dimension = "os" if any(w in q for w in ("ios", "android", "os", "device", "platform")) else "version"
    # Scoped to the finding's own product. Unscoped, this compared cohorts across
    # EVERY product and then wrote the result into this finding's addenda as a
    # permanent, citation-less claim ("concentrates in 3.2") about a version
    # string that might belong to a different app entirely.
    product_name = None
    if inv is not None and inv.product_id is not None:
        from echolens.db.models import Product
        prod = session.get(Product, inv.product_id)
        product_name = prod.name if prod else None
    res = compare_cohorts(session, term=query, dimension=dimension, product=product_name)
    top = res.get("highest_cohort")
    ratio = res.get("highest_vs_next_ratio")
    cohorts = res.get("cohorts") or []
    has_matches = any(c["term_share_of_negatives_pct"] > 0 for c in cohorts)
    if top and top != "unknown":
        if not has_matches:
            answer = f"No matching negative reviews for “{query}” in the available {dimension} cohorts."
        elif res.get("only_in_top_cohort"):
            answer = f"Matching complaints for “{query}” appear only in {top} among the observed {dimension} cohorts."
        elif ratio is not None and ratio > 1:
            answer = f"On the {dimension} split, “{query}” concentrates in {top} ({ratio}× the next cohort)."
        else:
            answer = (f"Matching complaints for “{query}” are present in {top}, but the available "
                      f"{dimension} data does not establish a higher complaint rate than other cohorts.")
    else:
        answer = f"Not enough {dimension}-tagged data to split “{query}” across cohorts."

    fj = dict(finding.json or {})
    addenda = list(fj.get("addenda", []))
    addenda.append({"question": question, "answer": answer, "dimension": dimension})
    fj["addenda"] = addenda
    finding.json = fj
    session.flush()
    return {"question": question, "answer": answer, "investigation_id": finding.investigation_id}
