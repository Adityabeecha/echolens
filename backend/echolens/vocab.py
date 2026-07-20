"""Shared theme vocabulary (v9.0) — one axis for every product you own.

Detection stays emergent (see textkit.top_themes: no keyword list, so it works on
any app). But you cannot COMPARE products on emergent strings: "battery drain" on
one app and "draining battery fast" on another are the same complaint wearing two
labels, and a portfolio view that treats them as different is lying about your
portfolio.

So this module does one narrow job: collapse raw complaint terms onto a canonical
theme id, deterministically and with no LLM. Two tiers, and the tier is always
reported so nothing is silently over-claimed:

  family   — a known complaint family (battery-drain, notification-spam, …).
             Curated, small, and only used for GROUPING things already detected.
  emergent — everything else: a stable id derived from the terms themselves, so
             unknown themes still line up across products when they truly match.

`is_family` on the result tells you which tier you got.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review
from echolens.textkit import tokenize
from echolens.timeutil import aware_utc

# Curated complaint families. Deliberately shallow — these group what detection
# already found; they never decide WHAT gets detected.
FAMILIES: dict[str, tuple[str, frozenset[str]]] = {
    "battery-drain": ("Battery drain", frozenset({
        "battery", "drain", "draining", "drains", "power", "overheat", "overheating",
        "hot", "wakelock", "charge", "charging"})),
    "notification-spam": ("Notification spam", frozenset({
        "notification", "notifications", "notify", "spam", "spammy", "push",
        "alerts", "alert", "badge"})),
    "crash-stability": ("Crashes & freezes", frozenset({
        "crash", "crashes", "crashing", "freeze", "freezes", "freezing", "hang",
        "hangs", "force", "close", "closes", "unresponsive"})),
    "login-auth": ("Login & auth", frozenset({
        "login", "log", "signin", "password", "auth", "authentication", "otp",
        "verification", "account", "locked", "2fa"})),
    "sync-data": ("Sync & data loss", frozenset({
        "sync", "syncing", "synced", "backup", "restore", "lost", "loss",
        "missing", "disappeared", "deleted"})),
    "performance-slow": ("Slow performance", frozenset({
        "slow", "slower", "lag", "laggy", "sluggish", "freeze", "loading",
        "load", "delay", "delays", "stutter"})),
    "payment-billing": ("Payments & billing", frozenset({
        "payment", "payments", "billing", "billed", "charge", "charged", "refund",
        "subscription", "price", "pricing", "checkout"})),
    "connectivity": ("Connectivity", frozenset({
        "connection", "connect", "offline", "network", "wifi", "server",
        "timeout", "disconnect", "disconnected"})),
    "ui-layout": ("UI & layout", frozenset({
        "layout", "design", "redesign", "button", "buttons", "screen", "menu",
        "font", "dark", "theme", "cluttered"})),
    "ads-privacy": ("Ads & privacy", frozenset({
        "ads", "advert", "advertising", "tracking", "privacy", "data", "permission",
        "permissions", "intrusive"})),
    "update-install": ("Update & install", frozenset({
        "install", "installation", "download", "downloading", "upgrade",
        "reinstall", "rollback"})),
    "search-discovery": ("Search & discovery", frozenset({
        "search", "searching", "results", "filter", "filters", "sort", "find"})),
}

# Words that describe a MEASUREMENT rather than a complaint — they must never be
# what two products get compared on.
_NOISE = frozenset({
    "review", "reviews", "star", "stars", "rating", "ratings", "daily", "volume",
    "average", "share", "complaint", "complaints", "negative", "spike", "surge",
    "drop", "case", "investigation", "cause", "causes", "users", "user", "issue",
    "issues", "report", "reports", "feedback", "week", "version", "app", "apps",
    "update", "updates",
})


def _norm(token: str) -> str:
    """Crude, predictable singularisation. No stemmer dependency: this only has
    to be CONSISTENT, since it is applied to both sides of every comparison."""
    t = token.lower()
    for suffix in ("ing", "ies", "es", "s"):
        if len(t) > 4 and t.endswith(suffix):
            if suffix == "ies":
                return t[:-3] + "y"
            return t[: -len(suffix)]
    return t


def canonical_theme(terms: list[str] | None) -> dict:
    """Map raw complaint terms onto a shared theme.

    Returns {"id", "label", "is_family", "terms"} — `terms` are the words to
    measure this theme with, which for a family is the family's whole vocabulary
    (so the rate means the same thing on every product).
    """
    words = [w for w in (terms or []) if w]
    toks = [t for w in words for t in tokenize(w)] or [w.lower() for w in words]
    toks = [t for t in toks if t not in _NOISE]
    if not toks:
        return {"id": "other", "label": "Other", "is_family": False, "terms": []}

    normed = [_norm(t) for t in toks]
    scores: dict[str, int] = {}
    for fid, (_label, vocab) in FAMILIES.items():
        hits = sum(1 for t, n in zip(toks, normed) if t in vocab or n in vocab
                   or any(_norm(v) == n for v in vocab))
        if hits:
            scores[fid] = hits
    if scores:
        # ties break alphabetically so the same input always yields the same id
        fid = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        label, vocab = FAMILIES[fid]
        return {"id": fid, "label": label, "is_family": True, "terms": sorted(vocab)}

    # Emergent: a stable id from the two most salient terms, order-independent.
    uniq = sorted(dict.fromkeys(normed))[:2]
    return {"id": "-".join(uniq), "label": " ".join(uniq).title(),
            "is_family": False, "terms": sorted(dict.fromkeys(normed))[:6]}


def theme_of(anomaly, finding_json: dict | None = None) -> dict:
    """The canonical theme of an anomaly/finding pair."""
    from echolens.impact import theme_terms
    return canonical_theme(theme_terms(anomaly, finding_json or {}))


def theme_rate(session: Session, theme: dict, product: str | None,
               days: int = 30, as_of=None) -> dict:
    """How loudly ONE product is complaining about ONE theme, on the shared axis:
    the share of its negative reviews mentioning the theme's vocabulary.

    A share (not a count) is the only honest cross-product comparison — a big app
    and a small app have wildly different absolute volumes.
    """
    from datetime import timedelta

    from echolens.detector.detect import reference_now
    now = as_of or reference_now(session)
    start = now - timedelta(days=days)
    stmt = select(Review).where(Review.rating <= 2)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = [r for r in session.scalars(stmt).all()
            if (aware_utc(r.created_at) or now) >= start]
    vocab = {_norm(t) for t in theme.get("terms", [])}
    if not rows or not vocab:
        return {"theme_id": theme.get("id"), "product": product, "negatives": len(rows),
                "mentions": 0, "rate_pct": 0.0, "days": days}
    mentions = sum(1 for r in rows
                   if vocab & {_norm(t) for t in tokenize(r.text)})
    return {
        "theme_id": theme.get("id"), "product": product, "negatives": len(rows),
        "mentions": mentions, "rate_pct": round(100 * mentions / len(rows), 1),
        "days": days,
    }


def compare_theme(session: Session, theme: dict, products: list[str],
                  days: int = 30, as_of=None) -> list[dict]:
    """The same theme's complaint rate across products, loudest first."""
    rows = [theme_rate(session, theme, p, days, as_of) for p in products]
    return sorted(rows, key=lambda r: -r["rate_pct"])
