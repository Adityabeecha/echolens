"""Graceful investigation recovery (v1.0).

On startup, any investigation still marked `running` was interrupted (crash,
deploy, kill). `resume_running` continues each from its last checkpoint; if a
case has no checkpoint yet (died in iteration 1) it is closed honestly as
needs_human rather than left orphaned.
"""
from __future__ import annotations

from datetime import datetime, timezone

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


# ── v15: continue a dead-end case with more budget ──────────────────────
#
# A case that ran out of budget, or stopped for lack of evidence, used to be
# final: resume only accepts a running/paused case. But a reviewer looking at
# "best confidence 0.72 when the budget ran out" often wants five more steps,
# not a fresh case that throws the gathered evidence away. This continues from
# the saved checkpoint with explicitly granted headroom — capped per case, so
# "one more try" cannot become an unbounded spend.

EXTENSION_STEPS = 5
MAX_HUMAN_EXTENSIONS = 2
EXTENDABLE_STATUSES = ("budget_exhausted", "insufficient_evidence")
# Headroom granted alongside the steps. The steps are the promise; tokens, cost
# and wall-clock get enough room to actually take them (1.5x the observed
# per-step rate), with floors so a case whose cost was never recorded is not
# granted zero dollars and immediately re-exhausted.
_HEADROOM = 1.5
_MIN_EXTRA_TOKENS = 10_000
_MIN_EXTRA_COST = 0.05
_EXTRA_WALL_S = 15 * 60


def _restored_budget(inv: Investigation):
    """The Budget a resume would restore from this case's checkpoint."""
    from echolens.investigator.graph import _GRANT_FIELDS
    from echolens.investigator.state import Budget
    from echolens.config import BUDGET_TIERS
    tier = inv.budget_tier if inv.budget_tier in BUDGET_TIERS else "standard"
    budget = Budget.for_tier(tier)
    b = (inv.checkpoint_json or {}).get("budget", {}) or {}
    budget.iterations = int(b.get("iterations", 0) or 0)
    budget.tool_calls = int(b.get("tool_calls", 0) or 0)
    budget.tokens = int(b.get("tokens", 0) or 0)
    budget.cost_usd = float(b.get("cost_usd", 0.0) or 0.0)
    budget.prior_elapsed_s = float(b.get("elapsed_s", 0.0) or 0.0)
    budget.extended = bool(b.get("extended", False))
    budget.extension_factor = float(b.get("extension_factor", 1.0) or 1.0)
    for k in _GRANT_FIELDS:
        default = getattr(budget, k)
        setattr(budget, k, type(default)(b.get(k, default) or 0))
    return budget


def _recorded_cost(session: Session, inv: Investigation, budget) -> float:
    """What this case has actually cost so far: the LLM ledger when it has rows,
    else the checkpointed budget figure."""
    from sqlalchemy import func
    from echolens.db.models import LLMCall
    ledger = session.scalar(select(func.coalesce(func.sum(LLMCall.cost), 0.0)).where(
        LLMCall.investigation_id == inv.id)) or 0.0
    return float(ledger) if ledger > 0 else float(budget.cost_usd)


def _is_dead_end(session: Session, inv: Investigation, budget) -> bool:
    if inv.status in EXTENDABLE_STATUSES:
        return True
    # needs_human is overloaded: "the evidence conflicts" is a human call that
    # more budget cannot settle, but "the budget ended below the bar" is the same
    # dead end as budget_exhausted under another name (classify_end_state). Only
    # the second is extendable — decided by whether the restored budget is spent.
    from echolens.investigator import guards
    return inv.status == "needs_human" and bool(guards.budget_exceeded(budget))


def extension_offer(session: Session, inv: Investigation) -> dict:
    """Whether this case can be continued, and roughly what five more steps cost.

    The estimate is the case's own recorded spend per step so far, times the
    steps offered — this case's track record, not a tier average."""
    budget = _restored_budget(inv)
    spent = _recorded_cost(session, inv, budget)
    per_step = spent / max(1, budget.iterations)
    estimate = round(per_step * EXTENSION_STEPS, 2)
    used = budget.human_extensions
    out = {"eligible": False, "reason": "", "steps": EXTENSION_STEPS,
           "estimate_usd": estimate, "spent_usd": round(spent, 4),
           "used": used, "remaining": max(0, MAX_HUMAN_EXTENSIONS - used)}
    if not _is_dead_end(session, inv, budget):
        out["reason"] = "Only a case that ran out of budget or evidence can be continued."
    elif not inv.checkpoint_json:
        out["reason"] = "This case has no saved checkpoint to continue from."
    elif used >= MAX_HUMAN_EXTENSIONS:
        out["reason"] = (f"This case has already been continued {used} times — "
                         "open a new case instead.")
    else:
        from echolens.db.models import Finding
        latest = session.scalars(select(Finding).where(
            Finding.investigation_id == inv.id).order_by(Finding.id.desc())).first()
        if latest is not None and latest.status in ("approved", "challenged"):
            out["reason"] = "This finding has already been reviewed."
        else:
            out["eligible"] = True
    return out


def grant_extension(session: Session, inv: Investigation, by: str | None = None) -> dict:
    """The SYNCHRONOUS half of "continue with more budget": validate, write the
    granted headroom into the checkpoint, and mark the case running again. The
    caller runs Investigator.resume (off the request path in the API)."""
    offer = extension_offer(session, inv)
    if not offer["eligible"]:
        raise ValueError(offer["reason"])
    budget = _restored_budget(inv)
    steps = max(1, budget.iterations)
    tokens_per_step = budget.tokens / steps
    ckpt = dict(inv.checkpoint_json or {})
    b = dict(ckpt.get("budget", {}) or {})
    # Each grant is measured from where the case STANDS, not from the original
    # cap: a case that stopped early for lack of evidence still gets exactly
    # EXTENSION_STEPS more, and one that blew its token cap gets token room.
    b["extra_iterations"] = int(budget.extra_iterations
                                + max(0, budget.iterations - budget.cap_iterations())
                                + EXTENSION_STEPS)
    b["extra_tool_calls"] = int(budget.extra_tool_calls
                                + max(0, budget.tool_calls - budget.cap_tool_calls())
                                + EXTENSION_STEPS)
    b["extra_tokens"] = int(budget.extra_tokens
                            + max(0, budget.tokens - budget.cap_tokens())
                            + max(_MIN_EXTRA_TOKENS,
                                  tokens_per_step * EXTENSION_STEPS * _HEADROOM))
    b["extra_cost_usd"] = round(budget.extra_cost_usd
                                + max(0.0, budget.cost_usd - budget.cap_cost_usd())
                                + max(_MIN_EXTRA_COST, offer["estimate_usd"] * _HEADROOM), 4)
    b["extra_wall_s"] = float(budget.extra_wall_s
                              + max(0.0, budget.prior_elapsed_s - budget.cap_wall_s())
                              + _EXTRA_WALL_S)
    b["human_extensions"] = budget.human_extensions + 1
    ckpt["budget"] = b
    inv.checkpoint_json = ckpt          # reassign: JSON columns don't track mutation
    # The audit record for History: when, which extension, and who granted it.
    inv.extensions_json = [*(inv.extensions_json or []),
                           {"at": datetime.now(timezone.utc).isoformat(),
                            "n": b["human_extensions"], "steps": EXTENSION_STEPS, "by": by}]
    prior_status = inv.status
    inv.status = "running"
    inv.paused = False
    inv.resolved_at = None
    from echolens.db.models import AnomalyEvent
    anomaly = session.get(AnomalyEvent, inv.anomaly_id) if inv.anomaly_id else None
    if anomaly is not None:
        anomaly.status = "investigating"
    session.flush()
    return {**offer, "prior_status": prior_status,
            "used": b["human_extensions"],
            "remaining": max(0, MAX_HUMAN_EXTENSIONS - b["human_extensions"])}


def extension_trace_note(prior_status: str, steps: int = EXTENSION_STEPS) -> str:
    label = prior_status.replace("_", " ")
    return (f"A reviewer granted {steps} more steps after this case ended as "
            f"“{label}”. Continuing from the saved checkpoint with the hypotheses and "
            "evidence already gathered — the same guards apply.")


def extend_investigation(session: Session, inv: Investigation,
                         llm: LLMClient | None = None, on_step=None) -> Investigation:
    """Grant AND run (tests and off-request workers; never inside a request)."""
    from echolens.investigator.graph import Investigator
    granted = grant_extension(session, inv)
    return Investigator.resume(session, inv, llm=llm, on_step=on_step,
                               reason=extension_trace_note(granted["prior_status"]))
