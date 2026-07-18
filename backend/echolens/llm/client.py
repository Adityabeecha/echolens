"""Provider-agnostic LLM interface. Groq/Gemini/Claude are drop-in swaps.

Every call returns parsed JSON (agents only ever consume structured output)
plus usage, and is logged to `llm_calls` by the caller-supplied recorder.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    parsed: dict
    tokens_in: int
    tokens_out: int
    ms: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class LLMClient(Protocol):
    def complete_json(
        self,
        system: str,
        user: str,
        json_schema: dict,
        agent: str,
    ) -> LLMResult:
        """Return structured JSON conforming to `json_schema`.
        Raise LLMFormatError if the provider cannot produce valid JSON."""
        ...


class LLMFormatError(RuntimeError):
    """Provider returned unusable output (after retry)."""
