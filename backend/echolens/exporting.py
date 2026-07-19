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
