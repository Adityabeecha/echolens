"""Case forensics — read-only views of what an investigation already recorded.

Everything here is DERIVED from stored rows (trace steps, hypotheses, evidence,
the finding). Nothing re-runs a guard against new data, calls a model, or
writes: these are the facts behind the case, shaped for the screens that show
them. Payloads stay small; every function takes the product scope the API has
already enforced.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from echolens.config import MIN_DISTINCT_SOURCES, MIN_INDEPENDENT_EVIDENCE, SUPPORT_CONFIDENCE
from echolens.db.models import (
    EvidenceRow, Finding, HypothesisRow, Investigation, LLMCall, QueuedInvestigation,
    Release, Review, TraceStep)
from echolens.investigator import guards
from echolens.textkit import parse_version
from echolens.timeutil import aware_utc

# ── guard results per case ──────────────────────────────────────────────

GUARDS = (
    ("citation", "Claim grounding"),
    ("two_source", "Two-source rule"),
    ("single_source_cap", f"Single-source cap ({guards.SINGLE_CHANNEL_CONFIDENCE_CAP:.2f})"),
    ("temporal_order", "Temporal order"),
    ("speculation", "Speculation kept apart"),
)
# The statuses that mean a guard changed the outcome.
INTERVENED = frozenset({"capped", "stripped", "blocked"})
_SUPPORTED = ("supported", guards.SINGLE_CHANNEL_STATUS)
_REJECTED_REF = "ref not present in tool result"
_RESOLUTION_REFUSED = "Declared resolution REJECTED by guard"


def _entry(key: str, status: str, detail: str) -> dict:
    return {"key": key, "label": dict(GUARDS)[key], "status": status, "detail": detail}


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def guard_results(hypotheses: list[dict], finding: dict | None,
                  steps: list[tuple[str, dict]]) -> list[dict]:
    """One {key, label, status, detail} per guard, in GUARDS order.

    status: "pass" (checked, nothing to do), "capped" (confidence held down),
    "stripped" (content removed, the rest kept), "blocked" (an outcome
    refused) or "not_applicable" (nothing reached that guard). Read from the
    stored hypotheses, finding JSON and trace `steps` [(kind, content)], so an
    old case reports what happened to it then, not what would happen now.
    """
    finding = finding or {}
    live = [h for h in hypotheses if h.get("status") not in ("rejected", "parked")]
    out = []

    # citation — claim grounding, and evidence refs no tool returned
    rejected_refs = sum(1 for kind, c in steps if kind == "FAIL" and c.get("error") == _REJECTED_REF)
    if finding.get("grounding_violations"):
        n = len(finding["grounding_violations"])
        out.append(_entry("citation", "blocked",
                          f"{_n(n, 'causal claim')} had no valid citation; the drafted cause was "
                          "withheld and is not presented as a conclusion."))
    elif rejected_refs:
        out.append(_entry("citation", "stripped",
                          f"{_n(rejected_refs, 'cited reference')} did not appear in any tool "
                          "result and were rejected as evidence."))
    elif finding:
        out.append(_entry("citation", "pass", "Every causal claim cites evidence on record."))
    else:
        out.append(_entry("citation", "not_applicable", "No finding has been drafted yet."))

    # two_source — >=2 independent items from >=2 sources
    supported = next((h for h in hypotheses if h.get("status") == "supported"), None)
    single = next((h for h in hypotheses if h.get("status") == guards.SINGLE_CHANNEL_STATUS), None)
    refused = sum(1 for kind, c in steps
                  if kind == "CHECK" and str(c.get("text", "")).startswith(_RESOLUTION_REFUSED))
    if supported is not None:
        n = len(supported.get("evidence_for") or [])
        out.append(_entry("two_source", "pass",
                          f"{supported['id']} rests on {_n(n, 'evidence item')} across at least "
                          f"{MIN_DISTINCT_SOURCES} independent sources."))
    elif single is not None:
        out.append(_entry("two_source", "not_applicable",
                          "Only one feedback channel is connected, so the stricter "
                          "single-channel bar applied instead."))
    elif refused:
        out.append(_entry("two_source", "blocked",
                          f"Resolution was declared {_n(refused, 'time')} without a hypothesis "
                          "meeting the rule, and refused."))
    else:
        out.append(_entry("two_source", "not_applicable", "No hypothesis reached the support bar."))

    # single_source_cap — no near-certainty without corroboration
    cap = guards.SINGLE_CHANNEL_CONFIDENCE_CAP
    held = [h for h in live if h.get("status") != "supported"
            and abs(float(h.get("confidence") or 0) - cap) < 1e-6]
    if single is not None:
        out.append(_entry("single_source_cap", "capped",
                          f"{single['id']} is supported by one channel only; confidence capped at {cap:.2f}."))
    elif held:
        out.append(_entry("single_source_cap", "capped",
                          f"{', '.join(h['id'] for h in held)} held at {cap:.2f}: not corroborated by "
                          "a second source."))
    elif hypotheses:
        out.append(_entry("single_source_cap", "pass", "No uncorroborated hypothesis needed capping."))
    else:
        out.append(_entry("single_source_cap", "not_applicable", "No hypotheses yet."))

    # temporal_order — a release cannot cause complaints that predate it
    temporal = [c for kind, c in steps if kind == "REFUTE" and c.get("guard") == "temporal_order"]
    if temporal:
        c = temporal[-1]
        more = f" ({len(temporal)} times in all)" if len(temporal) > 1 else ""
        out.append(_entry("temporal_order", "blocked",
                          f"{c.get('hypothesis')} blamed {c.get('release')} (released "
                          f"{c.get('release_date')}), but the first complaint is from "
                          f"{c.get('first_complaint')}{more}."))
    elif hypotheses:
        out.append(_entry("temporal_order", "pass",
                          "No hypothesis blamed a release that shipped after its first complaint."))
    else:
        out.append(_entry("temporal_order", "not_applicable", "No hypotheses yet."))

    # speculation — uncited causal sentences moved out of the prose
    moved = finding.get("working_hypotheses") or []
    if moved:
        out.append(_entry("speculation", "stripped",
                          f"{_n(len(moved), 'uncited causal sentence')} moved to "
                          "\"Working hypothesis\"; the rest is published."))
    elif finding:
        out.append(_entry("speculation", "pass", "No uncited causal sentence in the finding."))
    else:
        out.append(_entry("speculation", "not_applicable", "No finding has been drafted yet."))
    return out


_STEP_KINDS = ("FAIL", "CHECK", "REFUTE")


def _guard_steps(session: Session, inv_ids: list[int]) -> dict[int, list[tuple[str, dict]]]:
    """Only the trace kinds the guards write, for many cases in one query."""
    out: dict[int, list[tuple[str, dict]]] = {i: [] for i in inv_ids}
    if inv_ids:
        for inv_id, kind, content in session.execute(
                select(TraceStep.investigation_id, TraceStep.kind, TraceStep.content_json)
                .where(TraceStep.investigation_id.in_(inv_ids), TraceStep.kind.in_(_STEP_KINDS))
                .order_by(TraceStep.investigation_id, TraceStep.seq)).all():
            out[inv_id].append((kind, content or {}))
    return out


def hypothesis_dict(h: HypothesisRow) -> dict:
    return {"id": h.hid, "statement": h.statement, "confidence": h.confidence,
            "status": h.status, **(h.json or {})}


def case_guards(session: Session, inv: Investigation, hypotheses: list[dict],
                finding: dict | None) -> list[dict]:
    """guard_results for one case, reading its guard trace steps (one query)."""
    return guard_results(hypotheses, finding, _guard_steps(session, [inv.id])[inv.id])


def guard_config() -> dict:
    """The guard settings in force: read-only, for the landing page and Settings."""
    return {
        "two_source": {"min_items": MIN_INDEPENDENT_EVIDENCE, "min_sources": MIN_DISTINCT_SOURCES,
                       "support_confidence": SUPPORT_CONFIDENCE},
        "single_source_cap": guards.SINGLE_CHANNEL_CONFIDENCE_CAP,
        "temporal_order": True,
        "claim_grounding": True,
        "speculation_label": guards.WORKING_HYPOTHESIS_LABEL,
        "guards": [{"key": k, "label": label} for k, label in GUARDS],
    }


def guard_stats(session: Session, product_id: int | None, now: datetime | None = None) -> dict:
    """How often each guard changed an outcome, over cases opened in the last
    30 and 90 days, plus how many cases were checked in each window. A case is
    "checked" once it has stopped running. Four queries whatever the volume."""
    now = now or datetime.now(timezone.utc)
    since90, since30 = now - timedelta(days=90), now - timedelta(days=30)
    stmt = select(Investigation.id, Investigation.created_at).where(
        Investigation.created_at >= since90.replace(tzinfo=None),
        Investigation.status != "running")
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    cases = {i: aware_utc(at) for i, at in session.execute(stmt).all()}
    ids = list(cases)
    hyps: dict[int, list[dict]] = {i: [] for i in ids}
    findings: dict[int, dict] = {}
    if ids:
        for h in session.scalars(select(HypothesisRow).where(
                HypothesisRow.investigation_id.in_(ids))).all():
            hyps[h.investigation_id].append(hypothesis_dict(h))
        for inv_id, fj in session.execute(select(Finding.investigation_id, Finding.json).where(
                Finding.investigation_id.in_(ids)).order_by(Finding.id)).all():
            findings[inv_id] = fj or {}       # latest wins
    steps = _guard_steps(session, ids)
    counts = {k: {"d30": 0, "d90": 0} for k, _ in GUARDS}
    for inv_id, created in cases.items():
        recent = created is not None and created >= since30
        for g in guard_results(hyps[inv_id], findings.get(inv_id), steps[inv_id]):
            if g["status"] in INTERVENED:
                counts[g["key"]]["d90"] += 1
                counts[g["key"]]["d30"] += recent
    checked30 = sum(1 for at in cases.values() if at is not None and at >= since30)
    return {
        "as_of": now.date().isoformat(),
        "cases_checked": {"d30": checked30, "d90": len(cases)},
        "guards": [{"key": k, "label": label, "interventions": counts[k]} for k, label in GUARDS],
    }


# ── causal chain ────────────────────────────────────────────────────────

_TRIGGER_ORDER = ("release_notes", "github_commits", "github")
_COMPLAINT_SOURCES = frozenset({"play_store", "app_store", "reddit"})


def causal_chain(finding: dict | None, hypotheses: list[dict], evidence: list[dict]) -> dict | None:
    """{trigger, mechanism, symptom, impact} for a supported finding, else None.

    Each element is {text, evidence_ids} or null, and every text already exists
    in the case: trigger = the release/commit/issue evidence the supported
    hypothesis cites; mechanism = that hypothesis's statement; symptom = the
    complaint it cites that the prose cites most; impact = the stored impact
    line (affected share, rating drag). Nothing is generated here.
    """
    from echolens.impact import impact_line

    finding = finding or {}
    h = next((x for x in hypotheses if x["id"] == finding.get("supported_hypothesis")), None)
    if h is None or h.get("status") not in _SUPPORTED:
        return None
    by_id = {e["id"]: e for e in evidence}
    items = [by_id[i] for i in h.get("evidence_for") or [] if i in by_id]

    trigger = None
    for source in _TRIGGER_ORDER:
        hit = next((e for e in items if str(e.get("source", "")).lower() == source), None)
        if hit is not None:
            trigger = {"text": hit.get("snippet", ""), "evidence_ids": [hit["id"]]}
            break

    prose = finding.get("prose", "") or ""
    complaints = [e for e in items if str(e.get("source", "")).lower() in _COMPLAINT_SOURCES]
    symptom = None
    if complaints:
        top = max(complaints, key=lambda e: (prose.count(e["id"]), -complaints.index(e)))
        symptom = {"text": top.get("snippet", ""), "evidence_ids": [top["id"]]}

    impact = finding.get("impact") or {}
    impact_el = None
    if impact.get("measured") and (impact.get("affected_volume") or impact.get("rating_impact")):
        impact_el = {"text": impact_line(impact), "evidence_ids": [],
                     "affected_pct": impact.get("affected_pct"),
                     "rating_impact": impact.get("rating_impact")}
    return {
        "trigger": trigger,
        "mechanism": {"text": h.get("statement", ""), "evidence_ids": [e["id"] for e in items]},
        "symptom": symptom,
        "impact": impact_el,
    }


# ── complaint timeline ──────────────────────────────────────────────────

HOTFIX_DAYS = 14


def _day_key(value) -> str:
    return str(value)[:10]


def _daily(session: Session, product: str | None, start: datetime, end: datetime,
           extra=None) -> dict[str, dict]:
    """{day: {negative, one_star, total}} in ONE grouped query."""
    day = func.date(Review.created_at)
    stmt = (select(day, func.count(Review.id),
                   func.sum(case((Review.rating <= 2, 1), else_=0)),
                   func.sum(case((Review.rating == 1, 1), else_=0)))
            .where(Review.created_at >= start, Review.created_at <= end)
            .group_by(day))
    if product:
        stmt = stmt.where(Review.product == product)
    if extra is not None:
        stmt = stmt.where(extra)
    return {_day_key(d): {"total": int(t or 0), "negative": int(n or 0), "one_star": int(o or 0)}
            for d, t, n, o in session.execute(stmt).all()}


def _series(rows: dict[str, dict], first: date, days: int) -> list[dict]:
    out = []
    for i in range(days):
        d = (first + timedelta(days=i)).isoformat()
        out.append({"date": d, **rows.get(d, {"negative": 0, "one_star": 0, "total": 0})})
    return out


def release_markers(session: Session, product: str | None, start: datetime,
                    end: datetime) -> list[dict]:
    """[{version, date, kind}] for releases in [start, end]. kind is "hotfix"
    for a patch bump (same major.minor, higher patch) within HOTFIX_DAYS of the
    previous release, else "release". One query, reaching back HOTFIX_DAYS so
    the first release in the window has its predecessor."""
    lo = (start - timedelta(days=HOTFIX_DAYS)).replace(tzinfo=None)
    stmt = (select(Release.version, Release.released_at)
            .where(Release.released_at >= lo, Release.released_at <= end.replace(tzinfo=None))
            .order_by(Release.released_at, Release.id))
    if product:
        stmt = stmt.where(Release.product == product)
    out, prev = [], None
    start_day = start.date().isoformat()
    for version, at in session.execute(stmt).all():
        at = aware_utc(at)
        v = parse_version(version)
        kind = "release"
        if prev is not None and v is not None and prev[1] is not None:
            pv, pat = prev[1], prev[2]
            if v[:2] == pv[:2] and v[2] > pv[2] and (at - pat).days <= HOTFIX_DAYS:
                kind = "hotfix"
        if at.date().isoformat() >= start_day:
            out.append({"version": version, "date": at.date().isoformat(), "kind": kind})
        prev = (version, v, at)
    return out


def timeline(session: Session, product: str | None, days: int = 30,
             end: datetime | None = None, theme_terms: list[str] | None = None) -> dict:
    """Daily complaint series for the last `days` days ending at `end` (the
    product's latest review by default), release markers, and — given
    `theme_terms` — the same daily counts for reviews mentioning any of them."""
    from echolens.detector.detect import reference_now

    end = end or reference_now(session, product)
    end = aware_utc(end)
    first = end.date() - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=timezone.utc)
    # Naive bounds: the column is stored naive UTC on SQLite.
    lo, hi = start.replace(tzinfo=None), end.replace(tzinfo=None)
    out = {
        "product": product, "days": days, "start": first.isoformat(), "end": end.date().isoformat(),
        "series": _series(_daily(session, product, lo, hi), first, days),
        "releases": release_markers(session, product, start, end),
    }
    if theme_terms is not None:
        terms = [t.lower() for t in theme_terms if t][:4]
        match = or_(*[func.lower(Review.text).like(f"%{t}%") for t in terms]) if terms else None
        out["theme"] = {"terms": terms,
                        "series": _series(_daily(session, product, lo, hi, match), first, days)
                        if match is not None else []}
    return out


# ── live investigations ─────────────────────────────────────────────────

STEP_TEXT_MAX = 140


def _step_text(content: dict) -> str:
    text = (content.get("text") or content.get("code") or content.get("specialist")
            or content.get("error") or "")
    text = " ".join(str(text).split())
    return text if len(text) <= STEP_TEXT_MAX else text[:STEP_TEXT_MAX - 1] + "…"


def live_investigations(session: Session, product_id: int | None,
                        now: datetime | None = None) -> list[dict]:
    """Running cases and queued work, newest first. A fixed number of grouped
    queries (cases, step counts, latest steps, costs, queue), never one per case.

    Each row: {id, queue_id, status, title, started_at, elapsed_s, step_count,
    current_step: {kind, text ≤140 chars} | null, cost_usd_so_far}. Queued rows
    have id null and no steps until the orchestrator claims them. At most 50
    of each.
    """
    from echolens.cases import case_title
    from echolens.db.models import AnomalyEvent

    now = now or datetime.now(timezone.utc)
    stmt = select(Investigation).where(Investigation.status == "running").order_by(Investigation.id.desc())
    if product_id is not None:
        stmt = stmt.where(Investigation.product_id == product_id)
    running = session.scalars(stmt.limit(50)).all()
    ids = [i.id for i in running]
    counts: dict[int, tuple[int, int]] = {}
    latest: dict[int, tuple[str, dict]] = {}
    costs: dict[int, float] = {}
    anomalies: dict[int, AnomalyEvent] = {}
    if ids:
        counts = {i: (int(n), int(s)) for i, n, s in session.execute(
            select(TraceStep.investigation_id, func.count(TraceStep.id), func.max(TraceStep.seq))
            .where(TraceStep.investigation_id.in_(ids)).group_by(TraceStep.investigation_id)).all()}
        last = [(i, s) for i, (_, s) in counts.items()]
        if last:
            for i, kind, content in session.execute(
                    select(TraceStep.investigation_id, TraceStep.kind, TraceStep.content_json).where(
                        or_(*[(TraceStep.investigation_id == i) & (TraceStep.seq == s)
                              for i, s in last]))).all():
                latest[i] = (kind, content or {})
        costs = {i: float(c or 0) for i, c in session.execute(
            select(LLMCall.investigation_id, func.sum(LLMCall.cost))
            .where(LLMCall.investigation_id.in_(ids)).group_by(LLMCall.investigation_id)).all()}
        a_ids = [i.anomaly_id for i in running if i.anomaly_id]
        if a_ids:
            anomalies = {a.id: a for a in session.scalars(
                select(AnomalyEvent).where(AnomalyEvent.id.in_(a_ids))).all()}
        queued_titles = dict(session.execute(
            select(QueuedInvestigation.investigation_id, QueuedInvestigation.title)
            .where(QueuedInvestigation.investigation_id.in_(ids))).all())
    else:
        queued_titles = {}
    out = []
    for inv in running:
        started = aware_utc(inv.created_at)
        kind_content = latest.get(inv.id)
        out.append({
            "id": inv.id, "queue_id": None, "status": "running",
            "title": case_title(None, anomalies.get(inv.anomaly_id), queued_titles.get(inv.id)),
            "started_at": started.isoformat() if started else None,
            "elapsed_s": max(0, int((now - started).total_seconds())) if started else None,
            "step_count": counts.get(inv.id, (0, 0))[0],
            "current_step": ({"kind": kind_content[0], "text": _step_text(kind_content[1])}
                             if kind_content else None),
            "cost_usd_so_far": round(costs.get(inv.id, 0.0), 4),
        })
    q = select(QueuedInvestigation).where(
        QueuedInvestigation.status.in_(("queued", "running")),
        QueuedInvestigation.investigation_id.is_(None)).order_by(QueuedInvestigation.id.desc())
    if product_id is not None:
        q = q.where(QueuedInvestigation.product_id == product_id)
    for row in session.scalars(q.limit(50)).all():
        out.append({"id": None, "queue_id": row.id, "status": "queued",
                    "title": row.title or "Queued investigation",
                    "started_at": None, "elapsed_s": None, "step_count": 0,
                    "current_step": None, "cost_usd_so_far": 0.0})
    return out


# ── citation detail ─────────────────────────────────────────────────────

_QUOTED = re.compile(r"[\"“‘']([^\"”’']{6,200})[\"”’']")
_GITHUB_ISSUE = re.compile(r"^issue\s+([\w.-]+/[\w.-]+)#(\d+)$")


def prose_sentences(prose: str) -> list[str]:
    """The finding prose split the way the speculation guard splits it, so a
    claim_span index means the same sentence on both sides."""
    return [s.strip() for s in guards._WHOLE_SENTENCE.split(prose or "") if s.strip()]


def _url(source: str, ref: str) -> str | None:
    """A link only where the ref is enough to build a real one."""
    m = _GITHUB_ISSUE.match(ref or "")
    if source == "github" and m:
        return f"https://github.com/{m[1]}/issues/{m[2]}"
    return None


def _highlight(quotes: list[str], text: str) -> str | None:
    """The exact substring of `text` that the finding quotes, in the text's own
    casing, or None. Longest matching quote wins."""
    low = (text or "").lower()
    for q in sorted(quotes, key=len, reverse=True):
        at = low.find(q.lower().strip())
        if q.strip() and at >= 0:
            return text[at:at + len(q.strip())]
    return None


_ISSUE_REF = re.compile(r"^issue\s+(\S+)$")
# "release v3.2.0" from the tool, or the release page URL a stored exhibit keeps
# (…/releases/tag/v3.2.0). Missing the URL form left those exhibits undated.
_RELEASE_REF = re.compile(r"^(?:release\s+|https?://\S+/releases/tag/)v?([^\s/]+)$")


def _exhibit_meta(session: Session, evs: list, product: str | None) -> dict[str, dict]:
    """{evidence id: {date, rating}} — when each exhibit was written (a review,
    a post, an issue, a release) and a review's stars. One query per source
    kind that is actually cited; anything not found stays None."""
    from echolens.db.models import Issue, Post
    reviews = [e.ref for e in evs if e.source in guards.REVIEW_SOURCES]
    posts = [e.ref for e in evs if e.source not in guards.REVIEW_SOURCES
             and not _ISSUE_REF.match(e.ref or "") and not _RELEASE_REF.match(e.ref or "")]
    issues = [m[1] for e in evs if (m := _ISSUE_REF.match(e.ref or ""))]
    versions = [m[1] for e in evs if (m := _RELEASE_REF.match(e.ref or ""))]

    def scoped(stmt, model):
        return stmt.where(model.product == product) if product else stmt

    review_rows: dict[str, tuple] = {}
    if reviews:
        for ext, at, rating in session.execute(scoped(select(Review.ext_id, Review.created_at, Review.rating)
                                                      .where(Review.ext_id.in_(reviews)), Review)).all():
            review_rows[ext] = (at, rating)
    post_rows: dict[str, datetime] = {}
    if posts:
        post_rows = dict(session.execute(scoped(select(Post.ext_id, Post.created_at)
                                                .where(Post.ext_id.in_(posts)), Post)).all())
    issue_rows: dict[str, datetime] = {}
    if issues:
        for ext, at in session.execute(select(Issue.ext_id, Issue.created_at)
                                       .where(Issue.ext_id.in_(issues)).order_by(Issue.id)).all():
            issue_rows.setdefault(ext, at)
    release_rows: dict[str, datetime] = {}
    if versions:
        # Stored versions may or may not carry a leading "v"; key by the bare form.
        wanted = versions + [f"v{v}" for v in versions]
        for ver, at in session.execute(scoped(select(Release.version, Release.released_at)
                                              .where(Release.version.in_(wanted)), Release)).all():
            release_rows.setdefault(ver.lstrip("vV"), at)

    out: dict[str, dict] = {}
    for e in evs:
        at, rating = None, None
        if e.ref in review_rows and e.source in guards.REVIEW_SOURCES:
            at, rating = review_rows[e.ref]
        elif (m := _ISSUE_REF.match(e.ref or "")):
            at = issue_rows.get(m[1])
        elif (m := _RELEASE_REF.match(e.ref or "")):
            at = release_rows.get(m[1])
        else:
            at = post_rows.get(e.ref)
        out[e.eid] = {"date": _day_key(at) if at else None, "rating": rating}
    return out


def citations(session: Session, inv: Investigation, product: str | None) -> dict:
    """Two-way citation map for one case.

    {sentences: [finding prose sentences], citations: [{id, source, ref, quote,
    url, supports: [hypothesis ids], claim_spans: [sentence indexes citing it],
    highlight: substring of the full review text the finding quotes, or null,
    date: the day the source was written or released (or null), rating: a
    review's stars (or null)}]}.
    Three queries plus one for the quoted reviews' full text.
    """
    evs = session.scalars(select(EvidenceRow).where(
        EvidenceRow.investigation_id == inv.id).order_by(EvidenceRow.id)).all()
    hyps = session.scalars(select(HypothesisRow).where(HypothesisRow.investigation_id == inv.id)).all()
    finding = session.scalars(select(Finding).where(
        Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
    fj = (finding.json or {}) if finding else {}
    sentences = prose_sentences(fj.get("prose", ""))
    quotes = _QUOTED.findall(" ".join([fj.get("prose", "") or "", fj.get("summary", "") or ""]))

    full: dict[str, str] = {}
    review_refs = [e.ref for e in evs if e.source in guards.REVIEW_SOURCES]
    if quotes and review_refs:
        stmt = select(Review.ext_id, Review.text).where(Review.ext_id.in_(review_refs))
        if product:
            stmt = stmt.where(Review.product == product)
        full = dict(session.execute(stmt).all())

    meta = _exhibit_meta(session, evs, product)
    out = []
    for e in evs:
        supports = [h.hid for h in hyps if e.eid in ((h.json or {}).get("evidence_for") or [])]
        for hid in (e.json or {}).get("supports") or []:
            if hid not in supports:
                supports.append(hid)
        spans = [i for i, s in enumerate(sentences) if e.eid in guards.EVIDENCE_REF.findall(s)]
        out.append({
            "id": e.eid, "source": e.source, "ref": e.ref, "quote": e.snippet,
            "url": _url(e.source, e.ref), "supports": supports, "claim_spans": spans,
            "highlight": _highlight(quotes, full.get(e.ref) or e.snippet) if quotes else None,
            **meta[e.eid],
        })
    return {"investigation_id": inv.id, "sentences": sentences, "citations": out}
