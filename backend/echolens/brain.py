"""The product-knowledge brain — a learned causal model of how THIS product breaks.

Every version so far reacted to a live problem. After hundreds of verified
investigations the system holds something no single report contains: a map of
which subsystems, when touched, tend to produce which symptoms. This module
turns that latent knowledge into three things:

* **Edges** — "changes to <subsystem> cause <symptom>", each with a confidence
  earned from confirmed fixes, not asserted.
* **Design-doc review** — match a spec or PR description against the edges and
  flag the risks BEFORE the change ships. Prevention, not detection.
* **The oracle** — a new PM asks "what goes wrong with releases here?" and gets
  the product's own history, every claim cited to a real past case.

The honesty rule that governs the whole system applies hardest here, because a
brain is exactly the thing that drifts into confident folklore: an edge that
keeps being predicted and keeps NOT holding decays and retires itself. Knowledge
that stops predicting is knowledge the brain gives up.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, Finding, FixWatch, Investigation, KnowledgeEdge)
from echolens.impact import theme_terms
from echolens.logging import get_logger
from echolens.textkit import tokenize
from echolens.timeutil import aware_utc

log = get_logger("brain")

# The subsystems a change can touch. Each maps to the vocabulary that signals it,
# on either the change side (a PR description) or the symptom side (a finding).
SUBSYSTEMS: dict[str, set[str]] = {
    "sync": {"sync", "syncing", "synced", "wakelock", "background", "upload",
             "download", "replication", "offline", "cloud"},
    "onboarding": {"onboarding", "signup", "sign", "register", "registration",
                   "welcome", "tutorial", "setup", "first", "activation"},
    "auth": {"login", "logout", "auth", "authentication", "password", "token",
             "session", "oauth", "sso", "2fa", "otp"},
    "payments": {"payment", "billing", "checkout", "purchase", "subscription",
                 "refund", "card", "invoice", "price", "paywall"},
    "notifications": {"notification", "notifications", "push", "alert", "fcm",
                      "reminder", "badge"},
    "media": {"photo", "image", "video", "camera", "upload", "thumbnail",
              "gallery", "export", "import", "heic", "codec"},
    "search": {"search", "index", "query", "filter", "sort", "results", "ranking"},
    "ui": {"ui", "layout", "redesign", "theme", "dark", "button", "screen",
           "navigation", "menu", "font"},
    "performance": {"performance", "cache", "memory", "startup", "boot", "lazy",
                    "optimize", "render", "thread"},
    "data": {"database", "migration", "schema", "storage", "backup", "restore",
             "encryption", "export"},
}

# Symptoms a subsystem change tends to manifest as, user-side.
SYMPTOMS: dict[str, set[str]] = {
    "battery-drain": {"battery", "drain", "draining", "power", "overheat", "hot", "charge"},
    "crashes": {"crash", "crashes", "crashing", "freeze", "hang", "force", "close", "anr"},
    "churn": {"uninstall", "uninstalling", "leaving", "switching", "deleted",
              "cancel", "quit", "gave", "done"},
    "data-loss": {"lost", "loss", "missing", "disappeared", "gone", "deleted", "wiped"},
    "slowness": {"slow", "lag", "laggy", "sluggish", "loading", "delay", "stuck"},
    "confusion": {"confusing", "confused", "cluttered", "unclear", "complicated",
                  "hard", "difficult", "understand"},
    "billing-anger": {"charged", "overcharged", "refund", "scam", "expensive",
                      "money", "stolen"},
    "spam": {"spam", "intrusive", "annoying", "ads", "advert", "constant"},
}

# Self-calibration constants.
NEW_EDGE_CONFIDENCE = 0.5     # a single confirmed fix is a hypothesis, not a law
MATCH_PREDICT_DAYS = 45       # how long after a subsystem signal a symptom counts as "predicted"
RETIRE_CONFIDENCE = 0.25      # below this an edge is folklore — retire it
RETIRE_MIN_TRIALS = 3         # ...but only once it's actually been tested


def _classify(text: str, vocab: dict[str, set[str]]) -> list[str]:
    """Every category whose vocabulary the text touches, most-hit first."""
    toks = set(tokenize(text or ""))
    hits = [(name, len(toks & words)) for name, words in vocab.items()]
    return [name for name, n in sorted(hits, key=lambda x: -x[1]) if n > 0]


def _confidence(supports: int, refutes: int) -> float:
    """Beta-style posterior mean: (s + 1) / (s + r + 2). Starts at 0.5 for a
    single support, rises with corroboration, falls when predictions miss —
    and can never reach 1.0, because certainty is not something evidence buys."""
    return round((supports + 1) / (supports + refutes + 2), 3)


# ── mining: build edges from confirmed findings ─────────────────────────


def rebuild(session: Session, product_id: int | None = None) -> dict:
    """(Re)derive the edge set for a product from its confirmed fixes.

    Each confirmed FixWatch is one instance of 'a problem in <subsystem>
    manifested as <symptom>, and fixing it worked'. Instances of the same edge
    accumulate support; the calibration counters that self-play has earned are
    preserved across a rebuild so learning is not thrown away.
    """
    stmt = select(FixWatch).where(FixWatch.status == "confirmed")
    if product_id is not None:
        stmt = stmt.where(FixWatch.product_id == product_id)

    # preserve prediction outcomes (refutes / extra supports) across rebuilds
    prior = {(e.subsystem, e.symptom): e for e in session.scalars(
        select(KnowledgeEdge).where(KnowledgeEdge.product_id == product_id)).all()}
    for e in prior.values():
        e.verified_count = 0
        e.case_ids = []
        e._mined = 0  # type: ignore[attr-defined]

    seen: dict[tuple, KnowledgeEdge] = {}
    for w in session.scalars(stmt).all():
        finding = session.get(Finding, w.finding_id)
        inv = session.get(Investigation, w.investigation_id)
        anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
        text = " ".join(filter(None, [
            finding.summary if finding else "", (finding.json or {}).get("prose", "") if finding else "",
            anomaly.description if anomaly else "", " ".join(w.terms or [])]))

        subs = _classify(text, SUBSYSTEMS)
        syms = _classify(text, SYMPTOMS)
        if not subs or not syms:
            continue
        sub, sym = subs[0], syms[0]     # the strongest signal on each side
        key = (sub, sym)
        edge = prior.get(key) or seen.get(key)
        if edge is None:
            edge = KnowledgeEdge(product_id=product_id, subsystem=sub, symptom=sym,
                                 supports=0, refutes=0, verified_count=0,
                                 case_ids=[], terms=[])
            session.add(edge)
            edge._mined = 0  # type: ignore[attr-defined]
        seen[key] = edge
        prior.setdefault(key, edge)
        edge._mined = getattr(edge, "_mined", 0) + 1  # type: ignore[attr-defined]
        edge.verified_count += 1
        edge.case_ids = list(dict.fromkeys((edge.case_ids or []) + [w.investigation_id]))
        edge.terms = list(dict.fromkeys((edge.terms or []) + (w.terms or [])))[:8]
        edge.last_seen = aware_utc(w.confirmed_at) or edge.last_seen

    session.flush()
    # Support = the mined instances, at minimum the calibration floor of 1 so a
    # brand-new edge reads at NEW_EDGE_CONFIDENCE rather than below it.
    active = 0
    for edge in prior.values():
        mined = getattr(edge, "_mined", 0)
        edge.supports = max(edge.supports, mined)
        if edge.verified_count == 0 and mined == 0 and edge.supports <= edge.refutes:
            edge.status = "retired"      # nothing supports it any more
        _recalibrate(edge)
        if edge.status == "active":
            active += 1
    session.flush()
    return {"edges": active, "product_id": product_id}


def _recalibrate(edge: KnowledgeEdge) -> None:
    trials = edge.supports + edge.refutes
    conf = _confidence(edge.supports, edge.refutes)
    # Retirement wins over provenance: an edge that keeps missing must retire
    # even though it was once mined from confirmed fixes. A brain that can't
    # give up a belief isn't knowledge, it's folklore.
    if trials >= RETIRE_MIN_TRIALS and conf <= RETIRE_CONFIDENCE:
        edge.status = "retired"
    elif edge.verified_count > 0 or edge.supports > edge.refutes:
        edge.status = "active"


# ── self-calibration: did a prediction hold? ────────────────────────────


def record_outcome(session: Session, subsystem: str, symptom: str,
                   held: bool, product_id: int | None = None) -> KnowledgeEdge | None:
    """Feed one prediction outcome back into the brain.

    `held=True` when a problem in the subsystem did show the symptom (the edge
    predicted correctly); `held=False` when it did not. This is the mechanism
    that keeps the brain honest — an edge that keeps missing decays past the
    retirement line on its own.
    """
    edge = session.scalars(select(KnowledgeEdge).where(
        KnowledgeEdge.product_id == product_id,
        KnowledgeEdge.subsystem == subsystem,
        KnowledgeEdge.symptom == symptom)).first()
    if edge is None:
        return None
    if held:
        edge.supports += 1
        edge.last_seen = datetime.now(timezone.utc)
    else:
        edge.refutes += 1
    _recalibrate(edge)
    session.flush()
    return edge


def calibrate_from_history(session: Session, product_id: int | None = None,
                           as_of: datetime | None = None) -> dict:
    """Replay every resolved case as a test of the edges.

    A case whose subsystem matches an edge and whose symptom also matches is a
    HIT for that edge; a subsystem match with a different symptom is a MISS.
    This is how the brain grades itself against reality rather than against the
    fixes that happened to be confirmed.
    """
    now = as_of or datetime.now(timezone.utc)
    edges = {(e.subsystem, e.symptom): e for e in session.scalars(
        select(KnowledgeEdge).where(KnowledgeEdge.product_id == product_id)).all()}
    if not edges:
        return {"tested": 0, "hits": 0, "misses": 0}

    inv_stmt = select(Investigation).where(Investigation.status == "resolved")
    if product_id is not None:
        inv_stmt = inv_stmt.where(Investigation.product_id == product_id)

    hits = misses = tested = 0
    subsystems_seen = {sub for sub, _ in edges}
    for inv in session.scalars(inv_stmt).all():
        finding = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if finding is None:
            continue
        anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv.anomaly_id else None
        text = " ".join(filter(None, [finding.summary, (finding.json or {}).get("prose", ""),
                                      anomaly.description if anomaly else ""]))
        subs = set(_classify(text, SUBSYSTEMS))
        syms = set(_classify(text, SYMPTOMS))
        for (sub, sym), edge in edges.items():
            if sub not in subs or sub not in subsystems_seen:
                continue
            # only cases NOT already baked into the edge count as fresh trials
            if inv.id in (edge.case_ids or []):
                continue
            tested += 1
            if sym in syms:
                edge.supports += 1
                hits += 1
            else:
                edge.refutes += 1
                misses += 1
    for edge in edges.values():
        _recalibrate(edge)
    session.flush()
    return {"tested": tested, "hits": hits, "misses": misses,
            "retired": len([e for e in edges.values() if e.status == "retired"])}


# ── reading the brain ───────────────────────────────────────────────────


def _edge_dict(edge: KnowledgeEdge) -> dict:
    conf = _confidence(edge.supports, edge.refutes)
    return {
        "subsystem": edge.subsystem,
        "symptom": edge.symptom,
        "statement": f"changes to {edge.subsystem} tend to cause {edge.symptom.replace('-', ' ')}",
        "confidence": conf,
        "verified_count": edge.verified_count,
        "supports": edge.supports,
        "refutes": edge.refutes,
        "status": edge.status,
        "case_ids": edge.case_ids or [],
        "trend": ("weakening" if edge.refutes and _confidence(edge.supports, edge.refutes)
                  < _confidence(edge.supports, max(0, edge.refutes - 1)) else "holding"),
    }


def edges(session: Session, product_id: int | None = None,
          include_retired: bool = False) -> list[dict]:
    """The learned map, strongest belief first."""
    stmt = select(KnowledgeEdge).where(KnowledgeEdge.product_id == product_id)
    if not include_retired:
        stmt = stmt.where(KnowledgeEdge.status == "active")
    rows = session.scalars(stmt).all()
    out = [_edge_dict(e) for e in rows]
    return sorted(out, key=lambda e: (-e["confidence"], -e["verified_count"]))


# ── design-doc / PR review (prevention, not detection) ──────────────────


def review_change(session: Session, text: str, product_id: int | None = None) -> dict:
    """Match a spec or PR description against the learned edges and flag risks.

    This is the exit criterion: a risky proposed change is flagged BEFORE it
    ships, and each flag is grounded in real past cases rather than a hunch.
    """
    touched = _classify(text, SUBSYSTEMS)
    active = {e["subsystem"]: e for e in edges(session, product_id)}  # strongest per subsystem
    all_edges = edges(session, product_id)

    flags = []
    for sub in touched:
        for e in all_edges:
            if e["subsystem"] != sub:
                continue
            flags.append({
                "subsystem": sub,
                "symptom": e["symptom"],
                "confidence": e["confidence"],
                "verified_count": e["verified_count"],
                "case_ids": e["case_ids"],
                "recommendation": _recommend(sub, e["symptom"]),
                "why": (f"This change touches {sub}. On this product, {sub} changes have "
                        f"caused {e['symptom'].replace('-', ' ')} "
                        f"{e['verified_count']}× (confidence {e['confidence']:.0%})."),
            })
    flags.sort(key=lambda f: -f["confidence"])

    level = ("high" if any(f["confidence"] >= 0.75 for f in flags)
             else "elevated" if flags else "clear")
    return {
        "risk": level,
        "subsystems_touched": touched,
        "flags": flags,
        "summary": _review_summary(touched, flags),
    }


def _recommend(subsystem: str, symptom: str) -> str:
    tests = {
        "battery-drain": "run a battery-impact test on a real device before shipping",
        "crashes": "add a crash-regression pass on the affected flows",
        "data-loss": "verify migration/round-trip on real user data",
        "churn": "gate behind a staged rollout and watch retention",
        "slowness": "profile the hot path and check startup time",
        "billing-anger": "dry-run the billing flow end to end in staging",
    }
    return tests.get(symptom, f"add a targeted check for {symptom.replace('-', ' ')}")


def _review_summary(touched: list[str], flags: list[dict]) -> str:
    if not touched:
        return "This change doesn't touch any subsystem with a known failure history."
    if not flags:
        return (f"Touches {', '.join(touched)}, but none has a learned failure pattern yet — "
                "no history to warn from.")
    top = flags[0]
    return (f"Resembles past {top['subsystem']} changes that caused "
            f"{top['symptom'].replace('-', ' ')}. {top['recommendation'].capitalize()}.")


# ── the onboarding oracle ───────────────────────────────────────────────


def ask(session: Session, question: str, product_id: int | None = None,
        product_name: str | None = None) -> dict:
    """Answer 'what usually goes wrong here?' from the product's own history.

    Grounded by construction: the answer is assembled from edges and the cases
    behind them, so every claim carries a case id. When there is no history it
    says so rather than generalising — the same honesty rule as everywhere else.
    """
    active = edges(session, product_id)
    who = product_name or "this product"
    if not active:
        return {"answer": f"No failure patterns learned for {who} yet — I need a few "
                          "confirmed fixes before I can tell you what tends to go wrong.",
                "edges": [], "grounded": False}

    # if the question names a subsystem, focus there; otherwise the top risks
    focus = _classify(question, SUBSYSTEMS)
    relevant = [e for e in active if e["subsystem"] in focus] if focus else active
    relevant = (relevant or active)[:5]

    lines = [f"On {who}, here's what history shows:"]
    for e in relevant:
        cite = (f" (e.g. case #{e['case_ids'][0]})" if e["case_ids"] else "")
        lines.append(f"• {e['subsystem'].capitalize()} changes tend to cause "
                     f"{e['symptom'].replace('-', ' ')} — seen {e['verified_count']}×, "
                     f"confidence {e['confidence']:.0%}{cite}.")
    return {"answer": "\n".join(lines), "edges": relevant, "grounded": True}


def summarize_pr_terms(text: str) -> dict:
    """Small helper: what a change appears to touch, for display."""
    return {"subsystems": _classify(text, SUBSYSTEMS),
            "symptoms_mentioned": _classify(text, SYMPTOMS)}
