"""Portfolio command center (v9.0) — attention is the scarce resource.

EchoLens already budgets its own compute. This budgets the PM's attention: one
ranked view across every product, answering "which of these do I touch first?"

The score is deterministic and, more importantly, **explained**. A ranking a PM
cannot audit is a ranking they will not trust, so every product carries the exact
reasons that put it where it is, each with the number behind it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, Finding, FixWatch, Investigation, Product, Review)
from echolens.impact import severity
from echolens.themes import CHRONIC_DAYS
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

# Below this many reviews in a window, a negative-review RATE is noise. Reporting
# "100% negative" off one review is a statistic-shaped guess.
MIN_RATE_SAMPLE = 5

BANDS = (
    (60.0, "on_fire", "Needs you today"),
    (25.0, "attention", "Worth a look"),
    (5.0, "watch", "Trending, not urgent"),
    (0.0, "healthy", "Nothing demanding attention"),
)


def _n(count: int, noun: str, plural: str | None = None) -> str:
    """Plural forms a person would write. "(s)" is a note to self, not copy."""
    return f"{count} {noun}" if count == 1 else f"{count} {plural or noun + 's'}"


# The attention score reads "higher = needs you more", the opposite of every
# quality score a PM has seen. Users are shown HEALTH (100 − attention, higher
# is healthier) with labels that read the right way round; the attention score
# itself still does the ranking.
HEALTH_LABELS = {
    "healthy": "Healthy",
    "watch": "Watch",
    "attention": "Needs attention",
    "on_fire": "Needs you today",
}


def health(score: float) -> float:
    """Health shown to users: 100 − attention, floored at 0."""
    return round(max(0.0, 100.0 - score), 1)


def _band(score: float) -> tuple[str, str]:
    for threshold, key, label in BANDS:
        if score >= threshold:
            return key, label
    return "healthy", "Nothing demanding attention"


def _negative_rate(session: Session, product: str | None, start, end) -> float | None:
    """Share of reviews in the window that are negative. A rate, not a count —
    the only way a 3-review app and a 30,000-review app compare honestly.

    Counted in SQL: this used to pull every review the product has ever had into
    Python just to filter two date windows, twice per product, per page load.
    """
    from sqlalchemy import case
    row = session.execute(
        select(func.count(Review.id),
               func.sum(case((Review.rating <= 2, 1), else_=0)))
        .where(Review.product == product,
               Review.created_at >= start, Review.created_at < end)
    ).one()
    return _rate(row[0] or 0, row[1] or 0)


def _rate(total: int, negatives: int) -> float | None:
    # None, not 0.0, when the window is too thin to be a rate. A single review
    # used to award the FULL trend weight and print "negative reviews up 75 pts"
    # as fact; and an empty window scored 0.0, indistinguishable from a genuine
    # 0% negative rate.
    if total < MIN_RATE_SAMPLE:
        return None
    return negatives / total


def _load_board(session: Session, products: list[Product], now: datetime) -> dict[int, dict]:
    """Every input the attention score reads, for all products at once.

    product_snapshot used to run ~10 queries PER product (watches, resolved
    cases, findings, two theme queries plus one get() per finding, the queue,
    two rate windows, collectors), so the board grew linearly with the
    portfolio. Here each table is read once with `product_id IN (...)` and the
    two rate windows come from one GROUP BY.
    """
    from sqlalchemy import case

    from echolens.db.models import CollectorState
    from echolens.themes import theme_lifecycles

    ids = [p.id for p in products]
    data = {pid: {"watches": [], "resolved": [], "latest": {}, "untriaged": 0, "waiting_incidents": 0,
                  "sources": [], "chronic": [], "rates": (None, None),
                  "has_reviews": False} for pid in ids}
    if not ids:
        return data
    for w in session.scalars(select(FixWatch).where(FixWatch.product_id.in_(ids))).all():
        data[w.product_id]["watches"].append(w)
    resolved = session.scalars(select(Investigation).where(
        Investigation.product_id.in_(ids), Investigation.status == "resolved")).all()
    by_id = {inv.id: inv for inv in resolved}
    for inv in resolved:
        data[inv.product_id]["resolved"].append(inv)
    if by_id:
        for finding in session.scalars(select(Finding).where(
                Finding.investigation_id.in_(list(by_id))).order_by(Finding.id)).all():
            data[by_id[finding.investigation_id].product_id]["latest"][
                finding.investigation_id] = finding
    for pid, themes in theme_lifecycles(session, ids, now).items():
        data[pid]["chronic"] = [t for t in themes if t["status"] == "chronic"]
    for pid, n in session.execute(select(AnomalyEvent.product_id, func.count(AnomalyEvent.id)).where(
            AnomalyEvent.product_id.in_(ids), AnomalyEvent.status == "pending",
            AnomalyEvent.merged_into_id.is_(None)).group_by(AnomalyEvent.product_id)).all():
        data[pid]["untriaged"] = n

    from echolens.detector.incidents import waiting_groups
    for members in waiting_groups(session, ids):
        data[members[0].product_id]["waiting_incidents"] += 1

    # Both rate windows for every product in one pass: [now-35d, now-7d) is the
    # baseline, [now-7d, now) the recent week — same bounds as _negative_rate.
    split, start = now - timedelta(days=7), now - timedelta(days=35)
    is_recent = Review.created_at >= split
    is_neg = Review.rating <= 2
    names = {p.name: p.id for p in products}
    for name, rec_n, rec_neg, base_n, base_neg in session.execute(
            select(Review.product,
                   func.sum(case((is_recent, 1), else_=0)),
                   func.sum(case((is_recent & is_neg, 1), else_=0)),
                   func.sum(case((~is_recent, 1), else_=0)),
                   func.sum(case((~is_recent & is_neg, 1), else_=0)))
            .where(Review.product.in_(list(names)),
                   Review.created_at >= start, Review.created_at < now)
            .group_by(Review.product)).all():
        data[names[name]]["rates"] = (_rate(rec_n or 0, rec_neg or 0),
                                      _rate(base_n or 0, base_neg or 0))
    # Whether ANY feedback exists (not just in the last 7 days), for has_data.
    for name in session.scalars(select(Review.product).where(
            Review.product.in_(list(names))).distinct()).all():
        data[names[name]]["has_reviews"] = True

    for s in session.scalars(select(CollectorState).where(
            CollectorState.product_id.in_(ids))).all():
        data[s.product_id]["sources"].append(s)
    return data


def product_snapshot(session: Session, product: Product, now: datetime,
                     data: dict | None = None) -> dict:
    """One product's attention score plus the reasons behind it.

    `data` is this product's slice of `_load_board`; the board passes it in so
    ranking N products costs the same queries as ranking one.
    """
    if data is None:
        data = _load_board(session, [product], now)[product.id]
    pid = product.id
    reasons: list[dict] = []
    score = 0.0

    # ── live problems, weighted by severity ────────────────────────────
    watches = data["watches"]
    confirmed_inv = {w.investigation_id for w in watches if w.status == "confirmed"}
    high = medium = 0
    top_problem = None
    resolved = data["resolved"]
    latest: dict[int, Finding] = data["latest"]
    for inv in resolved:
        if inv.id in confirmed_inv:
            continue
        f = latest.get(inv.id)
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
                        "text": f"{_n(len(regressed), 'fix', 'fixes')} regressed after shipping"})

    # ── chronic themes ─────────────────────────────────────────────────
    chronic = data["chronic"]
    if chronic:
        score += W_CHRONIC * len(chronic)
        reasons.append({"kind": "chronic", "weight": round(W_CHRONIC * len(chronic), 1),
                        "text": f"{_n(len(chronic), 'complaint theme')} unresolved for over {CHRONIC_DAYS} days"})

    # ── queue depth ────────────────────────────────────────────────────
    # Preserve the original attention/health contribution of raw pending rows.
    # The visible decision count is incidents (singletons count once).
    untriaged = data["untriaged"]
    waiting = data["waiting_incidents"]
    if untriaged or waiting:
        score += W_UNTRIAGED * untriaged
        reasons.append({"kind": "untriaged", "weight": round(W_UNTRIAGED * untriaged, 1),
                        "text": f"{_n(waiting, 'incident')} waiting for triage"})

    # ── trend: is sentiment getting worse? ─────────────────────────────
    recent, baseline = data["rates"]
    has_rate = recent is not None and baseline is not None
    delta = round(recent - baseline, 4) if has_rate else 0.0
    if has_rate and baseline > 0 and delta > 0.02:
        score += W_TREND * min(1.0, delta / max(baseline, 0.01))
        reasons.append({
            "kind": "trend", "weight": round(W_TREND * min(1.0, delta / max(baseline, 0.01)), 1),
            "text": f"negative reviews up {int(round(delta * 100))} pts vs the prior month "
                    f"({int(round(baseline * 100))}% → {int(round(recent * 100))}%)"})

    # ── can we even see this product right now? ────────────────────────
    sources = data["sources"]
    stale = [s for s in sources if s.status == "error"
             or (s.last_run_at and (now - (aware_utc(s.last_run_at) or now)).days >= 2)]
    if stale:
        score += W_STALE_DATA
        reasons.append({"kind": "stale", "weight": W_STALE_DATA,
                        "text": f"{_n(len(stale), 'source')} not reporting — this ranking may be out of date"})

    band, band_label = _band(score)
    reasons.sort(key=lambda r: -r["weight"])
    return {
        "product_id": pid,
        "product": product.name,
        "is_demo": product.is_demo,
        "score": round(score, 1),
        "band": band,
        "band_label": band_label,
        "health": health(score),
        "health_label": HEALTH_LABELS[band],
        "reasons": reasons,
        "headline": (reasons[0]["text"] if reasons
                     else ("no data collected yet" if not sources else "nothing demanding attention")),
        "top_problem": top_problem,
        "open_problems": high + medium,
        "regressions": len(regressed),
        "untriaged": waiting,
        "negative_rate_pct": round(100 * recent, 1) if recent is not None else None,
        "negative_rate_delta_pct": round(100 * delta, 1) if has_rate else None,
        "confirmed_fixes": len(confirmed_inv),
        # Whether ANY feedback exists, not whether the last 7 days had some: the
        # old test (`bool(recent)`) told a product with 3,000 older reviews
        # "No feedback has been collected" beside a 12-week rating chart.
        "has_data": bool(sources) or data["has_reviews"],
    }


def visible_products(session: Session, demo_only: bool = False):
    """Products a caller may see. `demo_only` confines a public-demo guest to
    products flagged `is_demo`, so a shared URL cannot list real ones."""
    q = select(Product).order_by(Product.id)
    if demo_only:
        q = q.where(Product.is_demo == True)  # noqa: E712
    return session.scalars(q).all()


def portfolio(session: Session, as_of: datetime | None = None,
              demo_only: bool = False) -> dict:
    """Every product the caller may see, ranked by how much it needs them today."""
    now = as_of or datetime.now(timezone.utc)
    products = visible_products(session, demo_only)
    board = _load_board(session, products, now)
    rows = [product_snapshot(session, p, now, board[p.id]) for p in products]
    rows.sort(key=lambda r: (-r["score"], r["product"]))
    on_fire = [r for r in rows if r["band"] == "on_fire"]
    return {
        "generated": now.date().isoformat(),
        "products": rows,
        "total_products": len(rows),
        "needs_attention": len([r for r in rows if r["band"] in ("on_fire", "attention")]),
        "verdict": _verdict(rows, on_fire),
    }


# ── stored rows: /portfolio without recomputing the whole board ─────────
#
# Each product's row needs theme lifecycles, two review-rate windows over the
# whole corpus, the queue and the collectors. At live scale (7 products, ~9k
# reviews, a pooled remote DB) recomputing all of it on every open of "All
# products" was the slowest screen in the app. Rows are now stored (one
# Setting per product, with computed_at) and recomputed when:
#   * the product's data changed — a cheap fingerprint (grouped counts and max
#     ids, a handful of queries for every product at once) no longer matches;
#   * the row is older than SUMMARY_TTL (rates drift with the clock) — at most
#     MAX_REFRESH_PER_REQUEST such rows per request, oldest first;
#   * there is no row yet.
# The worker refreshes stale rows in the background, so a request rarely pays.

SUMMARY_TTL = timedelta(minutes=10)
MAX_REFRESH_PER_REQUEST = 2
_SUMMARY_KEY = "portfolio_row"


def _summary_key(pid: int) -> str:
    return f"{_SUMMARY_KEY}:{pid}"


def _fingerprints(session: Session, products: list[Product]) -> dict[int, list]:
    """What a product's row depends on, cheaply: counts, newest ids and
    statuses, for every product in ONE statement (a UNION ALL of grouped
    selects, every value cast to text so the branches line up on Postgres)."""
    from sqlalchemy import String, case, cast, literal, union_all

    from echolens.db.models import CollectorState

    ids = [p.id for p in products]
    names = {p.name: p.id for p in products}
    fp: dict[int, list] = {pid: [] for pid in ids}
    if not ids:
        return fp

    def t(col):
        return cast(col, String)

    blank = literal("")
    parts = [
        select(literal("reviews"), t(Review.product), t(func.count(Review.id)),
               t(func.max(Review.id)), blank, blank)
        .where(Review.product.in_(list(names))).group_by(Review.product),
        select(literal("cases"), t(Investigation.product_id), t(func.count(Investigation.id)),
               t(func.max(Investigation.id)),
               t(func.sum(case((Investigation.status == "resolved", 1), else_=0))),
               t(func.max(Investigation.resolved_at)))
        .where(Investigation.product_id.in_(ids)).group_by(Investigation.product_id),
        select(literal("watch"), t(FixWatch.product_id), t(FixWatch.status),
               t(func.count(FixWatch.id)), blank, blank)
        .where(FixWatch.product_id.in_(ids)).group_by(FixWatch.product_id, FixWatch.status),
        select(literal("signal"), t(AnomalyEvent.product_id), t(AnomalyEvent.status),
               t(func.count(AnomalyEvent.id)), t(func.max(AnomalyEvent.id)), blank)
        .where(AnomalyEvent.product_id.in_(ids))
        .group_by(AnomalyEvent.product_id, AnomalyEvent.status),
        select(literal("source"), t(CollectorState.product_id), t(CollectorState.status),
               t(CollectorState.last_run_at), blank, blank)
        .where(CollectorState.product_id.in_(ids)),
    ]
    for kind, key, *values in session.execute(union_all(*parts)).all():
        pid = names.get(key) if kind == "reviews" else (int(key) if key and key.isdigit() else None)
        if pid in fp:
            fp[pid].append([kind, *("" if v is None else str(v) for v in values)])
    # Sorted lists: the stored copy round-trips through JSON.
    return {pid: sorted(v, key=str) for pid, v in fp.items()}


def refresh_summaries(session: Session, products: list[Product], now: datetime | None = None,
                      fingerprints: dict[int, list] | None = None,
                      existing: dict | None = None) -> dict[int, dict]:
    """Recompute and store these products' rows. Returns {product_id: stored}."""
    from echolens.db.models import Setting

    now = now or datetime.now(timezone.utc)
    if not products:
        return {}
    fingerprints = fingerprints or _fingerprints(session, products)
    board = _load_board(session, products, now)
    if existing is None:
        keys = [_summary_key(p.id) for p in products]
        existing = {s.key: s for s in session.scalars(select(Setting).where(Setting.key.in_(keys)))}
    out = {}
    for p in products:
        stored = {"row": product_snapshot(session, p, now, board[p.id]),
                  "computed_at": now.isoformat(), "fingerprint": fingerprints.get(p.id, [])}
        row = existing.get(_summary_key(p.id))
        if row is None:
            session.add(Setting(key=_summary_key(p.id), value=stored))
        else:
            row.value = stored
        out[p.id] = stored
    session.flush()
    return out


def _is_stale(stored, fingerprint, now: datetime) -> tuple[bool, str]:
    if not isinstance(stored, dict) or "row" not in stored:
        return True, "missing"
    if stored.get("fingerprint") != fingerprint:
        return True, "changed"
    try:
        at = datetime.fromisoformat(stored["computed_at"])
    except (KeyError, TypeError, ValueError):
        return True, "missing"
    return (now - aware_utc(at) > SUMMARY_TTL), "old"


def _stored_rows(session: Session, products: list[Product]) -> dict:
    """{key: Setting} for these products' stored rows (one query)."""
    from echolens.db.models import Setting
    keys = [_summary_key(p.id) for p in products]
    if not keys:
        return {}
    return {s.key: s for s in session.scalars(select(Setting).where(Setting.key.in_(keys))).all()}


def stale_products(session: Session, now: datetime | None = None) -> list[Product]:
    """Products whose stored row is missing, changed or older than SUMMARY_TTL —
    what the worker refreshes in the background."""
    now = now or datetime.now(timezone.utc)
    products = list(visible_products(session))
    stored = {k: s.value for k, s in _stored_rows(session, products).items()}
    fps = _fingerprints(session, products)
    return [p for p in products
            if _is_stale(stored.get(_summary_key(p.id)), fps.get(p.id, []), now)[0]]


def stored_portfolio(session: Session, demo_only: bool = False, now: datetime | None = None,
                     max_refresh: int = MAX_REFRESH_PER_REQUEST) -> dict:
    """The same payload as `portfolio`, served from stored rows (see above),
    each row carrying `computed_at` and `updated_min_ago`."""
    now = now or datetime.now(timezone.utc)
    products = list(visible_products(session, demo_only))
    settings_rows = _stored_rows(session, products)
    stored = {k: s.value for k, s in settings_rows.items()}
    fps = _fingerprints(session, products)
    must, old = [], []
    for p in products:
        stale, why = _is_stale(stored.get(_summary_key(p.id)), fps.get(p.id, []), now)
        if stale:
            (old if why == "old" else must).append(p)
    old.sort(key=lambda p: stored[_summary_key(p.id)].get("computed_at", ""))
    todo = must + old[:max_refresh]
    fresh = refresh_summaries(session, todo, now, fps, settings_rows) if todo else {}
    rows = []
    for p in products:
        item = fresh.get(p.id) or stored[_summary_key(p.id)]
        try:
            at = aware_utc(datetime.fromisoformat(item["computed_at"]))
        except (KeyError, TypeError, ValueError):
            at = now
        rows.append({**item["row"], "computed_at": at.isoformat(),
                     "updated_min_ago": max(0, int((now - at).total_seconds() // 60))})
    rows.sort(key=lambda r: (-r["score"], r["product"]))
    on_fire = [r for r in rows if r["band"] == "on_fire"]
    return {
        "generated": now.date().isoformat(),
        "products": rows,
        "total_products": len(rows),
        "needs_attention": len([r for r in rows if r["band"] in ("on_fire", "attention")]),
        "verdict": _verdict(rows, on_fire),
        "updated_min_ago": max((r["updated_min_ago"] for r in rows), default=0),
        "refreshed": [p.name for p in todo],
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

def portfolio_brief(session: Session, as_of: datetime | None = None,
                    demo_only: bool = False) -> dict:
    """One brief for everything you own, ranked by impact across products.

    Not a concatenation of per-product briefs — the ranking is global, so the
    second-worst problem on your biggest app can outrank the worst problem on
    your smallest.
    """
    from echolens.brief import weekly_briefs

    now = as_of or datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    board = portfolio(session, now, demo_only)

    per_product, problems, fixes, regressions = [], [], [], []
    products = visible_products(session, demo_only)
    briefs = weekly_briefs(session, [p.id for p in products], now)
    for p in products:
        b = briefs[p.id]
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
        f"Across {_n(board['total_products'], 'product')}: {_n(len(problems), 'new problem')}, "
        f"{_n(len(fixes), 'fix', 'fixes')} verified, {_n(len(regressions), 'regression')}.")
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
    invs = session.scalars(select(Investigation).where(
            Investigation.seeded_from_pattern.is_not(None))).all()
    product_ids = {inv.product_id for inv in invs if inv.product_id is not None}
    products = {p.id: p for p in session.scalars(select(Product).where(
        Product.id.in_(product_ids))).all()} if product_ids else {}
    for inv in invs:
        seed = inv.seeded_from_pattern or {}
        if not seed.get("cross_product"):
            continue
        if since is not None and (aware_utc(inv.created_at) or since) < since:
            continue
        product = products.get(inv.product_id)
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
