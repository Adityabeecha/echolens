"""Orchestrator agent (PRD §4.1): triages pending anomalies in one LLM call.

Per anomaly it decides investigate(tier) / ignore(reason) / merge(into). It is
an agent because "which anomalies are worth a costly investigation, which are
noise, which duplicate an open case" is a runtime judgment — but a SMALL one:
one call per batch, and the daily budget is enforced in code, not by the model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.config import ORCHESTRATOR_DAILY_INVESTIGATIONS
from echolens.db.models import AnomalyEvent, Investigation, LLMCall, TriageDecision
from echolens.detector.detect import AS_OF
from echolens.llm.client import LLMClient, LLMFormatError

TRIAGE_SYSTEM = """You are the EchoLens orchestrator. Detected anomalies arrive in batches; \
your job is triage — decide what NOT to do as much as what to do. For each anomaly choose:
- "investigate": worth a full agentic investigation. Assign a budget tier: "quick" (cheap, \
narrow), "standard" (default), or "deep" (broad, expensive). Reserve "deep" for high-severity, \
wide-open questions.
- "merge": this anomaly is the SAME underlying signal as another one you are investigating in \
this batch (same theme + same time window, e.g. a GitHub issue-velocity surge that mirrors a \
review spike). Give its `merge_into` = the other anomaly's slug. Do not open a second case.
- "ignore": within normal variance, no version/release correlation, or too vague to act on. \
Give a concrete reason.

Be economical — investigations cost money and you have a hard daily cap. Merge duplicates, \
ignore noise, and spend the budget on the signals most likely to have an actionable root cause.
Respond with JSON only."""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "anomaly": {"type": "string", "description": "the anomaly slug"},
                    "decision": {"type": "string", "enum": ["investigate", "ignore", "merge"]},
                    "reason": {"type": "string"},
                    "budget_tier": {"type": "string", "enum": ["quick", "standard", "deep"]},
                    "merge_into": {"type": "string", "description": "slug of the anomaly this duplicates"},
                },
                "required": ["anomaly", "decision", "reason"],
            },
        }
    },
    "required": ["decisions"],
}


@dataclass
class Decision:
    anomaly: AnomalyEvent
    decision: str
    reason: str
    budget_tier: str | None = None
    merge_into: AnomalyEvent | None = None


class Orchestrator:
    def __init__(self, session: Session, llm: LLMClient | None = None,
                 daily_limit: int = ORCHESTRATOR_DAILY_INVESTIGATIONS):
        self.session = session
        self.daily_limit = daily_limit
        if llm is None:
            from echolens.llm.openai_client import OpenAIClient
            llm = OpenAIClient(on_call=self._record_llm_call)
        self.llm = llm

    def _record_llm_call(self, agent, model, tokens_in, tokens_out, cost, ms):
        self.session.add(LLMCall(
            investigation_id=None, agent=agent, model=model,
            tokens_in=tokens_in, tokens_out=tokens_out, cost=cost, ms=ms,
        ))

    def _investigations_today(self, as_of: datetime) -> int:
        rows = self.session.scalars(select(Investigation)).all()
        return sum(1 for r in rows if r.created_at and r.created_at.date() == as_of.date())

    def triage(self, as_of: datetime = AS_OF) -> list[Decision]:
        pending = self.session.scalars(
            select(AnomalyEvent).where(AnomalyEvent.status == "pending")
        ).all()
        if not pending:
            return []
        open_invs = self.session.scalars(
            select(Investigation).where(Investigation.status == "running")
        ).all()

        by_slug = {a.slug: a for a in pending}
        prompt = (
            f"REMAINING DAILY BUDGET: {self.daily_limit - self._investigations_today(as_of)} "
            f"of {self.daily_limit} investigations.\n\n"
            "PENDING ANOMALIES:\n" + json.dumps([
                {"slug": a.slug, "type": a.type, "metric": a.metric,
                 "delta": a.delta, "z": a.z, "window": a.window, "description": a.description}
                for a in pending
            ], indent=1) + "\n\nALREADY OPEN INVESTIGATIONS:\n" + json.dumps([
                {"id": i.id, "anomaly_id": i.anomaly_id, "tier": i.budget_tier}
                for i in open_invs
            ])
        )
        try:
            res = self.llm.complete_json(TRIAGE_SYSTEM, prompt, TRIAGE_SCHEMA, "orchestrator")
            raw = res.parsed.get("decisions", [])
        except LLMFormatError:
            raw = []

        # Parse LLM proposals; anything unmentioned/invalid defaults to ignore.
        decisions: dict[str, Decision] = {}
        for d in raw:
            a = by_slug.get(d.get("anomaly"))
            if a is None:
                continue
            kind = d.get("decision", "ignore")
            merge_into = by_slug.get(d.get("merge_into")) if kind == "merge" else None
            if kind == "merge" and merge_into is None:
                kind, d["reason"] = "ignore", "merge target not found; " + d.get("reason", "")
            decisions[a.slug] = Decision(
                anomaly=a, decision=kind, reason=d.get("reason", ""),
                budget_tier=d.get("budget_tier", "standard") if kind == "investigate" else None,
                merge_into=merge_into,
            )
        for a in pending:  # default for anything the model skipped
            decisions.setdefault(a.slug, Decision(a, "ignore", "not selected by orchestrator"))

        self._enforce_daily_cap(list(decisions.values()), as_of)
        self._persist(list(decisions.values()))
        return list(decisions.values())

    def _enforce_daily_cap(self, decisions: list[Decision], as_of: datetime) -> None:
        """Deterministic guard: never exceed the daily investigation cap.
        Keep the highest-severity investigations; defer the rest to 'pending'."""
        remaining = self.daily_limit - self._investigations_today(as_of)
        investigate = sorted(
            (d for d in decisions if d.decision == "investigate"),
            key=lambda d: -abs(d.anomaly.z),
        )
        for d in investigate[max(remaining, 0):]:
            d.decision = "ignore"
            d.reason = f"daily investigation cap ({self.daily_limit}) reached — deferred. " + d.reason
            d.budget_tier = None

    def _persist(self, decisions: list[Decision]) -> None:
        for d in decisions:
            self.session.add(TriageDecision(
                anomaly_id=d.anomaly.id, decision=d.decision, reason=d.reason,
                budget_tier=d.budget_tier,
                merge_into_anomaly_id=d.merge_into.id if d.merge_into else None,
            ))
            d.anomaly.status = {
                "investigate": "triaged", "merge": "merged", "ignore": "ignored",
            }[d.decision]
        self.session.flush()


def run_triaged(session: Session, decisions: list[Decision], llm: LLMClient | None = None,
                on_step=None) -> list[Investigation]:
    """Spawn one Investigator per 'investigate' decision (PRD: orchestrator
    spawns, one per investigation). Returns the investigations it ran."""
    from echolens.investigator.graph import Investigator

    investigations: list[Investigation] = []
    for d in decisions:
        if d.decision != "investigate":
            continue
        d.anomaly.status = "investigating"
        inv = Investigator(session, d.anomaly, llm=llm, tier=d.budget_tier or "standard",
                           opened_by="anomaly", on_step=on_step).run()
        investigations.append(inv)
    return investigations
