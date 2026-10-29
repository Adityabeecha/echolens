"""Delivery (v4.0): meet the PM where they live. Push a finding's 5-line decision
summary to Slack (with approve/challenge buttons) and/or email, with a deep link
back to the case. Severity decides the channel — high pings instantly, low waits
for the digest — so the tool never cries wolf.

All network/SMTP calls are injectable so this is fully offline-testable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from echolens.config import settings
from echolens.db.models import (AnomalyEvent, Finding, Investigation, Recommendation,
                                SentAlert, TriageDecision)
from echolens.impact import decision_doc, severity
from echolens.logging import get_logger
from echolens.timeutil import aware_utc

log = get_logger("notify")


def deep_link(investigation_id: int) -> str | None:
    """A link straight to the case. The product isn't in the URL because the
    notification doesn't know it — the app restores product context on load."""
    base = settings.app_base_url.rstrip("/")
    return f"{base}/#/cases/{investigation_id}" if base else None


def _finding_context(session: Session, finding: Finding) -> dict:
    fj = finding.json or {}
    inv = session.get(Investigation, finding.investigation_id)
    recs = session.scalars(select(Recommendation).where(
        Recommendation.finding_id == finding.id).order_by(Recommendation.rank)).all()
    impact = fj.get("impact", {})
    status = inv.status if inv else ""
    from echolens.exporting import _numbers
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv is not None and inv.anomaly_id else None
    decision = decision_doc(fj, list(recs), impact, status, _numbers(session, inv, finding, anomaly))
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
        return send_fn(subject, body) is not False
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


def _incident_contexts(session: Session, findings: list[Finding], *,
                       finding_window_end: datetime | None = None) -> list[dict]:
    """Use detector components plus persisted triage merges, at every status.

    Waiting groups intentionally exclude investigated/merged signals; alerts
    need those members to preserve the incident shown when it was triaged.
    """
    from echolens.cases import _headline
    from echolens.detector.incidents import group
    from echolens.textkit import clean_headline

    products = {f.product_id for f in findings}
    out = []
    for product_id in sorted(products, key=lambda p: -1 if p is None else p):
        anomalies = list(session.scalars(select(AnomalyEvent).where(
            AnomalyEvent.product_id == product_id)).all())
        by_id = {a.id: a for a in anomalies}
        components = group(anomalies)
        parent = {a.id: a.id for a in anomalies}

        def root(aid):
            while parent[aid] != aid:
                parent[aid] = parent[parent[aid]]
                aid = parent[aid]
            return aid

        def union(aid, target):
            if aid in parent and target in parent:
                parent[root(aid)] = root(target)

        for members in components:
            for member in members[1:]:
                union(member.id, members[0].id)
        for anomaly in anomalies:
            union(anomaly.id, anomaly.merged_into_id)
        latest = {}
        if by_id:
            for decision in session.scalars(select(TriageDecision).where(
                    TriageDecision.anomaly_id.in_(by_id)).order_by(TriageDecision.id)).all():
                latest[decision.anomaly_id] = decision
        for decision in latest.values():
            if decision.decision == "merge":
                union(decision.anomaly_id, decision.merge_into_anomaly_id)
        groups = {}
        for anomaly in anomalies:
            groups.setdefault(root(anomaly.id), []).append(anomaly)
        selected = [f for f in findings if f.product_id == product_id]
        selected_ids = {f.id for f in selected}
        known = selected
        if finding_window_end is not None:
            # Instant sends summarize the currently known 24h snapshot. Keep
            # an explicitly selected historical finding for manual delivery.
            known = list(session.scalars(select(Finding).where(
                Finding.product_id == product_id,
                or_(Finding.id.in_(selected_ids),
                    (Finding.created_at > finding_window_end - timedelta(hours=24))
                    & (Finding.created_at <= finding_window_end)))).all())
        invs = {i.id: i for i in session.scalars(select(Investigation).where(
            Investigation.product_id == product_id)).all()}
        # Legacy unscoped cases may still back scoped findings. Only load the
        # snapshot case ids, and only accept anomalies in this product below.
        for f in known:
            if f.investigation_id not in invs:
                inv = session.get(Investigation, f.investigation_id)
                if inv and inv.product_id in (None, product_id):
                    invs[inv.id] = inv
        buckets = {}
        for f in known:
            inv = invs.get(f.investigation_id)
            aid = inv.anomaly_id if inv else None
            key = ("incident", root(aid)) if aid in by_id else ("case", f.investigation_id)
            buckets.setdefault(key, []).append(f)
        for (kind, ident), related_findings in buckets.items():
            if not selected_ids.intersection(f.id for f in related_findings):
                continue
            members = groups[ident] if kind == "incident" else []
            lead = None
            if members:
                # Explicit merge edges can join detector-disjoint components.
                # Choose the strongest component lead across the whole union.
                lead = max((g[0] for g in group(members)), key=lambda a: (a.z or 0., -a.id))
            lead_findings = [f for f in related_findings
                             if lead and invs.get(f.investigation_id)
                             and invs[f.investigation_id].anomaly_id == lead.id]
            representative = max(lead_findings or related_findings, key=lambda f: (
                aware_utc(f.created_at) or datetime.min.replace(tzinfo=timezone.utc), f.id))
            out.append({"key": f"{product_id}:{kind}:{min(a.id for a in members) if members else ident}",
                        "product_id": product_id, "members": [a.id for a in members],
                        "finding_ids": [f.id for f in related_findings], "finding": representative,
                        "title": _headline(lead) if lead else clean_headline(representative.summary),
                        "z": max((a.z or 0. for a in members), default=0.),
                        "member_count": len(members) or 1})
    return out


def _incident_line(incident: dict) -> str:
    related = len(incident["finding_ids"]) - 1
    link = deep_link(incident["finding"].investigation_id)
    title = " ".join(incident["title"].splitlines())[:240]
    count = incident["member_count"]
    line = f"{title} | {count} signal{'s' if count != 1 else ''} | strongest z={incident['z']:g}"
    if related:
        line += f" | +{related} related finding{'s' if related != 1 else ''}"
    return line + (f" | {link}" if link else "")



def _already_sent(session: Session, incident: dict, channel: str, kind: str,
                  now: datetime) -> bool:
    rows = session.scalars(select(SentAlert).where(
        SentAlert.product_id == incident["product_id"], SentAlert.channel == channel,
        SentAlert.window_start > now - timedelta(hours=24),
        SentAlert.window_start <= now)).all()
    members = set(incident["members"])
    return any(row.incident_key == incident["key"] or members.intersection(row.member_ids)
               or set(incident["finding_ids"]).intersection(row.finding_ids) for row in rows)


def _record_sent(session: Session, incident: dict, channel: str, kind: str,
                 now: datetime) -> None:
    session.add(SentAlert(product_id=incident["product_id"], incident_key=incident["key"],
                          window_start=now, channel=channel, kind=kind,
                          member_ids=incident["members"], finding_ids=incident["finding_ids"]))
    session.flush()


def _deliver(channel: str, payload, slack_post_fn, email_send_fn) -> bool:
    try:
        if channel == "slack":
            return _send_slack(payload, post_fn=slack_post_fn)
        return _send_email(*payload, send_fn=email_send_fn)
    except Exception as exc:
        # Delivery failure must neither suppress a retry nor undo the other
        # channel's successful delivery record. Avoid logging payload/secrets.
        log.error("alert_delivery_failed", channel=channel, error_type=type(exc).__name__)
        return False


def notify_finding(session: Session, finding: Finding, *, force: bool = False,
                   slack_post_fn=None, email_send_fn=None, as_of: datetime | None = None) -> dict:
    """Route by existing severity gate, then send once per incident/channel/24h.

    Delivery records are flushed in the caller's transaction; caller commits.
    Force bypasses the severity gate, while keeping incident deduplication.
    """
    # Settings → Integrations can override the config defaults.
    from echolens.alert_settings import effective_alerts
    alerts = effective_alerts(session)
    if not alerts["alerts_enabled"] and not force:
        return {"routed": "disabled"}
    ctx = _finding_context(session, finding)
    sev = ctx["severity"]
    if not (force or sev["score"] >= alerts["alert_instant_min_severity"]):
        return {"routed": "digest", "severity": sev}
    now = aware_utc(as_of) or datetime.now(timezone.utc)
    incident = _incident_contexts(session, [finding], finding_window_end=now)[0]
    representative = incident["finding"]
    delivery_ctx = _finding_context(session, representative)
    line = _incident_line(incident)
    payload = slack_blocks(representative, delivery_ctx)
    payload["blocks"][0]["text"]["text"] = incident["title"][:140]
    payload["blocks"].insert(1, {"type": "section", "text": {"type": "mrkdwn", "text": line}})
    _, body = email_text(representative, delivery_ctx)
    email = (f"[EchoLens] {incident['title'][:120]}", line + "\n\n" + body)
    sent = []
    for channel, content in (("slack", payload), ("email", email)):
        if not _already_sent(session, incident, channel, "instant", now):
            if _deliver(channel, content, slack_post_fn, email_send_fn):
                _record_sent(session, incident, channel, "instant", now)
                sent.append(channel)
    return {"routed": "instant", "severity": sev, "sent": sent,
            "decision": ctx["decision"]}


def notify_digest(session: Session, findings: list[Finding], *, slack_post_fn=None,
                  email_send_fn=None, as_of: datetime | None = None) -> dict:
    """Deliver one digest line per incident from the caller's authorized selection.

    Select and authorize product/time scope before calling. Signal grouping
    includes persisted triage merges at every status; finding counts and case
    links use only the supplied authorized selection. Persist successes in the
    caller's transaction.
    """
    if not findings:
        return {"sent": False, "count": 0, "finding_count": 0, "sent_channels": [],
                "suppressed": 0, "reason": "no findings in window"}
    now = aware_utc(as_of) or datetime.now(timezone.utc)
    incidents = _incident_contexts(session, findings)
    sent_channels, delivered = [], set()
    for channel in ("slack", "email"):
        pending = [i for i in incidents if not _already_sent(session, i, channel, "digest", now)]
        if not pending:
            continue
        # Keep each Slack section bounded while retaining every incident. A
        # failed page remains retryable; successful pages are not sent again.
        batches, batch, length = [], [], 0
        for incident in pending:
            size = len(_incident_line(incident)) + 1
            if channel == "slack" and batch and length + size > 2800:
                batches.append(batch); batch, length = [], 0
            batch.append(incident); length += size
        if batch:
            batches.append(batch)
        for batch in batches:
            title = f"EchoLens digest | {len(batch)} incident{'s' if len(batch) != 1 else ''}"
            lines = "\n".join(_incident_line(i) for i in batch)
            content = {"blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": title}},
                {"type": "section", "text": {"type": "mrkdwn", "text": lines}},
            ]} if channel == "slack" else (title, lines)
            if _deliver(channel, content, slack_post_fn, email_send_fn):
                if channel not in sent_channels:
                    sent_channels.append(channel)
                for incident in batch:
                    _record_sent(session, incident, channel, "digest", now)
                    delivered.add(incident["key"])
    suppressed = sum(all(_already_sent(session, i, c, "digest", now)
                         for c in ("slack", "email")) and i["key"] not in delivered for i in incidents)
    return {"sent": bool(sent_channels), "count": len(incidents), "finding_count": len(findings),
            "sent_channels": sent_channels, "suppressed": suppressed}


def parse_action_value(value: str) -> tuple[str, int]:
    """'approve:42' → ('approve', 42). Raises ValueError on anything else."""
    action, _, fid = (value or "").partition(":")
    if action not in ("approve", "challenge") or not fid.isdigit():
        raise ValueError(f"unrecognized action value '{value}'")
    return action, int(fid)
