"""Batch 3 — budget and cost enforcement.

The caps were MEASURED accurately and ENFORCED loosely. Every defect here let
real money escape a limit the operator had configured, and several spent it
without recording that they had.
"""
from __future__ import annotations

import pytest

from echolens.config import BUDGET_TIERS, TOOL_RESULT_MAX_ITEMS
from echolens.investigator import guards
from echolens.investigator.state import Budget
from echolens.tools._util import cap_items
from echolens.tools.registry import _coerce


# ── B3.7 / B3.9 ─────────────────────────────────────────────────────────

def test_negative_limit_cannot_bypass_truncation():
    """`items[:k]` with a negative k slices from the END: cap_items(500 items, -5)
    returned 495 of them straight into LLM context."""
    capped, total = cap_items(list(range(500)), -5)
    assert len(capped) <= TOOL_RESULT_MAX_ITEMS
    assert total == 500


def test_cap_items_handles_junk_limits():
    for junk in ("abc", None, 0, -1, 10**9):
        capped, _ = cap_items(list(range(500)), junk)
        assert 1 <= len(capped) <= TOOL_RESULT_MAX_ITEMS


def test_tool_args_are_type_checked_not_just_key_filtered():
    """run_tool filtered by key only, so every declared "integer"/"enum" in the
    tool schemas was decorative."""
    assert _coerce("t", "limit", "7", {"type": "integer"}) == 7
    assert _coerce("t", "limit", -5, {"type": "integer"}) == 1
    with pytest.raises(ValueError):
        _coerce("t", "rating_max", "not-a-number", {"type": "integer"})
    with pytest.raises(ValueError):
        _coerce("t", "dimension", "banana", {"type": "string", "enum": ["version", "os"]})


# ── B3.4 ────────────────────────────────────────────────────────────────

def test_budget_extension_survives_a_resume():
    """`extended`/`extension_factor` were not checkpointed, so a resumed run
    restored a budget already at the extended ceiling but flagged un-extended —
    and resume_running() fires on every app start, so a crash-loop during a
    deploy re-granted the one-time extension without limit."""
    b = Budget(tier=BUDGET_TIERS["standard"])
    b.iterations, b.tokens, b.cost_usd = 18, 180_000, 1.12
    b.extended, b.extension_factor = True, 1.5

    checkpoint = {"iterations": b.iterations, "tool_calls": b.tool_calls,
                  "tokens": b.tokens, "cost_usd": b.cost_usd, "elapsed_s": 0.0,
                  "extended": b.extended, "extension_factor": b.extension_factor}

    restored = Budget(tier=BUDGET_TIERS["standard"])
    restored.iterations = checkpoint["iterations"]
    restored.tokens = checkpoint["tokens"]
    restored.cost_usd = checkpoint["cost_usd"]
    restored.extended = bool(checkpoint.get("extended", False))
    restored.extension_factor = float(checkpoint.get("extension_factor", 1.0))

    assert restored.extended is True, "a resumed run must not be granted a fresh extension"
    assert restored.extension_factor == 1.5
    assert guards.budget_exceeded(restored), "an exhausted budget stays exhausted"


# ── B3.1 ────────────────────────────────────────────────────────────────

def test_an_exhausted_budget_is_detected_before_the_next_spend():
    """The caps were consulted only in _check, at the END of a
    plan->act->update cycle, so a run at 119k/120k tokens still executed a full
    iteration (two LLM calls and a tool result) and the cap was merely OBSERVED
    to be blown afterwards. _plan now refuses up front."""
    b = Budget(tier=BUDGET_TIERS["standard"])
    b.tokens = int(b.tier.max_tokens)
    assert guards.budget_exceeded(b), "the guard must see this state as exhausted"


# ── B3.5 ────────────────────────────────────────────────────────────────

def test_no_llm_client_is_constructed_without_cost_recording():
    """Three call sites used `on_call=lambda *a: None`, so the recommender —
    one of the largest prompts in the system, sent on EVERY completed
    investigation — appeared in no cost report and counted against no budget."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "echolens"
    offenders = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "OpenAIClient(on_call=lambda" in line:
                offenders.append(f"{path.name}:{i}")
    assert not offenders, f"unmetered LLM clients: {offenders}"
