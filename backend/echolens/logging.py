"""Structured logging (v1.0). JSON logs with per-investigation correlation IDs.

Uses structlog if available; degrades to stdlib logging otherwise so importing
this module never hard-fails. Bind a correlation id with `bind_investigation(id)`
so every log line inside one investigation is greppable.
"""
from __future__ import annotations

import logging
import os

try:
    import structlog

    _HAVE_STRUCTLOG = True
except Exception:  # pragma: no cover
    _HAVE_STRUCTLOG = False

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True
    level = os.getenv("ECHOLENS_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(format="%(message)s", level=level)
    if _HAVE_STRUCTLOG:
        renderer = (
            structlog.processors.JSONRenderer()
            if os.getenv("ECHOLENS_LOG_JSON", "1") == "1"
            else structlog.dev.ConsoleRenderer()
        )
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                renderer,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level, logging.INFO)),
            cache_logger_on_first_use=True,
        )


def get_logger(name: str = "echolens"):
    _configure()
    if _HAVE_STRUCTLOG:
        return structlog.get_logger(name)
    return _StdlibShim(logging.getLogger(name))


def bind_investigation(investigation_id: int | None) -> None:
    """Attach a correlation id to all subsequent logs in this context."""
    if _HAVE_STRUCTLOG:
        structlog.contextvars.bind_contextvars(investigation_id=investigation_id)


def clear_context() -> None:
    if _HAVE_STRUCTLOG:
        structlog.contextvars.clear_contextvars()


class _StdlibShim:
    """Minimal structlog-like API over stdlib logging (kwargs → key=value)."""

    def __init__(self, logger: logging.Logger):
        self._log = logger

    def _fmt(self, event: str, **kw) -> str:
        extra = " ".join(f"{k}={v}" for k, v in kw.items())
        return f"{event} {extra}".strip()

    def info(self, event: str, **kw):
        self._log.info(self._fmt(event, **kw))

    def warning(self, event: str, **kw):
        self._log.warning(self._fmt(event, **kw))

    def error(self, event: str, **kw):
        self._log.error(self._fmt(event, **kw))

    def debug(self, event: str, **kw):
        self._log.debug(self._fmt(event, **kw))
