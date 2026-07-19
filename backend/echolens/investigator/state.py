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

    def elapsed_s(self) -> float:
        import time
        live = (time.monotonic() - self.started_at) if self.started_at else 0.0
        return self.prior_elapsed_s + live

    @classmethod
    def for_tier(cls, name: str) -> "Budget":
        return cls(tier=BUDGET_TIERS[name])

    def as_dict(self) -> dict:
        f = self.extension_factor
        return {
            "tier": self.tier.name + (" +ext" if self.extended else ""),
            "iterations": f"{self.iterations}/{int(self.tier.max_iterations * f)}",
            "tool_calls": f"{self.tool_calls}/{int(self.tier.max_tool_calls * f)}",
            "tokens": f"{self.tokens}/{int(self.tier.max_tokens * f)}",
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
