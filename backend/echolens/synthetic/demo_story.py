"""The demo's history — so every screen of a fresh demo has something real on it.

`generate()` seeds the corpus and two pending anomalies; on its own that leaves
Cases, Plan, Learned patterns, Calibration and the Today "Fix confirmed" card
empty until someone runs (and pays for) investigations. `seed_demo_story` runs
the history instead, deterministically:

* every case is a REAL investigation: the actual loop, guards, evidence and
  trace, driven by a scripted model exactly as the eval harness drives it — no
  live LLM, no API key, and every case shows the steps it took;
* two older crash themes are fixed: their post-fix complaints become the
  happy reviews a fix would bring, and the real fix-watch flow (issue linked →
  closed → evaluated) measures the drop and confirms them;
* reviewers have approved and challenged findings (with reasons), so
  Calibration has a curve, and two challenges re-opened their cases;
* one finding is parked and one is won't-fix.

Only ever applied to the demo product, and only when it has no cases yet. The
legacy `generate(session)` used by the eval/golden tests is untouched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, EvidenceRow, Finding, FindingDecision, Investigation, Issue, LLMCall,
    Product, Review, ReviewFeedback, TraceStep)
from echolens.llm.client import LLMResult

REPO = "lumo-app/lumo"


class _Script:
    """Replays fixed structured responses (the eval harness's ScriptedLLM)."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)

    def complete_json(self, system, user, json_schema, agent) -> LLMResult:
        parsed = self._responses.pop(0) if self._responses else {}
        return LLMResult(parsed=parsed, tokens_in=1800, tokens_out=420, ms=900, model="scripted-demo")


# ── the cases ───────────────────────────────────────────────────────────
#
# Each topic: the signal it starts from, the review search that reads the
# complaints, and (for a cause that clears the bar) the second source that
# corroborates it. `days_ago` is when it was opened, relative to the corpus's
# "today".

def _topics(today: datetime) -> list[dict]:
    d = lambda n: (today - timedelta(days=n)).date().isoformat()  # noqa: E731
    return [
        {"key": "sync_crash", "days_ago": 1, "status": "resolved", "confidence": 0.89,
         "metric": "sync crashes share of negative reviews",
         "signal": "Sync crashes after photo upload completion following the v3.2 release.",
         "h1": "v3.2 background sync causes crashes after upload completion",
         "h2": "Android 15 causes the upload crashes",
         "reviews": {"query": "sync crashes upload", "date_from": d(7), "rating_max": 2},
         "release": "3.2.0", "github": "disposed completion callback gallery",
         "summary": "The v3.2 sync regression crashes the gallery after uploads",
         "prose": "Upload reviews describe sync crashes after completion [ev_001]. "
                  "The v3.2 release enabled background photo sync [ev_002]. "
                  "The completion callback causes the crash by reading a disposed view [ev_003].",
         "actions": [("Stop the upload callback from accessing disposed gallery views", "HIGH", "LOW")]},
        {"key": "battery", "slug": "demo1", "days_ago": 5, "status": "resolved", "confidence": 0.85,
         "h1": "v3.2 background sync causes battery drain",
         "h2": "the Android 15 update causes the drain",
         "reviews": {"query": "battery drain", "date_from": d(7), "rating_max": 2},
         "github": "background sync battery wakelock",
         "summary": "Background sync in v3.2 drives the battery spike",
         "prose": "Battery complaints come from the v3.2 background sync: reviews tie the "
                  "drain to the update [ev_001] and the sync worker holds a wakelock when its "
                  "queue is empty [ev_002]. The Android 15 rollout was ruled out — the "
                  "mechanism is in the app [ev_002].",
         "actions": [("Release the sync wakelock when the upload queue is empty", "HIGH", "LOW"),
                     ("Default background sync to Wi-Fi only until 3.2.1 ships", "MED", "LOW")]},
        {"key": "shipping", "slug": "demo2", "days_ago": 4, "status": "insufficient_evidence",
         "confidence": 0.4,
         "h1": "the new print pricing drove the shipping complaints",
         "reviews": {"query": "shipping cost", "rating_max": 3},
         "summary": "Not enough evidence behind the shipping-cost complaints",
         "prose": "Reviews mention shipping costs after the pricing post, but nothing ties "
                  "them to a release or a defect.",
         "settle": "print-order data before and after the pricing change"},
        {"key": "export", "days_ago": 48, "status": "resolved", "confidence": 0.86,
         "metric": "album-export crash share of negative reviews",
         "signal": "Crashes when exporting large albums, often with HEIC photos.",
         "h1": "album export crashes on HEIC files", "h2": "large albums run out of memory",
         "reviews": {"query": "crashed exporting album", "date_to": d(21), "rating_max": 2},
         "github": "export HEIC fails",
         "summary": "Album export crashes on HEIC photos",
         "prose": "Export crashes come from HEIC files: reviews describe the crash on album "
                  "export [ev_001] and the HEIC export failure is reproduced on GitHub [ev_002].",
         "actions": [("Fall back to JPEG when HEIC encoding fails during export", "HIGH", "MED")],
         "fix": {"closed_days_ago": 20, "terms": ["exporting", "album"],
                 "match": "exporting an album",
                 "after": "Exporting albums works again since the update. Thanks!"}},
        {"key": "video", "days_ago": 40, "status": "resolved", "confidence": 0.88,
         "metric": "large-video crash share of negative reviews",
         "signal": "The viewer crashes opening large 4K videos, some on devices low on storage.",
         "h1": "4K videos crash the viewer", "h2": "low device storage causes the crash",
         "reviews": {"query": "crashing large videos", "date_to": d(18), "rating_max": 2},
         "github": "video thumbnails blank 4K",
         "summary": "Opening large 4K videos crashes the viewer",
         "prose": "Large-video crashes are the 4K decoder path: reviews report the crash when "
                  "opening big videos [ev_001] and the same 4K files render blank on GitHub [ev_002].",
         "actions": [("Decode 4K previews off the main thread", "HIGH", "MED")],
         "fix": {"closed_days_ago": 17, "terms": ["crashing", "videos"],
                 "match": "open large videos",
                 "after": "Large videos open smoothly now. Great update."}},
        {"key": "search", "days_ago": 20, "status": "resolved", "confidence": 0.82,
         "metric": "search complaint share of 3-star reviews",
         "signal": "Search misses tagged photos and the index looks stale after sync.",
         "h1": "search ignores accents and tags", "h2": "the search index is stale after sync",
         "reviews": {"query": "search tags", "rating_max": 3},
         "github": "search diacritics",
         "summary": "Search misses accented and tagged photos",
         "prose": "Search misses come from diacritic matching: reviews say tags do not stick "
                  "in search [ev_001] and the diacritics bug is filed on GitHub [ev_002].",
         "actions": [("Normalise accents in the search index", "MED", "MED")]},
        {"key": "metered", "days_ago": 3, "status": "resolved", "confidence": 0.83,
         "metric": "mobile-data complaint share of negative reviews",
         "signal": "Sync uploads photo backups over mobile data and drains the battery.",
         "h1": "sync ignores the Wi-Fi-only setting", "h2": "photo backups are larger in 3.2",
         "reviews": {"query": "battery update", "date_from": d(7), "rating_max": 2},
         "github": "sync metered connection",
         "summary": "Sync uploads over mobile data despite Wi-Fi only",
         "prose": "Battery and data complaints come from sync running on metered networks: "
                  "reviews blame the update [ev_001] and a GitHub issue reports uploads over "
                  "mobile data [ev_002].",
         "actions": [("Respect the Wi-Fi-only setting in the sync scheduler", "MED", "LOW")],
         "challenge": {"reason": "wrong_cause",
                       "note": "This is the wakelock bug again — metered uploads are a symptom.",
                       "confidence": 0.9, "h1": "the sync wakelock bug also drives the data use",
                       "github": "background sync battery wakelock",
                       "summary": "The sync wakelock bug, not metered uploads, drives these complaints",
                       "prose": "Re-examined: the complaints trace to the sync worker holding "
                                "its wakelock [ev_001][ev_002], the cause already found for the "
                                "battery spike."}},
        {"key": "storage", "days_ago": 2, "status": "resolved", "confidence": 0.81,
         "metric": "full-storage battery complaints",
         "signal": "Battery drains while the sync worker retries on full storage; large uploads stall.",
         "h1": "the sync worker loops when storage is full", "h2": "large uploads time out",
         "reviews": {"query": "battery update", "date_from": d(7), "rating_max": 2},
         "github": "sync storage full loop",
         "summary": "Sync worker spins when device storage is full",
         "prose": "Part of the drain comes from the sync worker retrying in a tight loop on "
                  "full storage: reviews report the drain [ev_001] and the loop is filed on "
                  "GitHub [ev_002]. A missing retry delay causes every upload failure.",
         "uncited_draft": True,
         "actions": [("Back off sync retries when storage is full", "MED", "LOW")],
         "challenge": {"reason": "wrong_severity",
                       "note": "Real, but it only hits devices with full storage — not a headline.",
                       "confidence": 0.82, "h1": "the full-storage retry loop, on a small slice of devices",
                       "github": "sync storage full loop",
                       "summary": "Sync retry loop on full storage (a small slice of devices)",
                       "prose": "Re-examined with the reviewer's note: the retry loop is real "
                                "[ev_001][ev_002] but limited to devices with full storage."}},
        {"key": "startup", "days_ago": 60, "status": "insufficient_evidence", "confidence": 0.55,
         "metric": "startup-crash share of negative reviews",
         "signal": "The app crashes on startup after clearing the cache.",
         "h1": "clearing the cache corrupts the local database",
         "reviews": {"query": "crash startup cache", "rating_max": 2},
         "summary": "Working lead: startup crashes after clearing the cache",
         "prose": "A handful of reviews report the app failing at startup after a cache "
                  "clear [ev_001]. Nothing else on record corroborates it.",
         "settle": "crash logs from an affected device",
         "challenge": {"reason": "weak_evidence",
                       "note": "Ask support for crash logs before concluding anything.",
                       "confidence": 0.45, "h1": "a migration fails on a cleared cache",
                       "summary": "Working lead: startup crashes still need device logs",
                       "prose": "Searched again with the reviewer's note [ev_001]. Still one "
                                "source and no logs, so nothing is named yet.",
                       "settle": "crash logs from support"}},
        {"key": "slow", "days_ago": 90, "status": "insufficient_evidence", "confidence": 0.5,
         "metric": "slowness mentions on older phones",
         "signal": "The gallery feels slow on older phones since the 3.0 redesign.",
         "h1": "the 3.0 gallery redesign is slow on older phones",
         "reddit": "slow older phones",
         "summary": "Not enough evidence that Lumo got slower on older phones",
         "prose": "One community thread says the app feels slow on older phones; reviews do "
                  "not corroborate it.",
         "settle": "frame-time telemetry on older devices"},
    ]


# Verdicts beyond the challenges above (which are verdicts too).
# The "slow" case is left for a human on purpose: Today should have one.
_APPROVED = {"battery": "Matches the wakelock trace engineering found.",
             "shipping": "Right call — this is pricing, not a bug.",
             "export": "", "video": "Confirmed on a Pixel 6 with 4K clips.",
             "search": ""}


def _ref(result: dict, key: str) -> str | None:
    rows = result.get(key) or []
    return rows[0]["ref"] if rows else None


def _quote(row: dict | None) -> str:
    """The cited item's own words, verbatim from the tool result: what a viewer
    reads as the exhibit. A stand-in phrase here shows up on every demo case."""
    if not row:
        return ""
    if row.get("title"):            # GitHub issue: its title is the report
        return row["title"]
    return (row.get("snippet") or row.get("notes") or "").strip()


def _first(result: dict, key: str) -> dict | None:
    rows = result.get(key) or []
    return rows[0] if rows else None


def _script(session: Session, product: str, t: dict, *, hyp: str | None = None,
            confidence: float | None = None, github: str | None = "",
            summary: str | None = None, prose: str | None = None,
            settle: str | None = None) -> list[dict]:
    """The scripted model turns for one case, with evidence refs read from the
    same tools the investigator will call (so the guards accept them)."""
    from echolens.tools.search_github_issues import search_github_issues
    from echolens.tools.search_reddit import search_reddit
    from echolens.tools.search_reviews import search_reviews
    from echolens.tools.get_release_notes import get_release_notes
    from echolens.intent import BUG, UX_CONFUSION, classify

    resolved = t["status"] == "resolved"
    conf = t["confidence"] if confidence is None else confidence
    h1 = hyp or t["h1"]
    hyps = [{"id": "H1", "statement": h1, "confidence": 0.5, "status": "active"}]
    if resolved and t.get("h2"):
        hyps.append({"id": "H2", "statement": t["h2"], "confidence": 0.35, "status": "active"})
    out: list[dict] = [{"thought": f"Two readings of '{t['summary'].lower()}'.",
                        "action": "revise_hypotheses", "hypotheses": hyps}]
    refs: list[str] = []
    if t.get("reviews"):
        reviews = search_reviews(session, product=product, **t["reviews"])["reviews"]
        row = next((r for r in reviews if r["rating"] < 4 or
                    classify(r["snippet"], r["rating"]) in (BUG, UX_CONFUSION)), None)
        ref = row["ref"] if row else None
        out.append({"thought": "Read what the complaining users actually say.", "action": "call_tool",
                    "tool": {"name": "search_reviews", "args": t["reviews"], "tests_hypothesis": "H1"}})
        if ref:
            refs.append(ref)
            out.append({"evidence": [{"ref": ref, "snippet": _quote(row),
                                      "supports": ["H1"], "contradicts": []}],
                        "hypothesis_updates": [{"id": "H1", "new_confidence": min(conf, 0.65),
                                                "based_on_refs": [ref], "note": "reviews point here"}]})
        else:
            out.append({"evidence": [], "hypothesis_updates": []})
    if t.get("reddit"):
        row = _first(search_reddit(session, t["reddit"], product=product), "posts")
        ref = row["ref"] if row else None
        out.append({"thought": "Check the community thread.", "action": "call_tool",
                    "tool": {"name": "search_reddit", "args": {"query": t["reddit"]},
                             "tests_hypothesis": "H1"}})
        out.append({"evidence": [{"ref": ref, "snippet": _quote(row), "supports": ["H1"],
                                  "contradicts": []}] if ref else [],
                    "hypothesis_updates": [{"id": "H1", "new_confidence": conf,
                                            "based_on_refs": [ref] if ref else [],
                                            "note": "a single source"}]})
    if t.get("release"):
        row = _first(get_release_notes(session, version=t["release"], product=product), "releases")
        ref = row["ref"] if row else None
        out.append({"thought": "Check what shipped before the complaints started.", "action": "call_tool",
                    "tool": {"name": "get_release_notes", "args": {"version": t["release"]},
                             "tests_hypothesis": "H1"}})
        out.append({"evidence": [{"ref": ref, "snippet": _quote(row),
                                  "supports": ["H1"], "contradicts": []}] if ref else [],
                    "hypothesis_updates": []})
    gh = t.get("github") if github == "" else github
    if resolved and gh:
        row = _first(search_github_issues(session, gh, product=product), "issues")
        ref = row["ref"] if row else None
        out.append({"thought": "Corroborate in a second, independent source.", "action": "call_tool",
                    "tool": {"name": "search_github_issues", "args": {"query": gh},
                             "tests_hypothesis": "H1"}})
        updates = [{"id": "H1", "new_confidence": conf, "based_on_refs": [ref] if ref else [],
                    "note": "mechanism confirmed in a second source"}]
        if len(hyps) > 1:
            updates.append({"id": "H2", "new_confidence": 0.15, "new_status": "rejected",
                            "based_on_refs": [ref] if ref else [], "note": "does not fit the mechanism"})
        out.append({"evidence": [{"ref": ref, "snippet": _quote(row),
                                  "supports": ["H1"], "contradicts": ["H2"] if len(hyps) > 1 else []}]
                    if ref else [], "hypothesis_updates": updates})
    if not resolved:
        out.append({"thought": "One weak source and nothing corroborates it. Being honest.",
                    "action": "conclude",
                    "conclusion": {"status": "insufficient_evidence",
                                   "reason": "single weak source; no corroboration"}})
    out.append({"summary": summary or t["summary"], "prose": prose or t["prose"],
                "confidence": conf, "supported_hypothesis": "H1" if resolved else None,
                "checked": ["play_store", "github"] if resolved else ["play_store", "reddit"],
                "what_would_settle_it": "" if resolved else (settle or t.get("settle", ""))})
    if t.get("uncited_draft") and prose is None:
        out.append(dict(out[-1]))  # both draft attempts expose the uncited claim to the guard
    return out


def _anomaly(session: Session, product: Product, t: dict, opened: datetime) -> AnomalyEvent:
    if t.get("slug"):
        a = session.scalars(select(AnomalyEvent).where(
            AnomalyEvent.slug == t["slug"], AnomalyEvent.product_id == product.id)).first()
        if a is not None:
            a.product_id = product.id
            return a
    a = AnomalyEvent(slug=f"story-{t['key']}", type="theme_volume_surge", metric=t["metric"],
                     delta=0.1, z=3.0, window="7d", status="pending", product_id=product.id,
                     # In the customers' words, as theme detection writes it — and the
                     # anchor the relevance guard holds each hypothesis to.
                     description=t["signal"],
                     created_at=opened)
    session.add(a)
    session.flush()
    return a


def _backdate(session: Session, inv: Investigation, opened: datetime, minutes: int = 12) -> None:
    """Move a case (and everything it wrote) to when it really happened: the
    loop stamps rows with the wall clock, the story needs its own timeline."""
    start = inv.created_at.replace(tzinfo=timezone.utc) if inv.created_at.tzinfo is None else inv.created_at
    shift = opened - start
    inv.created_at = opened
    inv.resolved_at = opened + timedelta(minutes=minutes)
    for step in session.scalars(select(TraceStep).where(TraceStep.investigation_id == inv.id)).all():
        step.created_at = (step.created_at.replace(tzinfo=timezone.utc)
                           if step.created_at.tzinfo is None else step.created_at) + shift
    for f in session.scalars(select(Finding).where(Finding.investigation_id == inv.id)).all():
        f.created_at = inv.resolved_at
    for c in session.scalars(select(LLMCall).where(LLMCall.investigation_id == inv.id)).all():
        c.created_at = opened
    session.flush()


def _finding(session: Session, inv: Investigation) -> Finding:
    return session.scalars(select(Finding).where(Finding.investigation_id == inv.id)
                           .order_by(Finding.id.desc())).first()


def _rewrite_after_fix(session: Session, product: str, match: str, after: str, fixed: datetime) -> int:
    """The fix worked: its complaints stop. Reviews of the fixed problem posted
    after the fix become the reviews such a fix brings."""
    rows = session.scalars(select(Review).where(
        Review.product == product, Review.created_at > fixed,
        Review.text.like(f"%{match}%"))).all()
    for r in rows:
        r.text, r.rating = after, 5
    session.flush()
    return len(rows)


def _issue_number(session: Session, product: str, query: str) -> int:
    from echolens.tools.search_github_issues import search_github_issues
    ref = _ref(search_github_issues(session, query, product=product), "issues") or "#1"
    issue = session.scalars(select(Issue).where(Issue.ext_id == ref.replace("issue ", ""))).first()
    digits = "".join(ch for ch in (issue.ext_id if issue else ref) if ch.isdigit())
    return int(digits or 1)


def seed_demo_story(session: Session) -> dict:
    """Write the demo's history into the demo product. Idempotent: does nothing
    if the demo product is missing or already has cases."""
    from echolens import fixwatch
    from echolens.detector.detect import reference_now
    from echolens.investigator.graph import Investigator
    from echolens.recommender.recommend import recommend
    from echolens.review import approve, challenge, decide

    demo = session.scalars(select(Product).where(Product.is_demo.is_(True))).first()
    if demo is None:
        return {"skipped": "no demo product"}
    if session.scalars(select(Investigation).where(Investigation.product_id == demo.id)).first():
        return {"skipped": "demo already has cases"}
    today = reference_now(session, demo.name)
    out = {"cases": 0, "verdicts": 0, "fixes_confirmed": 0, "decisions": 0}

    topics = _topics(today)
    # The fixes happened before anyone looks: their complaints already stopped.
    for t in topics:
        if t.get("fix"):
            fixed = today - timedelta(days=t["fix"]["closed_days_ago"])
            _rewrite_after_fix(session, demo.name, t["fix"]["match"], t["fix"]["after"], fixed)

    findings: dict[str, Finding] = {}
    for t in topics:
        opened = today - timedelta(days=t["days_ago"])
        anomaly = _anomaly(session, demo, t, opened)
        inv = Investigator(session, anomaly, llm=_Script(_script(session, demo.name, t)),
                           tier="standard").run()
        anomaly.status = "closed"
        _backdate(session, inv, opened)
        if t.get("release"):
            for e in session.scalars(select(EvidenceRow).where(
                    EvidenceRow.investigation_id == inv.id, EvidenceRow.source == "release_notes")):
                e.ref = f"https://github.com/{REPO}/releases/tag/v{t['release']}"
        f = _finding(session, inv)
        out["cases"] += 1
        if f is None:
            continue
        findings[t["key"]] = f
        if t.get("actions"):
            recommend(session, f, llm=_Script([{"actions": [
                {"rank": i + 1, "action": a, "impact": imp, "effort": eff,
                 "rationale": "From the cited evidence."}
                for i, (a, imp, eff) in enumerate(t["actions"])]}]))
        if t.get("challenge"):
            c = t["challenge"]
            child = challenge(session, f, c["note"], reason=c["reason"], llm=_Script(_script(
                session, demo.name, t, hyp=c["h1"], confidence=c["confidence"],
                github=c.get("github"), summary=c["summary"], prose=c["prose"],
                settle=c.get("settle"))))
            _backdate(session, child, opened + timedelta(days=1))
            out["cases"] += 1
            out["verdicts"] += 1
            child_f = _finding(session, child)
            # Only a re-examined cause is approved; approving "no cause found"
            # would turn the case into an open problem with nothing to fix.
            if child_f is not None and child.status == "resolved":
                approve(session, child_f, note="The re-examined cause holds.")
                out["verdicts"] += 1
                child.resolved_at = opened + timedelta(days=1, minutes=12)
        elif t["key"] in _APPROVED:
            approve(session, f, note=_APPROVED[t["key"]])
            out["verdicts"] += 1
        # approve() stamps the wall clock; keep the case on its own timeline.
        inv.resolved_at = opened + timedelta(minutes=12)
        for fb in session.scalars(select(ReviewFeedback).where(
                ReviewFeedback.finding_id == f.id)).all():
            fb.created_at = opened + timedelta(hours=3)

    # Two fixes shipped, were watched, and worked — measured by the real flow.
    for t in topics:
        f = findings.get(t["key"])
        if not t.get("fix") or f is None:
            continue
        number = _issue_number(session, demo.name, t["github"])
        watch = fixwatch.link_issue(session, f, REPO, number, f"https://github.com/{REPO}/issues/{number}")
        watch.terms = list(t["fix"]["terms"])
        watch.metric = t["metric"]
        watch.created_at = today - timedelta(days=t["days_ago"] - 1)
        session.flush()
        closed = today - timedelta(days=t["fix"]["closed_days_ago"])
        fixwatch.on_issue_closed(session, REPO, number, closed)
        _judge(session, watch, demo.name, closed)
    out["fixes_confirmed"] = sum(1 for t in topics if t.get("fix") and t["key"] in findings
                                 and _watch_status(session, findings[t["key"]]) == "confirmed")

    # The battery fix is in flight: its issue is open, nothing verified yet.
    if "battery" in findings:
        number = _issue_number(session, demo.name, "background sync battery wakelock")
        fixwatch.link_issue(session, findings["battery"], REPO, number,
                            f"https://github.com/{REPO}/issues/{number}")

    # Product decisions: one parked until after a planned rewrite, one by design.
    if "search" in findings:
        decide(session, findings["search"], "park", revisit_by=today + timedelta(days=30),
               reason="Folding this into the search rewrite next quarter.")
        out["decisions"] += 1
    if "shipping" in findings:
        decide(session, findings["shipping"], "wont_fix",
               reason="By design — shipping rates are set by the print partner.")
        out["decisions"] += 1
    for d in session.scalars(select(FindingDecision).where(
            FindingDecision.product_id == demo.id)).all():
        d.created_at = today - timedelta(days=1)
    from echolens.cases import _AffectedIndex, _terms
    affected = _AffectedIndex(session, demo.name, today)
    for f, inv, anomaly in session.execute(select(Finding, Investigation, AnomalyEvent)
            .join(Investigation, Investigation.id == Finding.investigation_id)
            .join(AnomalyEvent, AnomalyEvent.id == Investigation.anomaly_id)
            .where(Investigation.product_id == demo.id)):
        f.json = {**f.json, "impact": affected.measure(
            (f.json or {}).get("impact") or {}, _terms(f, anomaly))}
    session.flush()
    return out


def _judge(session: Session, watch, product: str, fixed: datetime) -> None:
    """fixwatch.evaluate, minus its "was a collector running?" check: a seeded
    corpus has no collector, yet every day of it was recorded. Same rates, same
    rule (post-fix at or under CONFIRM_DROP of baseline), same _confirm — which
    also writes the before/after chart and re-mines Learned patterns."""
    from echolens import fixwatch
    w = timedelta(days=watch.window_days)

    def rate(start, end):
        series = fixwatch.complaint_series(session, watch.terms, start, end, product)
        return round(sum(x["count"] for x in series) / len(series), 3) if series else None

    watch.baseline_rate = rate(fixed - w, fixed)
    watch.post_rate = rate(fixed, fixed + w)
    if watch.baseline_rate and watch.post_rate is not None             and watch.post_rate <= watch.baseline_rate * fixwatch.CONFIRM_DROP:
        fixwatch._confirm(session, watch)
        # Confirmed when its window closed, as the scheduled evaluator would —
        # not "the newest review", which in an anchored corpus can sit hours
        # past the wall clock.
        watch.confirmed_at = fixed + w
    session.flush()


def _watch_status(session: Session, finding: Finding) -> str | None:
    from echolens.db.models import FixWatch
    w = session.scalars(select(FixWatch).where(FixWatch.finding_id == finding.id)
                        .order_by(FixWatch.id.desc())).first()
    return w.status if w else None


def seed_demo(session: Session) -> dict:
    """The seed path: the corpus anchored to today, the demo product, and its
    history. What `echolens seed`, SEED_ON_START and /collect/run call."""
    from echolens.db.migrate import backfill_products
    from echolens.synthetic.generate import generate

    counts = generate(session, anchor="today")
    session.flush()
    backfill_products(session)            # the corpus becomes the demo product
    counts["story"] = seed_demo_story(session)
    return counts


# A demo whose newest review is older than this reads as abandoned: every
# "last 7 days" number on Today goes quiet. Weekly is the rhythm it is judged on.
STALE_DAYS = 7


def demo_is_stale(session: Session, now: datetime | None = None) -> bool:
    """True when the demo exists and is out of date (or never got its story)."""
    demo = session.scalars(select(Product).where(Product.is_demo.is_(True))).first()
    if demo is None:
        return False
    if not session.scalars(select(Investigation).where(Investigation.product_id == demo.id)).first():
        return True
    latest = session.scalar(select(Review.created_at).where(Review.product == demo.name)
                            .order_by(Review.created_at.desc()).limit(1))
    if latest is None:
        return True
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    return latest.replace(tzinfo=None) < now - timedelta(days=STALE_DAYS)


def reseed_demo(session: Session) -> dict:
    """Throw away the demo product's data and seed it again, dated to today.

    `seed_demo` only runs on an empty database, so a long-lived deploy kept the
    demo it was born with — July data on a site visited in October. This
    rebuilds just the `is_demo` product: real products are never read or
    touched, and the demo keeps its Product row (and so its id, its links and
    guest scoping). Deterministic, no LLM. Refuses when there is no demo
    product rather than inventing one inside a real workspace.
    """
    from echolens.db.migrate import backfill_products
    from echolens.db.purge import purge_product_data
    from echolens.synthetic.generate import generate

    demo = session.scalars(select(Product).where(Product.is_demo.is_(True))).first()
    if demo is None:
        return {"skipped": "no demo product"}
    purge_product_data(session, demo)
    counts = generate(session, anchor="today")
    session.flush()
    # generate() writes the corpus untagged; with the demo row still present
    # backfill tags it to the demo (and its anomalies to the demo's id).
    backfill_products(session)
    counts["story"] = seed_demo_story(session)
    counts["product_id"] = demo.id
    return counts
