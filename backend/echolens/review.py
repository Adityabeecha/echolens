"""Human review checkpoint (PRD §4.1, §9).

approve  → finding accepted, case closes as resolved, feedback recorded.
challenge(note) → feedback recorded, finding marked challenged, and the case is
re-opened: a fresh investigation on the same anomaly runs with the reviewer's
note injected as context, so the agent must address the objection before
concluding again.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent,
    Finding,
    Investigation,
    ReviewFeedback,
)
from echolens.llm.client import LLMClient


def approve(session: Session, finding: Finding, note: str = "", user_id: int | None = None) -> Finding:
    session.add(ReviewFeedback(finding_id=finding.id, action="approve", note=note, user_id=user_id))
    finding.status = "approved"
    inv = session.get(Investigation, finding.investigation_id)
    if inv is not None:
        inv.status = "resolved"
        inv.resolved_at = datetime.now(timezone.utc)
        anomaly = session.get(AnomalyEvent, inv.anomaly_id)
        if anomaly is not None:
            anomaly.status = "closed"
    session.flush()
    return finding


CHALLENGE_REASONS = {"wrong_cause", "weak_evidence", "wrong_severity", "already_knew"}


def challenge(session: Session, finding: Finding, note: str,
              llm: LLMClient | None = None, on_step=None,
              tier: str | None = None, user_id: int | None = None,
              reason: str | None = None) -> Investigation:
    """Record the challenge and re-open the investigation with the note injected.
    `reason` is a structured autopsy category (v5.0) that rolls up into the
    visible 'known weak spots' panel and future prompt guidance."""
    if not note.strip():
        raise ValueError("a challenge requires a note explaining what to reconsider")
    if reason is not None and reason not in CHALLENGE_REASONS:
        reason = None
    session.add(ReviewFeedback(finding_id=finding.id, action="challenge", note=note,
                               user_id=user_id, reason=reason))
    finding.status = "challenged"

    old_inv = session.get(Investigation, finding.investigation_id)
    anomaly = session.get(AnomalyEvent, old_inv.anomaly_id)
    anomaly.status = "investigating"
    session.flush()

    from echolens.investigator.graph import Investigator
    reopened = Investigator(
        session, anomaly, llm=llm, tier=tier or old_inv.budget_tier,
        opened_by="challenge", context_note=note,
        reopens_investigation_id=old_inv.id, on_step=on_step,
    ).run()
    return reopened
