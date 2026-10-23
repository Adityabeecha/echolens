"""Translate non-English reviews instead of dropping them.

Real products get reviews in many languages. Keyword matching, theme discovery
and request discovery all read English, so a Spanish "la batería se agota"
used to count for nothing. This module:

* detects each review's language (textkit.detect_language — a heuristic, no
  dependency, no network) and stores it in `Review.lang`;
* translates non-English reviews to English in batches through an injected LLM
  and caches the result in `Review.text_en`, so a review is translated once;
* gives analysis one accessor, `analysis_text`, that prefers the translation.

What it never does: replace the original. Evidence quotes, theme verbatims and
reply excerpts keep `Review.text` verbatim, in the language it was written; the
translation is shown beside it. And it never spends without a key, for a guest,
or past the run cap / the product's daily translation budget.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from echolens.db.models import LLMCall, Product, Review
from echolens.logging import get_logger
from echolens.textkit import detect_language, language_name, needs_translation

log = get_logger("translate")

RUN_CAP = 200            # reviews translated per run, at most
BATCH_SIZE = 20          # reviews per LLM call
MAX_CHARS = 1200         # per review sent; longer text is truncated for the model only
# Daily spend on translation per product, unless limits say otherwise
# (`daily_translation_usd` in the workspace or product limits).
DEFAULT_DAILY_USD = 0.50
AGENT = "translate"

_SYSTEM = (
    "Translate app-store reviews into plain English. Keep the meaning, tone and "
    "any product terms, version numbers and feature names exactly. Do not add, "
    "summarise or explain. Return one translation per review id."
)
_SCHEMA = {
    "type": "object",
    "properties": {"translations": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
        "required": ["id", "text"], "additionalProperties": False}}},
    "required": ["translations"],
    "additionalProperties": False,
}


def analysis_text(review) -> str:
    """The text analysis should read: the English translation when there is one,
    else the original. Never use this for anything shown as a quote."""
    return (getattr(review, "text_en", None) or getattr(review, "text", None) or "")


def review_lang(review) -> str:
    """The stored language, or a fresh detection for rows not yet labelled."""
    return getattr(review, "lang", None) or detect_language(getattr(review, "text", None))


def detect_languages(session: Session, product: str | None = None, limit: int = 5000) -> int:
    """Label `lang` on reviews that have none yet. Free: no model involved."""
    stmt = select(Review).where(Review.lang.is_(None)).limit(limit)
    if product:
        stmt = stmt.where(Review.product == product)
    rows = session.scalars(stmt).all()
    for r in rows:
        r.lang = detect_language(r.text)
    session.flush()
    return len(rows)


def spent_today(session: Session, product_id: int | None) -> float:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(func.coalesce(func.sum(LLMCall.cost), 0.0)).where(
        LLMCall.agent.like(f"{AGENT}%"), LLMCall.created_at >= start)
    if product_id is not None:
        stmt = stmt.where(LLMCall.product_id == product_id)
    return float(session.scalar(stmt) or 0.0)


def metered_client(session: Session, product_id: int | None):
    """An OpenAIClient whose every call lands in llm_calls with this product's
    id — the same recording api/app.py _metered_llm does, so Costs shows it."""
    from echolens.llm.openai_client import OpenAIClient

    def _record(agent, model, tokens_in, tokens_out, cost, ms):
        session.add(LLMCall(investigation_id=None, product_id=product_id,
                            agent=f"{AGENT}.{agent}"[:32], model=model, tokens_in=tokens_in,
                            tokens_out=tokens_out, cost=cost, ms=ms))

    return OpenAIClient(on_call=_record)


def _pending(session: Session, product: str | None, limit: int) -> list[Review]:
    stmt = (select(Review).where(Review.text_en.is_(None), Review.lang.is_not(None),
                                 Review.lang.notin_(["en", "und"]))
            .order_by(Review.created_at.desc()).limit(limit))
    if product:
        stmt = stmt.where(Review.product == product)
    return [r for r in session.scalars(stmt).all() if (r.text or "").strip()]


def translate_reviews(session: Session, product: Product | None, llm, *,
                      limit: int = RUN_CAP, daily_usd: float | None = None) -> dict:
    """Translate up to `limit` untranslated non-English reviews of `product`.

    `llm` is any object with complete_json(system, user, schema, agent); pass a
    metered client (metered_client) so spend is recorded with the product id.
    None means no translation at all — detection still runs. Returns counts
    and, when it stopped early, why.
    """
    name = product.name if product else None
    pid = product.id if product else None
    detected = detect_languages(session, name)
    out = {"detected": detected, "translated": 0, "pending": 0, "stopped": None}
    pending = _pending(session, name, max(0, min(limit, RUN_CAP)))
    out["pending"] = len(pending)
    if llm is None:
        out["stopped"] = "no_llm"
        return out
    cap = DEFAULT_DAILY_USD if daily_usd is None else float(daily_usd)
    for i in range(0, len(pending), BATCH_SIZE):
        if spent_today(session, pid) >= cap:
            out["stopped"] = "daily_budget"
            break
        batch = pending[i:i + BATCH_SIZE]
        payload = [{"id": r.id, "language": language_name(r.lang),
                    "text": " ".join((r.text or "").split())[:MAX_CHARS]} for r in batch]
        try:
            res = llm.complete_json(_SYSTEM, json.dumps(payload, ensure_ascii=False),
                                    _SCHEMA, "reviews")
            data = res.parsed if hasattr(res, "parsed") else res
        except Exception as err:   # a failed batch leaves those rows for next run
            log.warning("translate_batch_failed", product=name, error=str(err))
            out["stopped"] = "llm_error"
            break
        by_id = {r.id: r for r in batch}
        for t in (data or {}).get("translations", []) or []:
            try:
                r = by_id.get(int(t.get("id")))
            except (TypeError, ValueError):
                continue
            text = " ".join(str(t.get("text") or "").split())
            # Empty or wildly longer than the original is not a translation.
            if r is None or not text or len(text) > 3 * len(r.text or "") + 200:
                continue
            r.text_en = text
            out["translated"] += 1
        session.flush()
    out["pending"] = len(_pending(session, name, RUN_CAP))
    return out


def translations_for(session: Session, refs: list[str], product: str | None) -> dict[str, dict]:
    """{ext_id: {lang, lang_name, text_en}} for the non-English reviews among
    `refs` — what the case view shows beside a quote. Product-scoped, so a ref
    that collides with another product's review id never borrows its text."""
    refs = [r for r in dict.fromkeys(refs) if r]
    if not refs:
        return {}
    stmt = select(Review).where(Review.ext_id.in_(refs))
    if product:
        stmt = stmt.where(Review.product == product)
    out = {}
    for r in session.scalars(stmt).all():
        lang = review_lang(r)
        if needs_translation(lang):
            out[r.ext_id] = {"lang": lang, "lang_name": language_name(lang),
                             "text_en": r.text_en}
    return out
