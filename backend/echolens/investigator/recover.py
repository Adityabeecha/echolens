"""Graceful investigation recovery (v1.0).

On startup, any investigation still marked `running` was interrupted (crash,
deploy, kill). `resume_running` continues each from its last checkpoint; if a
case has no checkpoint yet (died in iteration 1) it is closed honestly as
needs_human rather than left orphaned.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Investigation
from echolens.llm.client import LLMClient
from echolens.logging import get_logger

log = get_logger("recover")


def find_interrupted(session: Session) -> list[Investigation]:
    """Investigations a restart left mid-flight.

    A PAUSED case is not one of them. The cooperative pause sets paused=True but
    leaves status="running" (that is what makes it resumable at all), so
    selecting on status alone swept up every case a reviewer had deliberately
    held — the next deploy silently resumed it and carried on burning its
    budget. A human's hold outranks a restart.
    """
    return list(session.scalars(
        select(Investigation).where(
            Investigation.status == "running",
            # `is_not(True)` rather than `== False`: the column is nullable and
            # older rows carry NULL, which `== False` does not match in SQL.
            Investigation.paused.is_not(True),
        )
    ).all())


def resume_running(session: Session, llm: LLMClient | None = None, on_step=None) -> list[int]:
    """Resume (or honestly close) every interrupted investigation. Returns the
    ids that were acted on."""
    from echolens.investigator.graph import Investigator

    acted: list[int] = []
    for inv in find_interrupted(session):
        if inv.checkpoint_json:
            log.info("resuming_investigation", id=inv.id)
            Investigator.resume(session, inv, llm=llm, on_step=on_step)
        else:  # nothing to resume from
            log.warning("closing_orphan_investigation", id=inv.id)
            inv.status = "needs_human"
            session.flush()
        acted.append(inv.id)
    return acted
