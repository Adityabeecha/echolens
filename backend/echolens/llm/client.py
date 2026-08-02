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


def _dict_to_list(value: dict, item_spec: dict) -> list:
    """One dict where a list was declared. Three shapes occur in practice:

      {"0": {...}, "1": {...}}   numbered map    -> its values
      {"evidence": [...]}        wrapped list    -> the inner list
      {"ref": "r1", ...}         a single ITEM   -> [value]

    Distinguishing the third matters: taking .values() there shreds one evidence
    object into a list of its field values, which then fails ref validation and
    silently drops real evidence.
    """
    if not value:
        return []
    inner = list(value.values())
    if len(inner) == 1 and isinstance(inner[0], list):
        return inner[0]
    if all(k.isdigit() for k in value):
        return inner
    required = set((item_spec or {}).get("required") or ())
    if required and required <= set(value):
        return [value]
    if all(isinstance(v, dict) for v in inner) and len(inner) > 1:
        return inner
    return [value]


def coerce_to_schema(parsed: dict, json_schema: dict) -> dict:
    """Force model output into the shape the schema declares.

    response_format is sent with strict=False, so the schema is advisory: the
    provider may return an object where an array was declared. Crash observed in
    production — `KeyError: slice(None, 5, None)` from slicing a dict — which
    killed the investigation immediately after a tool call, on the node that
    assesses the tool's result.

    Coercing here means every caller is protected at the one point model output
    enters the system, rather than each site guarding its own reads.
    """
    if not isinstance(parsed, dict):
        return {}
    props = (json_schema or {}).get("properties") or {}
    out = dict(parsed)
    for key, spec in props.items():
        if key not in out:
            continue
        declared = (spec or {}).get("type")
        value = out[key]
        if declared == "array" and not isinstance(value, list):
            if isinstance(value, dict):
                out[key] = _dict_to_list(value, (spec or {}).get("items") or {})
            elif value is None:
                out[key] = []
            else:
                out[key] = [value]
        elif declared == "object" and not isinstance(value, dict):
            out[key] = {} if value is None else value
    return out
