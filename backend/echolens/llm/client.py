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
        Raise LLMError when the provider is unavailable or unusable."""
        ...


class LLMError(RuntimeError):
    """A provider failure an agent node can recover from safely."""


class LLMFormatError(LLMError):
    """Provider returned unusable output (after retry)."""


class LLMServiceError(LLMError):
    """Provider stayed unavailable after its bounded retries."""


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


def _coerce_value(value, spec: dict):
    """Recursively make a provider value safe to consume as ``spec``.

    Structured-output schemas are advisory for providers running with
    ``strict=False``.  Normalising only the top-level container still allowed
    values such as ``evidence: ["text"]`` and ``supports: "H1"`` through: the
    first crashed on ``item.get`` and the second was iterated as ``H``, ``1``.
    """
    declared = (spec or {}).get("type")
    if declared == "array":
        item_spec = (spec or {}).get("items") or {}
        if not isinstance(value, list):
            if isinstance(value, dict):
                value = _dict_to_list(value, item_spec)
            elif value is None:
                value = []
            else:
                value = [value]

        out = []
        for item in value:
            # An array of objects cannot usefully preserve a bare scalar. Drop
            # it at the trust boundary instead of making every consumer guard
            # every ``.get`` call independently.
            if item_spec.get("type") == "object" and not isinstance(item, dict):
                continue
            out.append(_coerce_value(item, item_spec))
        return out

    if declared == "object":
        if not isinstance(value, dict):
            return {}
        out = dict(value)
        for key, child_spec in ((spec or {}).get("properties") or {}).items():
            if key in out:
                out[key] = _coerce_value(out[key], child_spec or {})
        return out

    return value


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
    return _coerce_value(parsed, json_schema)
