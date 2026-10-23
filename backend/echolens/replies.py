"""Closing the loop with users: reply DRAFTS for affected reviewers, and follow-up
questions when the evidence is thin.

Nothing here posts anywhere. Drafts are text a human copies into Play Console or
App Store Connect; there is deliberately no store client in this module. The
default wording is a deterministic template. An LLM may reword it only when one
is passed in (injectable, like the other integrations), and its output is
rejected in favour of the template if it is empty, too long, or promises things.
"""
from __future__ import annotations

import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    Finding, FixWatch, HypothesisRow, Investigation, Product, Review)
from echolens.detector.detect import reference_now
from echolens.fixwatch import _terms_for, product_name_of
from echolens.textkit import parse_version
from echolens.timeutil import aware_utc
from echolens.tools._util import match_score

REPLY_MAX_CHARS = 350        # Play Store's developer-reply limit; also a sane App Store length
MAX_DRAFTS = 50
DEFAULT_WINDOW_DAYS = 30
TRANSLATION_NOTE = ("Drafts are in English. Reviews that look non-English are flagged "
                    "instead of translated — reply to those in the reviewer's language.")

# Words an English review nearly always contains. A review of four or more words
# with none of them, or one that is mostly non-ASCII, is flagged as non-English.
_EN_COMMON = frozenset(
    "the and is it my to of this that app in on for not but after since was you with "
    "have has are so when every just very can don it's im its me we they be as at no".split())

_PROMISE = re.compile(r"\b(guarantee|promise|definitely|will be fixed|within \d|by (monday|tomorrow|friday))\b", re.I)


# ── affected reviewers ────────────────────────────────────────────────

def looks_non_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    if sum(1 for c in letters if ord(c) > 0x024F) / len(letters) > 0.3:
        return True
    words = re.findall(r"[^\W\d_]+(?:'[a-z]+)?", text.lower())
    return len(words) >= 4 and not any(w in _EN_COMMON for w in words)


def _topic(finding: Finding, terms: list[str]) -> str:
    """A short noun phrase for the problem, lifted from the finding summary."""
    summary = (finding.summary or (finding.json or {}).get("summary", "") or "").strip()
    if summary:
        first = re.split(r"[.;:\n]| — | - ", summary)[0].strip()
        if first:
            return (first[:60].rsplit(" ", 1)[0] if len(first) > 60 else first).rstrip(",")
    return " ".join(terms[:2]) or "the issue you reported"


def _watch_of(session: Session, finding: Finding) -> FixWatch | None:
    return session.scalars(select(FixWatch).where(
        FixWatch.finding_id == finding.id).order_by(FixWatch.id.desc())).first()


def _store_links(product: Product | None) -> dict:
    """Plain URLs, built from the package / app id. Nothing is called."""
    pkg = (product.package_name or "").strip() if product else ""
    if not pkg:
        return {"store": None, "console_url": None, "console_name": None}
    if pkg.isdigit():
        return {"store": "app_store", "console_name": "App Store Connect",
                "console_url": f"https://appstoreconnect.apple.com/apps/{pkg}/distribution/reviews"}
    return {"store": "play_store", "console_name": "Play Console",
            "console_url": "https://play.google.com/console/developers",
            "listing_url": f"https://play.google.com/store/apps/details?id={pkg}"}


def affected_reviews(session: Session, finding: Finding, watch: FixWatch | None,
                     fixed_version: str | None) -> tuple[list[Review], int]:
    """(reviews, skipped_on_fixed_version): negative reviews matching the theme
    terms inside the window, scoped to the finding's product. Reviews already on
    the fixed version are excluded — the fix is not news to them — and counted."""
    inv = session.get(Investigation, finding.investigation_id)
    pid = (watch.product_id if watch else None) or finding.product_id or (inv.product_id if inv else None)
    product = product_name_of(session, pid)
    terms = list(watch.terms) if watch and watch.terms else _terms_for(session, finding)
    window = watch.window_days if watch else DEFAULT_WINDOW_DAYS
    now = reference_now(session, product)
    fix = aware_utc(watch.fix_date) if watch and watch.fix_date else now
    start = fix - timedelta(days=window)
    stmt = select(Review).where(Review.rating <= 2, Review.created_at >= start,
                                Review.created_at <= now).order_by(Review.created_at.desc())
    if product:
        stmt = stmt.where(Review.product == product)
    target = parse_version(fixed_version)
    out, skipped = [], 0
    for r in session.scalars(stmt).all():
        if terms and match_score(r.text or "", terms) == 0:
            continue
        rv = parse_version(r.version)
        if target is not None and rv is not None and rv >= target:
            skipped += 1
            continue
        out.append(r)
    return out, skipped


# ── drafts ────────────────────────────────────────────────────────────

def draft_reply(topic: str, fixed_version: str | None, fix_confirmed: bool) -> str:
    """Short, polite, non-promissory. Never claims more than we know: a fix is
    described as shipped only when a version is known, as confirmed only when
    verification confirmed it."""
    topic = topic.strip().rstrip(".")
    if fixed_version and fix_confirmed:
        body = (f"Thanks for flagging {topic} — v{fixed_version} fixes it. "
                "Please update to the latest version, and if you still see it, reply here.")
    elif fixed_version:
        body = (f"Thanks for flagging {topic} — v{fixed_version} includes a change aimed at it. "
                "Please update, and if you still see it, reply here.")
    elif fix_confirmed:
        body = (f"Thanks for flagging {topic} — a recent update fixes it. "
                "Please update to the latest version, and if you still see it, reply here.")
    else:
        body = (f"Thanks for flagging {topic}. We've looked into it and are working on it. "
                "If you can, reply here with your app version and what you were doing when it happened.")
    return body[:REPLY_MAX_CHARS]


def _reword(llm, base: str, review_text: str) -> str:
    """Optional LLM polish. Falls back to the template on any problem."""
    try:
        res = llm.complete_json(
            "Reword this app-store developer reply to sound warm and natural. Keep every fact, "
            f"stay under {REPLY_MAX_CHARS} characters, make no promises or timelines, and do not "
            "add claims. Reply in English.",
            f"Reviewer wrote: {review_text[:300]}\n\nDraft reply: {base}",
            {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]},
            "reply_drafter")
        text = str((res.parsed or {}).get("reply", "")).strip()
    except Exception:
        return base
    if not text or len(text) > REPLY_MAX_CHARS or _PROMISE.search(text):
        return base
    return text


def reply_drafts(session: Session, finding: Finding, llm=None) -> dict:
    """The "reply to affected reviewers" panel's data. DRAFT ONLY."""
    inv = session.get(Investigation, finding.investigation_id)
    watch = _watch_of(session, finding)
    fixed_version = watch.fixed_in_version if watch else None
    confirmed = bool(watch and watch.status == "confirmed")
    terms = list(watch.terms) if watch and watch.terms else _terms_for(session, finding)
    pid = (watch.product_id if watch else None) or finding.product_id or (inv.product_id if inv else None)
    product = session.get(Product, pid) if pid else None
    reviews, skipped = affected_reviews(session, finding, watch, fixed_version)
    topic = _topic(finding, terms)
    base = draft_reply(topic, fixed_version, confirmed)
    drafts = []
    for r in reviews[:MAX_DRAFTS]:
        non_en = looks_non_english(r.text or "")
        text = None if non_en else (_reword(llm, base, r.text) if llm is not None else base)
        drafts.append({
            "review_id": r.id, "ext_id": r.ext_id, "rating": r.rating, "version": r.version,
            "created_at": aware_utc(r.created_at).isoformat() if r.created_at else None,
            "excerpt": (r.text or "")[:240],
            "language": "non_english" if non_en else "en",
            "draft": text,
            "note": ("Looks non-English — not drafted. Reply in the reviewer's language."
                     if non_en else None),
        })
    return {
        "finding_id": finding.id, "mode": "fixed" if confirmed else ("shipped" if fixed_version else "investigating"),
        "fixed_in_version": fixed_version, "fix_confirmed": confirmed, "topic": topic,
        "total": len(reviews), "shown": len(drafts), "skipped_on_fixed_version": skipped,
        "drafts": drafts, "translation_note": TRANSLATION_NOTE,
        "draft_only": True, **_store_links(product),
    }


# ── follow-up questions for thin evidence ─────────────────────────────

# (keywords in what_would_settle_it / a hypothesis, question to put to users)
_QUESTION_RULES: list[tuple[tuple[str, ...], str]] = [
    (("version", "release", "build", "rollout"),
     "Which app version are you on (Settings > About), and did this start after a recent update?"),
    (("device", "model", "hardware", "os ", "android", "ios", "chipset"),
     "What device and OS version are you using, and does it happen on any other device?"),
    (("log", "crash", "error", "stack", "trace"),
     "Do you see an error message or a crash when it happens? If so, what does it say?"),
    (("price", "pricing", "flag", "experiment", "paywall", "offer", "subscription", "billing"),
     "Did you notice a change in price, offer or what's included right before this happened?"),
    (("background", "sync", "battery", "drain", "power"),
     "Does it still happen with background sync turned off? Roughly how much does it cost you per hour?"),
    (("network", "wifi", "connection", "latency", "slow", "load"),
     "Does it happen on both Wi-Fi and mobile data? How long does it take?"),
    (("when", "start", "timing", "began", "first"),
     "When did you first notice it, and has it happened every day since?"),
]
_DEFAULT_QUESTIONS = [
    "Which app version are you on, and what device and OS?",
    "What were you doing right before it happened, and can you make it happen again?",
    "When did you first notice it?",
]


def followup_questions(session: Session, finding: Finding, inv: Investigation | None = None) -> dict:
    """1-3 short questions the team could ask affected users when a case ended on
    thin evidence. Built from what_would_settle_it and the still-open hypotheses
    by keyword rules, so the same case always yields the same questions."""
    inv = inv or session.get(Investigation, finding.investigation_id)
    settle = ((finding.json or {}).get("what_would_settle_it") or "").strip()
    hyps = []
    if inv is not None:
        hyps = [h for h in session.scalars(select(HypothesisRow).where(
            HypothesisRow.investigation_id == inv.id).order_by(HypothesisRow.confidence.desc())).all()
            if h.status != "rejected"]
    questions: list[dict] = []
    seen: set[str] = set()

    def add(q: str, source: str, why: str) -> None:
        if q not in seen and len(questions) < 3:
            seen.add(q)
            questions.append({"question": q, "source": source, "why": why})

    def rules_for(text: str, source: str, why: str, limit: int) -> None:
        low = f" {text.lower()} "
        n = 0
        for words, q in _QUESTION_RULES:
            if n < limit and any(w in low for w in words):
                add(q, source, why)
                n += 1

    if settle:
        rules_for(settle, "what_would_settle_it", f"To settle: {settle[:120]}", 2)
    for h in hyps[:2]:
        why = f"Open hypothesis {h.hid}: {h.statement[:100]}"
        rules_for(f"{h.statement} {(h.json or {}).get('next_test', '')}", "hypothesis", why, 1)
    for q in _DEFAULT_QUESTIONS:
        add(q, "default", "General details that usually narrow a case down")
    return {"finding_id": finding.id, "case_status": inv.status if inv else None,
            "questions": questions[:3], "draft_only": True}
