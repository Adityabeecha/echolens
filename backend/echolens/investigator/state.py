"""Investigation state shared across the LangGraph loop (PRD §5.1–5.3)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from echolens.config import BUDGET_TIERS, BudgetTier


@dataclass
class Budget:
    tier: BudgetTier
    iterations: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    started_at: float = 0.0  # time.monotonic() of THIS process's run segment
    # wall-clock already spent in PRIOR segments (restored from checkpoint on resume)
    # so the wall-clock guard survives a server restart.
    prior_elapsed_s: float = 0.0
    extension_factor: float = 1.0  # v2.0: one-time extension multiplier on caps
    extended: bool = False
    # v15: headroom a REVIEWER explicitly granted to a dead-end case ("continue
    # with more budget"). Additive on top of the scaled tier caps, so the guard
    # still enforces a hard ceiling — it is just a ceiling a human raised, with
    # their name on it, rather than one the agent raised for itself.
    extra_iterations: int = 0
    extra_tool_calls: int = 0
    extra_tokens: int = 0
    extra_cost_usd: float = 0.0
    extra_wall_s: float = 0.0
    human_extensions: int = 0

    def elapsed_s(self) -> float:
        import time
        live = (time.monotonic() - self.started_at) if self.started_at else 0.0
        return self.prior_elapsed_s + live

    @classmethod
    def for_tier(cls, name: str) -> "Budget":
        return cls(tier=BUDGET_TIERS[name])

    # The effective hard caps. One definition, read by both the guard and the
    # display, so the budget shown can never disagree with the budget enforced.
    def cap_iterations(self) -> float:
        return self.tier.max_iterations * self.extension_factor + self.extra_iterations

    def cap_tool_calls(self) -> float:
        return self.tier.max_tool_calls * self.extension_factor + self.extra_tool_calls

    def cap_tokens(self) -> float:
        return self.tier.max_tokens * self.extension_factor + self.extra_tokens

    def cap_cost_usd(self) -> float:
        return self.tier.max_cost_usd * self.extension_factor + self.extra_cost_usd

    def cap_wall_s(self) -> float:
        return self.tier.max_wall_clock_s * self.extension_factor + self.extra_wall_s

    def as_dict(self) -> dict:
        tier = self.tier.name + (" +ext" if self.extended else "")
        if self.human_extensions:
            tier += f" +{self.human_extensions} granted"
        return {
            "tier": tier,
            "iterations": f"{self.iterations}/{int(self.cap_iterations())}",
            "tool_calls": f"{self.tool_calls}/{int(self.cap_tool_calls())}",
            "tokens": f"{self.tokens}/{int(self.cap_tokens())}",
            "cost_usd": round(self.cost_usd, 4),
        }


class InvState(TypedDict, total=False):
    """LangGraph graph state. Hypotheses/evidence are plain dicts:

    hypothesis: {id, statement, confidence, status, evidence_for, evidence_against, next_test}
    evidence:   {id, source, ref, snippet, retrieved_by, supports, contradicts}
    """
    trigger: dict[str, Any]
    hypotheses: list[dict]
    evidence: list[dict]
    status: str            # running|resolved|insufficient_evidence|needs_human|budget_exhausted
    status_reason: str
    finding: dict | None
    pending_tool: dict | None   # {name, args, tests_hypothesis}
    pending_delegate: dict | None  # {specialist, focus} — v2.0 delegation
    last_tool: dict | None      # {name, args, result} or {name, args, error}
    proposed: dict | None       # plan's declared conclusion, validated by check
    over_budget: bool           # set by the pre-flight check in _plan
