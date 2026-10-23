"""Requests from users — what people ASK for, not what they complain about.

discover.py only ever reads 1-3 star reviews, because its job is finding
problems. That made every feature request invisible: the people who write
"love it, but I wish it had dark mode" leave four stars, and the people who
want an export button are not angry enough to leave one.

This pass reads 3-5 star reviews, keeps the ones that phrase a request ("wish",
"please add", "would love", "it would be great", "missing", "can you add",
"feature request"), pulls out WHAT is being asked for from the words after the
cue, and groups reviews that ask for the same thing.

Deterministic first. Grouping is by the shared noun phrase, so "please add dark
mode" and "would love a dark mode option" land together without a model. An LLM,
when one is supplied, only relabels the groups — exactly the optional path
discover.py uses, with the same guards — and a missing or unsure model leaves
the deterministic statement in place.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review, Setting
from echolens.intent import FEATURE_REQUEST, classify, count_intents
from echolens.textkit import STOPWORDS, tokenize
from echolens.themes.discover import (
    MIN_CLUSTER_SIZE, MIN_LABEL_CONFIDENCE, WINDOW_DAYS, _trend, _truncate,
    banned_terms, is_usable_statement, label_clusters, product_terms)
from echolens.timeutil import aware_utc

MIN_RATING = 3

# The cue, then up to ~8 words of what follows it, stopping at a clause break.
# The tail is where the asked-for thing lives: "please add [a dark mode]".
_CUE_RE = re.compile(
    r"\b(?:i wish|wish (?:it|you|there)(?: (?:had|was|were|would|could|is))?|"
    r"please add|pls add|would love(?: to see| it if| if)?|"
    r"it would be (?:great|nice|awesome|helpful)(?: (?:if|to))?|"
    r"would be (?:great|nice|awesome|helpful) (?:if|to)|missing|"
    r"can you (?:please )?add|could you (?:please )?add|feature request:?|"
    r"hope (?:you|they) add|should (?:add|have|include)|"
    r"needs? (?:an? )?option(?: to| for)?|add (?:an? )?option(?: to| for)?|"
    r"option to|bring back|support for)\s+([^.!?;\n]{2,80})",
    re.IGNORECASE)

# Words that carry no "what" on their own. They glue the request together
# ("you could add", "an option to") and must never become its name.
_FILLER = STOPWORDS | {
    "add", "added", "adding", "option", "options", "ability", "feature", "features",
    "please", "pls", "able", "make", "made", "let", "lets", "allow", "allows",
    "would", "could", "should", "great", "nice", "awesome", "helpful", "love",
    "really", "maybe", "also", "though", "something", "thing", "things", "way",
    "use", "using", "see", "had", "have", "has", "was", "were", "there", "here",
    "app", "apps", "lot", "bit", "good", "better", "able", "being", "which", "where",
    "she", "him", "her", "they", "them", "these", "those", "only", "own", "too",
    "every", "each", "other", "else", "more", "most", "much", "many", "few",
    "request", "requests", "wish", "missing", "support", "back", "bring",
}


def request_tail(text: str | None) -> list[str]:
    """The content words that follow every request cue in a review."""
    out: list[str] = []
    for m in _CUE_RE.finditer(" ".join((text or "").split())):
        words = [w for w in tokenize(m.group(1)) if w not in _FILLER]
        out.extend(words[:4])
    return out


def _phrases(words: list[str]) -> set[str]:
    """Candidate names for one review's request: its words and adjacent pairs."""
    grams = set(words)
    grams |= {f"{a} {b}" for a, b in zip(words, words[1:])}
    return grams


def group_requests(texts: list[str], banned: set[str]) -> list[dict]:
    """Group request reviews by the thing they ask for.

    Greedy over document frequency, bigrams weighted double (they are more
    specific: "dark mode" beats "mode"). A review joins the first chosen phrase
    it contains and is never counted twice, so one review cannot inflate two
    requests.
    """
    tails = [[w for w in request_tail(t) if w not in banned] for t in texts]
    per_review = [_phrases(ws) for ws in tails]
    df: Counter[str] = Counter()
    for grams in per_review:
        df.update(grams)

    scored = sorted(((c * (2.0 if " " in p else 1.0), c, p) for p, c in df.items()
                     if c >= MIN_CLUSTER_SIZE),
                    key=lambda x: (-x[0], x[2]))
    taken: set[int] = set()
    groups: list[dict] = []
    for _score, _c, phrase in scored:
        members = [i for i, grams in enumerate(per_review)
                   if i not in taken and phrase in grams]
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        # "dark" after "dark mode" was already chosen is the same request again.
        if any(set(phrase.split()) <= set(g["phrase"].split()) for g in groups):
            continue
        taken.update(members)
        groups.append({"phrase": phrase, "members": members})
    return groups


def _statement(phrase: str) -> str:
    return f"Users ask for {phrase}"


def _slug(phrase: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", phrase.lower().replace(" ", "-")).strip("-")[:48]


def _candidates(session: Session, product: str | None, days: int,
                as_of: datetime) -> list[Review]:
    start = as_of - timedelta(days=days)
    stmt = select(Review).where(Review.rating >= MIN_RATING,
                                Review.created_at >= start,
                                Review.created_at <= as_of)
    if product:
        stmt = stmt.where(Review.product == product)
    return [r for r in session.scalars(stmt).all()
            if (r.text or "").strip() and classify(r.text, r.rating) == FEATURE_REQUEST]


def discover_requests(session: Session, product: str | None = None, *, llm=None,
                      days: int = WINDOW_DAYS, as_of: datetime | None = None,
                      limit: int = 8, package_name: str | None = None) -> dict:
    """Feature-request / improvement themes from this product's 3-5 star reviews."""
    from echolens.detector.detect import reference_now

    now = as_of or reference_now(session, product)
    rows = _candidates(session, product, days, now)
    base = {"product": product, "reviews_considered": len(rows), "days": days}
    if len(rows) < MIN_CLUSTER_SIZE:
        return {**base, "requests": [], "engine": "none"}

    texts = [r.text or "" for r in rows]
    banned = banned_terms(product, package_name)
    own = product_terms(product, package_name)
    prepared = []
    for g in group_requests(texts, banned)[:limit]:
        members = g["members"]
        dates = [d for d in (aware_utc(rows[m].created_at) for m in members) if d]
        verbatims: list[str] = []
        for m in members:
            t = " ".join(texts[m].split())
            if t and not any(t[:60].lower() == v[:60].lower() for v in verbatims):
                verbatims.append(t)
            if len(verbatims) >= 3:
                break
        ratings = [rows[m].rating for m in members if rows[m].rating]
        prepared.append({
            "phrase": g["phrase"], "count": len(members), "verbatims": verbatims,
            "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "intents": count_intents((rows[m].text, rows[m].rating) for m in members),
            "first_seen": min(dates).date().isoformat() if dates else None,
            "last_seen": max(dates).date().isoformat() if dates else None,
            "trend": _trend(dates, now),
        })

    # Optional relabel. Same contract as discover: one batched call, and any
    # label that is unsure or fails the guards keeps the deterministic name.
    raw_by_index = {int(lab.get("index", -1)): lab
                    for lab in label_clusters(prepared, llm, product)} if llm else {}
    requests = []
    for i, c in enumerate(prepared):
        raw = raw_by_index.get(i) or {}
        statement = " ".join(str(raw.get("statement", "")).split())
        confidence = float(raw.get("label_confidence") or 0.0)
        if statement and confidence >= MIN_LABEL_CONFIDENCE \
                and is_usable_statement(statement, banned, own):
            statement, source = _truncate(statement), "model"
        else:
            statement, source = _statement(c["phrase"]), "phrase"
        requests.append({
            "slug": _slug(c["phrase"]) or f"request-{i + 1}",
            "statement": statement, "phrase": c["phrase"], "label_source": source,
            "count": c["count"], "verbatims": c["verbatims"], "avg_rating": c["avg_rating"],
            "intents": c["intents"], "first_seen": c["first_seen"],
            "last_seen": c["last_seen"], "trend": c["trend"],
        })
    return {**base, "requests": requests,
            "grouped": sum(r["count"] for r in requests), "engine": "phrases"}


def cached_requests(session: Session, product: str | None, *, llm=None,
                    days: int = WINDOW_DAYS, as_of: datetime | None = None,
                    limit: int = 8, package_name: str | None = None,
                    force: bool = False) -> dict:
    """discover_requests behind the same new-data cache discover.py uses, so an
    optional labelling call happens on new reviews, not on every page load."""
    from echolens.detector.detect import reference_now

    now = as_of or reference_now(session, product)
    key = f"requests:{product or '_'}:{days}:{limit}"[:64]
    rows = _candidates(session, product, days, now)
    ids = [r.id for r in rows]
    stamps = [aware_utc(r.created_at) for r in rows if r.created_at]
    fp = (f"{len(rows)}:{max(stamps, default=None)}:{min(stamps, default=None)}:"
          f"{min(ids, default=0)}:{max(ids, default=0)}")
    row = session.get(Setting, key)
    if not force and row and isinstance(row.value, dict) and row.value.get("fingerprint") == fp:
        cached = dict(row.value.get("result") or {})
        cached["cached"] = True
        return cached
    result = discover_requests(session, product, llm=llm, days=days, as_of=now,
                               limit=limit, package_name=package_name)
    if row is None:
        session.add(Setting(key=key, value={"fingerprint": fp, "result": result}))
    else:
        row.value = {"fingerprint": fp, "result": result}
    session.flush()
    result["cached"] = False
    return result
