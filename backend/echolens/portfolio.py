"""Portfolio command center (v9.0) — attention is the scarce resource.

EchoLens already budgets its own compute. This budgets the PM's attention: one
ranked view across every product, answering "which of these do I touch first?"

The score is deterministic and, more importantly, **explained**. A ranking a PM
cannot audit is a ranking they will not trust, so every product carries the exact
reasons that put it where it is, each with the number behind it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, Finding, FixWatch, Investigation, Product, Review)
from echolens.impact import severity
from echolens.themes import CHRONIC_DAYS, theme_lifecycle
from echolens.timeutil import aware_utc

# What each signal is worth. Tuned so one live SEV1 outranks a pile of chronic
# background noise — a fire beats a smell.
W_SEV1 = 40.0
W_SEV2 = 18.0
W_REGRESSION = 30.0
W_CHRONIC = 8.0
W_UNTRIAGED = 4.0
W_TREND = 25.0        # multiplied by the negative-rate delta (0..1)
W_STALE_DATA = 6.0

BANDS = (
    (60.0, "on_fire", "Needs you today"),
    (25.0, "attention", "Worth a look"),
    (5.0, "watch", "Trending, not urgent"),
    (0.0, "healthy", "Nothing demanding attention"),
)


def _band(score: float) -> tuple[str, str]:
    for threshold, key, label in BANDS:
        if score >= threshold:
            return key, label
    return "healthy", "Nothing demanding attention"


def _negative_rate(session: Session, product: str | None, start, end) -> float:
    """Share of reviews in the window that are negative. A rate, not a count —
    the only way a 3-review app and a 30,000-review app compare honestly."""
    rows = [r for r in session.scalars(
        select(Review).where(Review.product == product)).all()
        if start <= (aware_utc(r.created_at) or start) < end]
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.rating <= 2) / len(rows)


def product_snapshot(session: Session, product: Product, now: datetime) -> dict:
    """One product's attention score plus the reasons behind it."""
    pid = product.id
    reasons: list[dict] = []
    score = 0.0

    # ── live problems, weighted by severity ────────────────────────────
    watches = session.scalars(select(FixWatch).where(FixWatch.product_id == pid)).all()
    confirmed_inv = {w.investigation_id for w in watches if w.status == "confirmed"}
    high = medium = 0
    top_problem = None
    for inv in session.scalars(select(Investigation).where(
            Investigation.product_id == pid,
            Investigation.status == "resolved")).all():
        if inv.id in confirmed_inv:
            continue
        f = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if f is None:
            continue
        impact = (f.json or {}).get("impact", {})
        sev = severity(float(f.confidence or 0.0), impact)
        if sev["band"] == "high":
            high += 1
        elif sev["band"] == "medium":
            medium += 1
        if top_problem is None or sev["score"] > top_problem["sev_score"]:
            top_problem = {"investigation_id": inv.id, "summary": f.summary,
                           "band": sev["band"], "sev_score": sev["score"]}
    if high:
        score += W_SEV1 * high
        reasons.append({"kind": "high", "weight": round(W_SEV1 * high, 1),
                        "text": f"{high} unfixed high-severity problem{'s' if high > 1 else ''}"})
    if medium:
        score += W_SEV2 * medium
        reasons.append({"kind": "medium", "weight": round(W_SEV2 * medium, 1),
                        "text": f"{medium} unfixed medium-severity problem{'s' if medium > 1 else ''}"})

    # ── regressions: a fix that came back is worse than one never made ──
    regressed = [w for w in watches if w.status == "regressed"]
    if regressed:
        score += W_REGRESSION * len(regressed)
        reasons.append({"kind": "regression", "weight": round(W_REGRESSION * len(regressed), 1),
                        "text": f"{len(regressed)} fix(es) regressed"})

    # ── chronic themes ─────────────────────────────────────────────────
    chronic = [t for t in theme_lifecycle(session, now, pid) if t["status"] == "chronic"]
    if chronic:
        score += W_CHRONIC * len(chronic)
        reasons.append({"kind": "chronic", "weight": round(W_CHRONIC * len(chronic), 1),
                        "text": f"{len(chronic)} theme(s) unresolved > {CHRONIC_DAYS}d"})

    # ── queue depth ────────────────────────────────────────────────────
    untriaged = session.scalars(select(AnomalyEvent).where(
        AnomalyEvent.product_id == pid, AnomalyEvent.status == "pending",
        AnomalyEvent.merged_into_id.is_(None))).all()
    if untriaged:
        score += W_UNTRIAGED * len(untriaged)
        reasons.append({"kind": "untriaged", "weight": round(W_UNTRIAGED * len(untriaged), 1),
                        "text": f"{len(untriaged)} anomal{'ies' if len(untriaged) > 1 else 'y'} awaiting triage"})

    # ── trend: is sentiment getting worse? ─────────────────────────────
    recent = _negative_rate(session, product.name, now - timedelta(days=7), now)
    baseline = _negative_rate(session, product.name, now - timedelta(days=35), now - timedelta(days=7))
    delta = round(recent - baseline, 4)
    if baseline > 0 and delta > 0.02:
        score += W_TREND * min(1.0, delta / max(baseline, 0.01))
        reasons.append({
            "kind": "trend", "weight": round(W_TREND * min(1.0, delta / max(baseline, 0.01)), 1),
            "text": f"negative reviews up {int(round(delta * 100))} pts vs the prior month "
                    f"({int(round(baseline * 100))}% → {int(round(recent * 100))}%)"})

    # ── can we even see this product right now? ────────────────────────
    from echolens.db.models import CollectorState
    sources = session.scalars(select(CollectorState).where(
        CollectorState.product_id == pid)).all()
    stale = [s for s in sources if s.status == "error"
             or (s.last_run_at and (now - (aware_utc(s.last_run_at) or now)).days >= 2)]
    if stale:
        score += W_STALE_DATA
        reasons.append({"kind": "stale", "weight": W_STALE_DATA,
                        "text": f"{len(stale)} source(s) stale — this ranking may be out of date"})

    band, band_label = _band(score)
    reasons.sort(key=lambda r: -r["weight"])
    return {
        "product_id": pid,
        "product": product.name,
        "is_demo": product.is_demo,
        "score": round(score, 1),
        "band": band,
        "band_label": band_label,
        "reasons": reasons,
        "headline": (reasons[0]["text"] if reasons
                     else ("no data collected yet" if not sources else "nothing demanding attention")),
        "top_problem": top_problem,
        "open_problems": high + medium,
        "regressions": len(regressed),
        "untriaged": len(untriaged),
        "negative_rate_pct": round(100 * recent, 1),
        "negative_rate_delta_pct": round(100 * delta, 1),
        "confirmed_fixes": len(confirmed_inv),
        "has_data": bool(sources) or recent > 0,
    }


def portfolio(session: Session, as_of: datetime | None = None) -> dict:
    """Every product, ranked by how much it needs the PM today."""
    now = as_of or datetime.now(timezone.utc)
    rows = [product_snapshot(session, p, now)
            for p in session.scalars(select(Product).order_by(Product.id)).all()]
    rows.sort(key=lambda r: (-r["score"], r["product"]))
    on_fire = [r for r in rows if r["band"] == "on_fire"]
    return {
        "generated": now.date().isoformat(),
        "products": rows,
        "total_products": len(rows),
        "needs_attention": len([r for r in rows if r["band"] in ("on_fire", "attention")]),
        "verdict": _verdict(rows, on_fire),
    }


def _verdict(rows: list[dict], on_fire: list[dict]) -> str:
    """The one line the PM reads first."""
    if not rows:
        return "No products connected yet."
    if on_fire:
        top = on_fire[0]
        return f"Start with {top['product']} — {top['headline']}."
    ranked = [r for r in rows if r["score"] > 0]
    if not ranked:
        return "Nothing needs you today across any product."
    top = ranked[0]
    return f"Nothing on fire. If you have time, {top['product']}: {top['headline']}."


# ── portfolio brief ─────────────────────────────────────────────────────

def portfolio_brief(session: Session, as_of: datetime | None = None) -> dict:
    """One brief for everything you own, ranked by impact across products.

    Not a concatenation of per-product briefs — the ranking is global, so the
    second-worst problem on your biggest app can outrank the worst problem on
    your smallest.
    """
    from echolens.brief import weekly_brief

    now = as_of or datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    board = portfolio(session, now)

    per_product, problems, fixes, regressions = [], [], [], []
    for p in session.scalars(select(Product).order_by(Product.id)).all():
        b = weekly_brief(session, now, p.id)
        per_product.append({"product": p.name, "product_id": p.id, "brief": b})
        for np in b["new_problems"]:
            problems.append({**np, "product": p.name, "product_id": p.id})
        for fx in b["fixes_verified"]:
            fixes.append({**fx, "product": p.name, "product_id": p.id})
        for rg in b["regressions"]:
            regressions.append({**rg, "product": p.name, "product_id": p.id})
    problems.sort(key=lambda x: -x.get("impact_score", 0.0))

    # cross-product transfers that actually happened this week
    transfers = recent_transfers(session, since)

    lines = [board["verdict"]]
    lines.append(
        f"Across {board['total_products']} product(s): {len(problems)} new problem(s), "
        f"{len(fixes)} fix(es) verified, {len(regressions)} regression(s).")
    for p in problems[:3]:
        lines.append(f"• {p['product']}: {p['summary']} (case #{p['investigation_id']}).")
    for t in transfers[:1]:
        lines.append(f"↗ Reused {t['from_product']}'s verified fix on {t['product']} "
                     f"(case #{t['investigation_id']}).")

    return {
        "generated": now.date().isoformat(),
        "verdict": board["verdict"],
        "ranked_products": board["products"],
        "problems": problems,
        "fixes_verified": fixes,
        "regressions": regressions,
        "transfers": transfers,
        "per_product": per_product,
        "lines": lines[:6],
    }


def recent_transfers(session: Session, since: datetime | None = None) -> list[dict]:
    """Cases that started from another product's verified pattern."""
    out = []
    for inv in session.scalars(select(Investigation).where(
            Investigation.seeded_from_pattern.is_not(None))).all():
        seed = inv.seeded_from_pattern or {}
        if not seed.get("cross_product"):
            continue
        if since is not None and (aware_utc(inv.created_at) or since) < since:
            continue
        product = session.get(Product, inv.product_id) if inv.product_id else None
        out.append({
            "investigation_id": inv.id,
            "product": product.name if product else None,
            "from_product": seed.get("from_product"),
            "cause": seed.get("cause"),
            "verified_count": seed.get("verified_count"),
            "status": inv.status,
        })
    return out


def transfer_stats(session: Session) -> dict:
    """Does a borrowed pattern actually shortcut an investigation?

    Compares median iterations of cases seeded by a cross-product pattern against
    cold-start cases. Reported with the sample size, and refuses to claim a
    speedup it cannot support.
    """
    import statistics

    def iters(inv) -> int | None:
        raw = (inv.budget_json or {}).get("iterations")
        if raw is None:
            return None
        try:
            return int(str(raw).split("/")[0])
        except (ValueError, TypeError):
            return None

    seeded, cold = [], []
    for inv in session.scalars(select(Investigation)).all():
        n = iters(inv)
        if n is None or n <= 0:
            continue
        seed = inv.seeded_from_pattern or {}
        (seeded if seed.get("cross_product") else cold).append(n)

    med_s = statistics.median(seeded) if seeded else None
    med_c = statistics.median(cold) if cold else None
    saved = None
    if med_s is not None and med_c is not None and med_c > 0:
        saved = round(100 * (med_c - med_s) / med_c, 1)
    return {
        "seeded_cases": len(seeded),
        "cold_cases": len(cold),
        "median_iterations_seeded": med_s,
        "median_iterations_cold": med_c,
        "iterations_saved_pct": saved,
        "sufficient": len(seeded) >= 1 and len(cold) >= 1,
    }
