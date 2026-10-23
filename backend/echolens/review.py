"""Human review checkpoint (PRD §4.1, §9).

approve  → finding accepted, case closes as resolved, feedback recorded.
challenge(note) → feedback recorded, finding marked challenged, and the case is
re-opened: a fresh investigation on the same anomaly runs with the reviewer's
note injected as context, so the agent must address the objection before
concluding again.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent,
    EvidenceRow,
    Finding,
    FindingDecision,
    HypothesisRow,
    Investigation,
    Recommendation,
    ReviewFeedback,
)
from echolens.llm.client import LLMClient
from echolens.timeutil import aware_utc


def approve(session: Session, finding: Finding, note: str = "", user_id: int | None = None) -> Finding:
    session.add(ReviewFeedback(finding_id=finding.id, action="approve", note=note, user_id=user_id))
    finding.status = "approved"
    # A fresh approval is the re-review a struck-evidence flag asked for (v15).
    if (finding.json or {}).get("needs_review"):
        finding.json = {k: v for k, v in finding.json.items() if k != "needs_review"}
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


def record_challenge(session: Session, finding: Finding, note: str,
                     reason: str | None = None, user_id: int | None = None,
                     tier: str | None = None) -> Investigation:
    """The SYNCHRONOUS part of a challenge: record the feedback, mark the finding
    challenged, and create the re-opened investigation ROW (running, not yet
    executed). Returns it so the API can respond immediately and run the loop in
    the background — a full investigation must not block the HTTP request."""
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
    new_inv = Investigation(anomaly_id=anomaly.id, status="running", opened_by="challenge",
                            budget_tier=tier or old_inv.budget_tier, budget_json={},
                            reopens_investigation_id=old_inv.id,
                            product_id=old_inv.product_id or anomaly.product_id)
    session.add(new_inv)
    session.flush()
    return new_inv


def challenge(session: Session, finding: Finding, note: str,
              llm: LLMClient | None = None, on_step=None,
              tier: str | None = None, user_id: int | None = None,
              reason: str | None = None) -> Investigation:
    """Record the challenge AND run the re-investigation synchronously (used by
    tests and off-request background workers, never inside a request handler)."""
    new_inv = record_challenge(session, finding, note, reason=reason, user_id=user_id, tier=tier)
    anomaly = session.get(AnomalyEvent, new_inv.anomaly_id)
    from echolens.investigator.graph import Investigator
    return Investigator(
        session, anomaly, llm=llm, tier=new_inv.budget_tier,
        opened_by="challenge", context_note=note,
        reopens_investigation_id=new_inv.reopens_investigation_id, on_step=on_step,
        existing_investigation=new_inv,
    ).run()


# ── v15: partial challenge ──────────────────────────────────────────────
#
# A full Challenge throws the whole case away and starts again. Most
# disagreements are smaller than that: one quote that doesn't say what the
# finding claims, or an effort estimate that is obviously off. These record the
# objection against the ONE item, as ReviewFeedback so Calibration counts it,
# without re-opening anything.

PARTIAL_REASONS = CHALLENGE_REASONS | {"rec_estimate_off"}
REC_LEVELS = ("LOW", "MED", "HIGH")


def _supported_hypothesis(session: Session, finding: Finding) -> dict | None:
    hid = (finding.json or {}).get("supported_hypothesis")
    if not hid:
        return None
    row = session.scalars(select(HypothesisRow).where(
        HypothesisRow.investigation_id == finding.investigation_id,
        HypothesisRow.hid == hid)).first()
    if row is None:
        return None
    return {"id": row.hid, "statement": row.statement, "confidence": row.confidence,
            "status": row.status, **(row.json or {})}


def rejected_eids(finding: Finding) -> set[str]:
    return {r.get("eid") for r in (finding.json or {}).get("rejected_evidence", []) or []}


def reject_evidence(session: Session, finding: Finding, eid: str, note: str = "",
                    reason: str | None = None, user_id: int | None = None) -> dict:
    """Strike one evidence item from a finding and re-run the two-source rule.

    The rule is guards.two_source_rule itself, on the evidence that REMAINS —
    not a re-implementation — so a struck quote is judged by exactly the bar
    the finding was concluded under. If the bar no longer holds, the finding is
    flagged as needing review and an approval it carried is withdrawn: an
    approval of a claim whose proof just shrank is not an approval of what is
    left.
    """
    from echolens.investigator import guards

    row = session.scalars(select(EvidenceRow).where(
        EvidenceRow.investigation_id == finding.investigation_id,
        EvidenceRow.eid == eid)).first()
    if row is None:
        raise LookupError(f"no evidence {eid} on this finding")
    if eid in rejected_eids(finding):
        raise ValueError(f"{eid} has already been rejected")
    if reason not in PARTIAL_REASONS:
        reason = "weak_evidence"

    now = datetime.now(timezone.utc)
    session.add(ReviewFeedback(finding_id=finding.id, action="reject_evidence",
                               note=f"{eid}: {note}".strip().rstrip(":"),
                               user_id=user_id, reason=reason))
    row.json = {**(row.json or {}), "rejected": {"at": now.isoformat(), "user_id": user_id,
                                                 "note": note}}

    struck = rejected_eids(finding) | {eid}
    remaining = [{"id": e.eid, "source": e.source, "snippet": e.snippet, **(e.json or {})}
                 for e in session.scalars(select(EvidenceRow).where(
                     EvidenceRow.investigation_id == finding.investigation_id)).all()
                 if e.eid not in struck]
    hyp = _supported_hypothesis(session, finding)
    meets: bool | None = None
    message = (f"{eid} was struck from the record. This finding didn't name a proven "
               "cause, so there was no two-source claim to re-check.")
    if hyp is not None:
        hyp = {**hyp, "evidence_for": [x for x in hyp.get("evidence_for", []) if x not in struck]}
        meets = guards.two_source_rule(hyp, remaining)
        message = (f"{eid} was struck. The finding still has at least two independent "
                   "sources behind it, so it stands." if meets else
                   f"{eid} was struck, and without it the finding no longer has two "
                   "independent sources agreeing. It needs review again before anyone "
                   "acts on it.")

    fj = dict(finding.json or {})
    fj["rejected_evidence"] = [*(fj.get("rejected_evidence") or []),
                               {"eid": eid, "user_id": user_id, "at": now.isoformat(),
                                "note": note}]
    if meets is False:
        fj["needs_review"] = {"reason": message, "at": now.isoformat(), "eid": eid}
        if finding.status == "approved":
            finding.status = "draft"
    finding.json = fj
    session.flush()
    return {"eid": eid, "two_source_ok": meets, "needs_review": meets is False,
            "message": message, "remaining_evidence": len(remaining)}


def edit_recommendation(session: Session, finding: Finding, rank: int, *,
                        effort: str | None = None, impact: str | None = None,
                        note: str = "", user_id: int | None = None) -> Recommendation:
    """Correct one recommendation's effort/impact without touching the finding."""
    rec = session.scalars(select(Recommendation).where(
        Recommendation.finding_id == finding.id, Recommendation.rank == rank)).first()
    if rec is None:
        raise LookupError(f"no recommendation #{rank} on this finding")
    changes = []
    for field, value in (("effort", effort), ("impact", impact)):
        if value is None:
            continue
        value = value.strip().upper()
        if value not in REC_LEVELS:
            raise ValueError(f"{field} must be one of {', '.join(REC_LEVELS)}")
        old = getattr(rec, field)
        if old != value:
            changes.append(f"{field} {old}→{value}")
            setattr(rec, field, value)
    if not changes:
        raise ValueError("nothing changed")
    text = f"#{rank}: {', '.join(changes)}" + (f" — {note.strip()}" if note.strip() else "")
    session.add(ReviewFeedback(finding_id=finding.id, action="edit_rec", note=text,
                               user_id=user_id, reason="rec_estimate_off"))
    session.flush()
    return rec


# ── v15: product decisions ──────────────────────────────────────────────

DECISIONS = ("fix_now", "park", "wont_fix", "cleared")


def latest_decision(session: Session, finding_id: int) -> FindingDecision | None:
    return session.scalars(select(FindingDecision).where(
        FindingDecision.finding_id == finding_id).order_by(FindingDecision.id.desc())).first()


def latest_decisions(session: Session, finding_ids: list[int]) -> dict[int, FindingDecision]:
    """Bulk form, for lists: {finding_id: decision in force}. A `cleared` row
    counts as no decision."""
    out: dict[int, FindingDecision] = {}
    if not finding_ids:
        return out
    for d in session.scalars(select(FindingDecision).where(
            FindingDecision.finding_id.in_(finding_ids)).order_by(FindingDecision.id)).all():
        out[d.finding_id] = d          # ascending: last wins
    return {fid: d for fid, d in out.items() if d.decision != "cleared"}


def decision_hides(decision: FindingDecision | None, now: datetime | None = None) -> bool:
    """Should this decision take a finding OUT of the open-problem lists?

    won't fix: always — the team decided. parked: until its revisit date, then
    it comes back on its own (no date = parked indefinitely). fix now: never.
    """
    if decision is None:
        return False
    if decision.decision == "wont_fix":
        return True
    if decision.decision == "park":
        if decision.revisit_by is None:
            return True
        now = now or datetime.now(timezone.utc)
        return aware_utc(decision.revisit_by) > now
    return False


def decision_dict(decision: FindingDecision | None, now: datetime | None = None) -> dict | None:
    if decision is None or decision.decision == "cleared":
        return None
    return {"decision": decision.decision,
            "revisit_by": aware_utc(decision.revisit_by).date().isoformat()
            if decision.revisit_by else None,
            "reason": decision.reason or "", "user_id": decision.user_id,
            "at": aware_utc(decision.created_at).isoformat() if decision.created_at else None,
            "hidden": decision_hides(decision, now)}


def decide(session: Session, finding: Finding, decision: str, *,
           revisit_by: datetime | None = None, reason: str = "",
           user_id: int | None = None) -> FindingDecision:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    reason = (reason or "").strip()
    if decision == "wont_fix" and not reason:
        raise ValueError("won't fix needs a reason (for example: by design)")
    if decision != "park":
        revisit_by = None
    row = FindingDecision(finding_id=finding.id, investigation_id=finding.investigation_id,
                          product_id=finding.product_id, decision=decision,
                          revisit_by=revisit_by, reason=reason, user_id=user_id)
    session.add(row)
    session.flush()
    return row
