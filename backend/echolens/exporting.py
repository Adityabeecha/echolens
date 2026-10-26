"""Ticket-ready export (v4.0): turn a finding into a formatted issue an engineer
can act on — copy-to-clipboard markdown, and the payload for native GitHub issue
creation. The evidence chain travels WITH the ticket; a fix never leaves the
trust chain behind.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent,
    EvidenceRow,
    Finding,
    Investigation,
    Recommendation,
)
from echolens.impact import decision_doc, impact_line


def _evidence_lines(session: Session, inv_id: int, repo: str | None) -> list[str]:
    lines = []
    for e in session.scalars(select(EvidenceRow).where(EvidenceRow.investigation_id == inv_id)).all():
        ref = e.ref
        if e.source == "github" and repo and ref.startswith("#"):
            ref = f"[{ref}](https://github.com/{repo}/issues/{ref.lstrip('#')})"
        lines.append(f"- `{e.eid}` · **{e.source}** {ref} — “{e.snippet}”")
    return lines


def finding_ticket(session: Session, finding: Finding, repo: str | None = None,
                   deep_link: str | None = None) -> dict:
    """Build {title, body} markdown for a finding. `repo` (owner/name) turns
    GitHub evidence refs into links; `deep_link` points back to the case."""
    fj = finding.json or {}
    inv = session.get(Investigation, finding.investigation_id)
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv else None
    recs = session.scalars(select(Recommendation).where(
        Recommendation.finding_id == finding.id).order_by(Recommendation.rank)).all()
    impact = fj.get("impact", {})
    decision = decision_doc(fj, list(recs), impact, inv.status if inv else "")

    title = f"[EchoLens] {fj.get('summary') or 'Finding'}"

    top = recs[0] if recs else None
    acceptance = []
    if top is not None:
        acceptance.append(f"- [ ] {top.action}")
    acceptance.append("- [ ] Root cause above is addressed and the negative-review trend reverses")
    if impact.get("blast_radius", {}).get("top_cohort"):
        acceptance.append(f"- [ ] Verified on {impact['blast_radius']['top_cohort']}")

    body = [
        "### What's broken",
        decision["whats_broken"],
        "",
        "### How bad",
        impact_line(impact),
        "",
        "### Root cause",
        fj.get("prose", "").strip() or "(see evidence)",
        "",
        "### Recommended actions",
    ]
    if recs:
        body += [f"{r.rank}. **{r.action}** — {r.impact} impact / {r.effort} effort" for r in recs]
    else:
        body.append("_No confirmed action yet._")
    body += ["", "### Acceptance criteria", *acceptance, "", "### Evidence"]
    ev = _evidence_lines(session, finding.investigation_id, repo)
    body += ev or ["_No evidence rows._"]
    body += ["",
             f"_Confidence: {fj.get('confidence', 0):.2f}"
             + (f" · anomaly: {anomaly.description}" if anomaly else "") + "_"]
    if deep_link:
        body.append(f"_Full case: {deep_link}_")

    return {"title": title, "body": "\n".join(body)}


EVIDENCE_HEADING = "### Evidence"


def apply_ticket_edits(ticket: dict, title: str | None = None, body: str | None = None) -> dict:
    """A person's edits to the generated ticket, without losing the proof:
    an edited body that dropped the evidence section gets the generated one
    appended, so every exhibit is always attached."""
    out = dict(ticket)
    if title and title.strip():
        out["title"] = title.strip()
    if body and body.strip():
        edited = body.strip()
        generated = ticket.get("body") or ""
        at = generated.find(EVIDENCE_HEADING)
        if EVIDENCE_HEADING not in edited and at >= 0:
            edited = edited + "\n\n" + generated[at:]
        out["body"] = edited
    return out


# ── v15: the shareable brief ────────────────────────────────────────────
#
# The ticket above is for an engineer and carries the whole evidence chain.
# This is for everyone else — a Slack thread, a Notion page, a read-only link —
# so it says what a person outside the tool needs and nothing they would have to
# decode: no evidence ids, no hypothesis labels, no confidence decimals, no
# status enums.

# Channels where the quote is a user speaking, ranked first in the brief.
_USER_VOICE = ("play_store", "app_store", "chrome_web_store", "csv", "csv_reviews",
               "in_app", "support", "zendesk", "forum", "discord", "reddit",
               "hacker_news", "stack_overflow")
_SOURCE_NAMES = {
    "play_store": "Play Store review", "app_store": "App Store review",
    "chrome_web_store": "Chrome Web Store review", "csv": "Imported review",
    "csv_reviews": "Imported review", "in_app": "In-app feedback",
    "support": "Support ticket", "zendesk": "Support ticket", "forum": "Community forum",
    "discord": "Discord", "reddit": "Reddit", "hacker_news": "Hacker News",
    "stack_overflow": "Stack Overflow", "github": "GitHub issue",
    "release_notes": "Release notes",
}
_LEVEL = {"LOW": "low", "MED": "medium", "HIGH": "high"}
BRIEF_QUOTES = 3


def _plain(text: str) -> str:
    """Prose with the internal scaffolding removed: [ev_001] citations and
    bare hypothesis labels mean nothing outside the app."""
    import re
    text = re.sub(r"\s*\[ev_\d+\]", "", text or "")
    text = re.sub(r"\(\s*(?:H\d+[\s,]*)+\)", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def share_brief(session: Session, finding: Finding, link: str | None = None) -> dict:
    """{headline, impact, quotes, actions, markdown} for one finding.

    Quotes come ONLY from this finding's own investigation, and only when that
    investigation belongs to the same product as the finding — a brief that can
    be posted outside the app must never carry another product's users' words.
    Evidence a reviewer struck is left out.
    """
    from echolens.review import rejected_eids

    fj = finding.json or {}
    inv = session.get(Investigation, finding.investigation_id)
    recs = session.scalars(select(Recommendation).where(
        Recommendation.finding_id == finding.id).order_by(Recommendation.rank)).all()
    impact = fj.get("impact", {}) or {}

    quotes: list[dict] = []
    # The case's owner, resolved the way _owned does for legacy rows (via the
    # anomaly) — a NULL is not a wildcard.
    owner = None
    if inv is not None:
        owner = inv.product_id
        if owner is None and inv.anomaly_id:
            anomaly = session.get(AnomalyEvent, inv.anomaly_id)
            owner = anomaly.product_id if anomaly else None
    same_product = inv is not None and owner == finding.product_id
    if same_product:
        struck = rejected_eids(finding)
        rows = [e for e in session.scalars(select(EvidenceRow).where(
            EvidenceRow.investigation_id == finding.investigation_id)).all()
            if e.eid not in struck and (e.snippet or "").strip()
            and not (e.json or {}).get("contradicts")]
        # Quotes behind the proven cause first, then user voices before trackers.
        cited = set()
        hid = fj.get("supported_hypothesis")
        for e in rows:
            if hid and hid in ((e.json or {}).get("supports") or []):
                cited.add(e.eid)
        rows.sort(key=lambda e: (e.eid not in cited,
                                 e.source not in _USER_VOICE, e.eid))
        seen: set[str] = set()
        for e in rows:
            text = " ".join(e.snippet.split())
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            quotes.append({"text": text,
                           "source": _SOURCE_NAMES.get(e.source, e.source.replace("_", " ").title())})
            if len(quotes) >= BRIEF_QUOTES:
                break

    headline = (finding.summary or fj.get("summary") or "Finding").strip()
    how_bad = impact_line(impact)
    why = _plain(fj.get("prose", ""))
    actions = [{"action": r.action.strip(),
                "impact": _LEVEL.get((r.impact or "").upper(), (r.impact or "").lower()),
                "effort": _LEVEL.get((r.effort or "").upper(), (r.effort or "").lower())}
               for r in recs if (r.action or "").strip()]

    md = [f"*{headline}*", "", f"*How bad:* {how_bad}"]
    if why and why != headline:
        md += ["", why]
    if quotes:
        md += ["", "*What users are saying:*"]
        md += [f"> “{q['text']}” — {q['source']}" for q in quotes]
    md += ["", "*Recommended actions:*"]
    if actions:
        md += [f"{i}. {a['action']} ({a['impact']} impact, {a['effort']} effort)"
               for i, a in enumerate(actions, start=1)]
    else:
        md.append("No action agreed yet.")
    if link:
        md += ["", f"Full brief: {link}"]

    return {"headline": headline, "impact": how_bad, "why": why, "quotes": quotes,
            "actions": actions, "markdown": "\n".join(md)}


# ── v16: a feature-request spec as a ticket ─────────────────────────────


def request_ticket(spec: dict, deep_link: str | None = None) -> dict:
    """{title, body} for a spec from prd.build_spec. The body is the spec as the
    PM read it, minus its H1 — the title already says it."""
    lines = (spec.get("markdown") or "").splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if deep_link:
        body += f"\n\n_Filed from EchoLens: {deep_link}_"
    return {"title": f"[EchoLens] Spec: {spec.get('title') or 'Feature request'}", "body": body}
