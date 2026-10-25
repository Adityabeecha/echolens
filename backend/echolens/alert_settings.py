"""Alert settings an admin can change in Settings → Integrations.

The defaults are the deployment's config (ALERTS_ENABLED,
ALERT_INSTANT_MIN_SEVERITY, AUTO_CREATE_ISSUE_ON_APPROVE). An admin's choice is
stored as one Setting row and wins over them; with no row, behaviour is exactly
the config's. Channels themselves (the Slack webhook, the GitHub token) stay
server-side secrets: this only says whether they are connected.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from echolens.config import settings
from echolens.db.models import Setting

KEY = "alerts"
FIELDS = ("alerts_enabled", "alert_instant_min_severity", "auto_create_issue_on_approve")


def effective_alerts(session: Session) -> dict:
    """{alerts_enabled, alert_instant_min_severity, auto_create_issue_on_approve}."""
    row = session.get(Setting, KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    out = {k: getattr(settings, k) for k in FIELDS}
    for k in FIELDS:
        if k in stored and stored[k] is not None:
            out[k] = stored[k]
    out["alerts_enabled"] = bool(out["alerts_enabled"])
    out["auto_create_issue_on_approve"] = bool(out["auto_create_issue_on_approve"])
    out["alert_instant_min_severity"] = float(out["alert_instant_min_severity"])
    return out


def save_alerts(session: Session, changes: dict) -> dict:
    """Merge `changes` (only FIELDS, None = leave) into the stored row."""
    row = session.get(Setting, KEY)
    if row is None:
        row = Setting(key=KEY, value={})
        session.add(row)
    value = dict(row.value or {})
    for k in FIELDS:
        if changes.get(k) is not None:
            value[k] = changes[k]
    row.value = value
    session.flush()
    return effective_alerts(session)


def channels() -> dict:
    """Which channels the server has credentials for. Booleans only."""
    from echolens.integrations.trackers import configured_trackers
    return {"slack_connected": bool(settings.slack_webhook_url),
            "github_connected": bool(configured_trackers().get("github"))}
