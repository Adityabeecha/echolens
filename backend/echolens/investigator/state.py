"""Investigation state shared across the LangGraph loop (PRD §5.1–5.3)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from echolens.config import BUDGET_TIERS, BudgetTier


@dataclass
class Budget:
    tier: BudgetTier
    iterations: int = 0
    tool_calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    started_at: float = 0.0  # time.monotonic()

    @classmethod
    def for_tier(cls, name: str) -> "Budget":
        return cls(tier=BUDGET_TIERS[name])

    def as_dict(self) -> dict:
        return {
            "tier": self.tier.name,
            "iterations": f"{self.iterations}/{self.tier.max_iterations}",
            "tool_calls": f"{self.tool_calls}/{self.tier.max_tool_calls}",
            "tokens": f"{self.tokens}/{self.tier.max_tokens}",
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
    last_tool: dict | None      # {name, args, result} or {name, args, error}
    proposed: dict | None       # plan's declared conclusion, validated by check
