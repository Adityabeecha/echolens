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
    return list(session.scalars(select(Investigation).where(Investigation.status == "running")).all())


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
