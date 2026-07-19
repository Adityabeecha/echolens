"""Delivery (v4.0): meet the PM where they live. Push a finding's 5-line decision
summary to Slack (with approve/challenge buttons) and/or email, with a deep link
back to the case. Severity decides the channel — high pings instantly, low waits
for the digest — so the tool never cries wolf.

All network/SMTP calls are injectable so this is fully offline-testable.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.config import settings
from echolens.db.models import Finding, Investigation, Recommendation
from echolens.impact import decision_doc, severity
from echolens.logging import get_logger

log = get_logger("notify")


def deep_link(investigation_id: int) -> str | None:
    base = settings.app_base_url.rstrip("/")
    return f"{base}/#case/{investigation_id}" if base else None


def _finding_context(session: Session, finding: Finding) -> dict:
    fj = finding.json or {}
    inv = session.get(Investigation, finding.investigation_id)
    recs = session.scalars(select(Recommendation).where(
        Recommendation.finding_id == finding.id).order_by(Recommendation.rank)).all()
    impact = fj.get("impact", {})
    status = inv.status if inv else ""
    decision = decision_doc(fj, list(recs), impact, status)
    sev = severity(float(fj.get("confidence", 0.0)), impact)
    return {"fj": fj, "inv": inv, "impact": impact, "decision": decision,
            "severity": sev, "status": status}


def slack_blocks(finding: Finding, ctx: dict) -> dict:
    d, sev = ctx["decision"], ctx["severity"]
    link = deep_link(finding.investigation_id)
    actions = [
        {"type": "button", "text": {"type": "plain_text", "text": "Approve"},
         "style": "primary", "action_id": "echolens_approve", "value": f"approve:{finding.id}"},
        {"type": "button", "text": {"type": "plain_text", "text": "Challenge"},
         "action_id": "echolens_challenge", "value": f"challenge:{finding.id}"},
    ]
    if link:
        actions.append({"type": "button", "text": {"type": "plain_text", "text": "Open case"}, "url": link})
    return {"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": f"🔎 {d['whats_broken'][:140]}"}},
        {"type": "section", "text": {"type": "mrkdwn",
            "text": f"*How bad:* {d['how_bad']}\n*What to do:* {d['what_to_do']}"}},
        {"type": "context", "elements": [{"type": "mrkdwn",
            "text": f"confidence {ctx['fj'].get('confidence', 0):.2f} · severity *{sev['band']}* "
                    f"({sev['score']}) · case #{finding.investigation_id}"}]},
        {"type": "actions", "elements": actions},
    ]}


def email_text(finding: Finding, ctx: dict) -> tuple[str, str]:
    d = ctx["decision"]
    link = deep_link(finding.investigation_id)
    subject = f"[EchoLens] {d['whats_broken'][:120]}"
    body = (f"What's broken: {d['whats_broken']}\n"
            f"How bad: {d['how_bad']}\n"
            f"What to do: {d['what_to_do']}\n\n"
            f"Confidence: {ctx['fj'].get('confidence', 0):.2f} · severity: {ctx['severity']['band']}\n")
    if link:
        body += f"\nOpen the case: {link}\n"
    return subject, body


def _send_slack(payload: dict, post_fn=None) -> bool:
    url = settings.slack_webhook_url
    if not url:
        return False
    if post_fn is None:
        import httpx

        def post_fn(u, json):  # noqa: ANN001
            return httpx.post(u, json=json, timeout=15)
    resp = post_fn(url, payload)
    ok = getattr(resp, "status_code", 200) < 300
    if not ok:
        log.error("slack_send_failed", status=getattr(resp, "status_code", "?"))
    return ok


def _send_email(subject: str, body: str, send_fn=None) -> bool:
    if not settings.smtp_host or not settings.alert_email_to:
        return False
    if send_fn is not None:
        send_fn(subject, body)
        return True
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.alert_email_from or settings.smtp_user
    msg["To"] = settings.alert_email_to
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
        s.starttls()
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)
    return True


def notify_finding(session: Session, finding: Finding, *, force: bool = False,
                   slack_post_fn=None, email_send_fn=None) -> dict:
    """Route a finding to its channel by severity. Returns what was sent.
    `force` overrides the severity gate (used by the digest and manual sends)."""
    if not settings.alerts_enabled and not force:
        return {"routed": "disabled"}
    ctx = _finding_context(session, finding)
    sev = ctx["severity"]
    instant = force or sev["score"] >= settings.alert_instant_min_severity
    if not instant:
        return {"routed": "digest", "severity": sev}

    sent = []
    if _send_slack(slack_blocks(finding, ctx), post_fn=slack_post_fn):
        sent.append("slack")
    subject, body = email_text(finding, ctx)
    if _send_email(subject, body, send_fn=email_send_fn):
        sent.append("email")
    return {"routed": "instant", "severity": sev, "sent": sent,
            "decision": ctx["decision"]}


def parse_action_value(value: str) -> tuple[str, int]:
    """'approve:42' → ('approve', 42). Raises ValueError on anything else."""
    action, _, fid = (value or "").partition(":")
    if action not in ("approve", "challenge") or not fid.isdigit():
        raise ValueError(f"unrecognized action value '{value}'")
    return action, int(fid)
