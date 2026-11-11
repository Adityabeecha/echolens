"""Error tracking. Off unless SENTRY_DSN is set.

Outages used to surface as a user's screenshot: the logs existed, but nobody
reads JSON logs on a free container until something is already broken. With a
DSN, unhandled exceptions AND every `log.error(...)` reach Sentry — most of the
app's failures are caught and logged rather than raised, so capturing only
crashes would miss them.
"""
from __future__ import annotations

import os

from echolens.config import settings

_active = False


def init_sentry(process: str = "api") -> bool:
    """Start Sentry once per process. Returns whether it is on."""
    global _active
    if _active or not settings.sentry_dsn:
        return _active
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.echolens_env,
        # Northflank exposes the built commit; it groups errors by deploy.
        release=os.getenv("NF_GIT_SHA") or os.getenv("SENTRY_RELEASE") or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # Review text, emails and cookies stay out of error reports.
        send_default_pii=False,
    )
    sentry_sdk.set_tag("process", process)
    _active = True
    return True


def is_active() -> bool:
    return _active


def forward_errors(_logger, method: str, event_dict: dict) -> dict:
    """structlog processor: send error-level log lines to Sentry as events.

    Grouped by the event name, so "collector_fetch_failed" is one issue with a
    count rather than a new issue per message text."""
    if _active and method in ("error", "critical", "exception"):
        import sentry_sdk

        event = str(event_dict.get("event", "error"))
        with sentry_sdk.new_scope() as scope:
            scope.fingerprint = [event]
            for key, value in event_dict.items():
                if key not in ("event", "timestamp", "level"):
                    scope.set_extra(key, value if isinstance(value, (int, float, bool)) else str(value)[:2000])
            sentry_sdk.capture_message(event, level="error")
    return event_dict
