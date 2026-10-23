"""How much to trust a finding, and the fixes worth telling people about.

Two read-only summaries the UI shows without having to understand the
investigation internals:

* **trust** — computed from the case's own evidence rows, deterministically:
  how many items per source, how many distinct sources, whether the two-source
  rule (investigator/guards.two_source_rule — the same function the
  investigator concluded under, not a copy) holds for the supported
  hypothesis, and the confidence band. Evidence a reviewer struck does not
  count. The words "verified"/"proven" are reserved for the rule the Inspector
  uses: the finding is approved, not flagged for review, AND a fix is confirmed.
* **confirmed fixes** — fix-watches that reached "confirmed" recently, with the
  complaint drop and how many affected reviewers could be replied to. That
  count reuses replies.affected_reviews (the reply panel's own matching), so
  the number on Today is the number the panel opens with; no draft is built.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import EvidenceRow, Finding, FixWatch, HypothesisRow, Investigation, Setting
from echolens.investigator.guards import two_source_rule
from echolens.timeutil import aware_utc

# Same thresholds the investigator works to: 0.80 is the bar for `resolved`.
HIGH_CONFIDENCE = 0.8
MEDIUM_CONFIDENCE = 0.6

CONFIRMED_WINDOW_DAYS = 14
MAX_CONFIRMED_CARDS = 3
_DISMISS_KEY = "fix_dismissed"

# (singular, plural) for the sources evidence actually comes from. Anything
# else falls back to its own name, title-cased, as format.ts sourceLabel does.
_SOURCE_NOUNS: dict[str, tuple[str, str]] = {
    "play_store": ("Play Store review", "Play Store reviews"),
    "app_store": ("App Store review", "App Store reviews"),
    "release_notes": ("release note", "release notes"),
    "github": ("GitHub issue", "GitHub issues"),
    "github_issues": ("GitHub issue", "GitHub issues"),
    "github_prs": ("GitHub PR", "GitHub PRs"),
    "reddit": ("Reddit post", "Reddit posts"),
    "zendesk": ("support ticket", "support tickets"),
    "support": ("support ticket", "support tickets"),
    "discord": ("Discord message", "Discord messages"),
    "in_app": ("in-app report", "in-app reports"),
    "csv": ("imported review", "imported reviews"),
    "csv_reviews": ("imported review", "imported reviews"),
}


def confidence_band(confidence: float | None) -> str:
    c = float(confidence or 0.0)
    return "high" if c >= HIGH_CONFIDENCE else "medium" if c >= MEDIUM_CONFIDENCE else "low"


def _noun(source: str, n: int) -> str:
    one, many = _SOURCE_NOUNS.get(source, (source.replace("_", " ").capitalize(),) * 2)
    return f"{n} {one if n == 1 else many}"


def is_verified(finding: Finding | None, watch: FixWatch | None) -> bool:
    """The Inspector's "proven cause" rule, server-side: approved, not flagged
    for review again, and a fix confirmed."""
    return bool(finding is not None and finding.status == "approved"
                and not (finding.json or {}).get("needs_review")
                and watch is not None and watch.status == "confirmed")


def trust_label(trust: dict) -> str:
    """The badge's sentence. Never claims more than `verified` allows."""
    if not trust["two_source_ok"]:
        if trust["distinct_sources"] <= 1:
            return "Single source — needs corroboration"
        # Several channels, but not two INDEPENDENT ones behind the cause.
        return f"{trust['distinct_sources']} sources, not independent — needs corroboration"
    lead = "Verified fix" if trust["verified"] else f"{trust['confidence'].capitalize()} confidence"
    parts = " + ".join(_noun(s["source"], s["count"]) for s in trust["sources"])
    n = trust["distinct_sources"]
    return f"{lead} · {parts} · {n} {'source' if n == 1 else 'sources'}"


def _trust(finding: Finding, evidence: list[EvidenceRow], hyps: list[HypothesisRow],
           watch: FixWatch | None) -> dict:
    fj = finding.json or {}
    struck = {r.get("eid") for r in fj.get("rejected_evidence") or []}
    kept = [e for e in evidence if e.eid not in struck]
    counts = Counter(e.source for e in kept)
    sources = [{"source": s, "count": n}
               for s, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    hid = fj.get("supported_hypothesis")
    hyp = next((h for h in hyps if h.hid == hid), None) if hid else None
    ok = False
    if hyp is not None:
        h = {"id": hyp.hid, "statement": hyp.statement, "confidence": hyp.confidence,
             "status": hyp.status, **(hyp.json or {})}
        h["evidence_for"] = [x for x in h.get("evidence_for", []) if x not in struck]
        ok = two_source_rule(h, [{"id": e.eid, "source": e.source, "snippet": e.snippet,
                                  **(e.json or {})} for e in kept])
    conf = finding.confidence if finding.confidence is not None else fj.get("confidence")
    out = {"sources": sources, "distinct_sources": len(counts), "two_source_ok": ok,
           "confidence": confidence_band(conf), "evidence_count": len(kept),
           "verified": is_verified(finding, watch)}
    out["label"] = trust_label(out)
    return out


def trust_for_cases(session: Session, investigation_ids: list[int]) -> dict[int, dict]:
    """{investigation_id: trust} for every case that has a finding — four
    queries for the whole list rather than four per case."""
    ids = sorted({i for i in investigation_ids if i is not None})
    if not ids:
        return {}
    findings: dict[int, Finding] = {}
    for f in session.scalars(select(Finding).where(
            Finding.investigation_id.in_(ids)).order_by(Finding.id)).all():
        findings[f.investigation_id] = f            # newest wins
    if not findings:
        return {}
    evidence: dict[int, list[EvidenceRow]] = {}
    for e in session.scalars(select(EvidenceRow).where(
            EvidenceRow.investigation_id.in_(list(findings)))).all():
        evidence.setdefault(e.investigation_id, []).append(e)
    hyps: dict[int, list[HypothesisRow]] = {}
    for h in session.scalars(select(HypothesisRow).where(
            HypothesisRow.investigation_id.in_(list(findings)))).all():
        hyps.setdefault(h.investigation_id, []).append(h)
    watches: dict[int, FixWatch] = {}
    for w in session.scalars(select(FixWatch).where(
            FixWatch.finding_id.in_([f.id for f in findings.values()])).order_by(FixWatch.id)).all():
        watches[w.finding_id] = w                   # newest wins
    return {iid: _trust(f, evidence.get(iid, []), hyps.get(iid, []), watches.get(f.id))
            for iid, f in findings.items()}


def finding_trust(session: Session, finding: Finding) -> dict:
    return trust_for_cases(session, [finding.investigation_id]).get(finding.investigation_id) \
        or _trust(finding, [], [], None)


# ── confirmed fixes for Today ───────────────────────────────────────────


def _dismiss_key(user_id: int) -> str:
    return f"{_DISMISS_KEY}:{user_id}"


def dismissed_fixes(session: Session, user_id: int | None) -> set[int]:
    if user_id is None:
        return set()
    row = session.get(Setting, _dismiss_key(user_id))
    ids = (row.value or {}).get("ids", []) if row and isinstance(row.value, dict) else []
    return {int(i) for i in ids if str(i).isdigit()}


def dismiss_fix(session: Session, user_id: int, watch_id: int) -> set[int]:
    """Hide one confirmed fix from this user's Today, for good."""
    ids = dismissed_fixes(session, user_id) | {int(watch_id)}
    row = session.get(Setting, _dismiss_key(user_id))
    value = {"ids": sorted(ids)}
    if row is None:
        session.add(Setting(key=_dismiss_key(user_id), value=value))
    else:
        row.value = value
    session.flush()
    return ids


def _drop_pct(watch: FixWatch) -> int | None:
    b, p = watch.baseline_rate, watch.post_rate
    if b is None or p is None or b <= 0:
        return None
    return max(0, round((b - p) / b * 100))


def fix_headline(watch: FixWatch) -> str:
    what = (watch.metric or "").strip() or "these"
    drop = _drop_pct(watch)
    since = (f"since v{watch.fixed_in_version}" if watch.fixed_in_version
             else "since the fix shipped")
    if drop:
        return f"Fix confirmed — {what} complaints down {drop}% {since}"
    return f"Fix confirmed — {what} complaints are down {since}"


def recent_confirmed_fixes(session: Session, product_id: int | None, user_id: int | None,
                           as_of: datetime | None = None,
                           days: int = CONFIRMED_WINDOW_DAYS,
                           limit: int = MAX_CONFIRMED_CARDS) -> list[dict]:
    """Fix-watches on this product confirmed in the last `days`, newest first,
    minus the ones this user dismissed. At most `limit`."""
    from echolens.replies import affected_reviews

    now = as_of or datetime.now(timezone.utc)
    stmt = select(FixWatch).where(FixWatch.status == "confirmed",
                                  FixWatch.confirmed_at.is_not(None))
    if product_id is not None:
        stmt = stmt.where(FixWatch.product_id == product_id)
    hidden = dismissed_fixes(session, user_id)
    recent = [w for w in session.scalars(stmt).all()
              if w.id not in hidden
              and timedelta(0) <= now - aware_utc(w.confirmed_at) <= timedelta(days=days)]
    recent.sort(key=lambda w: aware_utc(w.confirmed_at), reverse=True)
    out = []
    for w in recent[:limit]:
        finding = session.get(Finding, w.finding_id)
        inv = session.get(Investigation, w.investigation_id)
        reply_count = 0
        # Reply drafts only exist for a resolved case; the count says the same.
        if finding is not None and inv is not None and inv.status == "resolved":
            reply_count = len(affected_reviews(session, finding, w, w.fixed_in_version)[0])
        out.append({
            "watch_id": w.id, "finding_id": w.finding_id, "investigation_id": w.investigation_id,
            "headline": fix_headline(w), "metric": w.metric, "drop_pct": _drop_pct(w),
            "baseline_rate": w.baseline_rate, "post_rate": w.post_rate,
            "fixed_in_version": w.fixed_in_version,
            "confirmed_at": aware_utc(w.confirmed_at).isoformat(),
            "chart": w.chart_json, "reply_count": reply_count,
        })
    return out
