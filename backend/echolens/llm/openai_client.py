from __future__ import annotations

import json
import random
import time

from openai import OpenAI

from echolens.config import FALLBACK_PRICING, MODEL_PRICING, settings
from echolens.llm.client import LLMFormatError, LLMResult
from echolens.logging import get_logger

log = get_logger("llm")

# Transient errors worth retrying with backoff (rate limits, timeouts, 5xx).
try:  # keep import-safe across openai SDK versions
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    _TRANSIENT = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
except Exception:  # pragma: no cover
    _TRANSIENT = ()

try:
    from openai import BadRequestError
except Exception:  # pragma: no cover
    class BadRequestError(Exception):
        ...

LOW_TEMPERATURE = 0.2

# The SDK defaults to a 600s read timeout and 2 internal retries, so one stuck
# call can hold the loop for 30 minutes — longer than the whole `quick` tier
# wall-clock budget (900s). The budget guard only runs BETWEEN graph nodes, so
# nothing can interrupt a call already in flight; the ceiling has to be here.
REQUEST_TIMEOUT_S = 90.0
SDK_INTERNAL_RETRIES = 0
# Ceiling across all backoff attempts for ONE logical call, so five retries of a
# 90s timeout cannot add up to 7+ minutes on a single node.
MAX_TOTAL_CALL_S = 240.0


def _is_temperature_refusal(err: Exception) -> bool:
    text = str(err).lower()
    return "temperature" in text and ("unsupported" in text or "does not support" in text)


_warned_pricing: set[str] = set()


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price = MODEL_PRICING.get(model)
    if price is None:
        if model not in _warned_pricing:
            _warned_pricing.add(model)
            log.warning("llm_pricing_unknown", model=model,
                        note="cost recorded with a fallback rate; add it to "
                             "MODEL_PRICING for accurate spend and budget caps")
        price = FALLBACK_PRICING
    price_in, price_out = price
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


class OpenAIClient:
    """OpenAI structured-output client with exponential backoff on transient
    errors (v1.0) and one retry on malformed JSON. A rate limit pauses and
    retries with jittered backoff instead of failing the investigation."""

    _supports_temperature = True
    _max_total_s = MAX_TOTAL_CALL_S

    def __init__(self, model: str | None = None, on_call=None,
                 max_retries: int = 5, base_delay: float = 1.0, sleep=time.sleep,
                 max_total_s: float = MAX_TOTAL_CALL_S):
        self.model = model or settings.echolens_model
        self._client = OpenAI(api_key=settings.openai_api_key,
                              timeout=REQUEST_TIMEOUT_S,
                              max_retries=SDK_INTERNAL_RETRIES)
        self._on_call = on_call
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._sleep = sleep  # injectable so tests don't actually wait
        self._max_total_s = max_total_s
        self._supports_temperature = True

    def _create_with_backoff(self, system: str, user: str, json_schema: dict):
        attempt = 0
        deadline = time.monotonic() + self._max_total_s
        while True:
            try:
                kwargs: dict = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "response", "schema": json_schema,
                                        "strict": False},
                    },
                }
                if self._supports_temperature:
                    kwargs["temperature"] = LOW_TEMPERATURE
                return self._client.chat.completions.create(**kwargs)
            except BadRequestError as err:
                if self._supports_temperature and _is_temperature_refusal(err):
                    log.warning("llm_temperature_unsupported", model=self.model)
                    self._supports_temperature = False
                    continue
                raise
            except _TRANSIENT as err:
                attempt += 1
                if attempt > self._max_retries:
                    log.error("llm_giving_up", attempts=attempt, error=str(err))
                    raise
                delay = self._base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                remaining = deadline - time.monotonic()
                if remaining <= delay:
                    log.error("llm_deadline_exceeded", attempts=attempt,
                              budget_s=self._max_total_s, error=type(err).__name__)
                    raise
                log.warning("llm_backoff", attempt=attempt, delay_s=round(delay, 2), error=type(err).__name__)
                self._sleep(delay)

    def complete_json(self, system: str, user: str, json_schema: dict, agent: str) -> LLMResult:
        last_err: Exception | None = None
        prompt = user
        for _attempt in range(2):  # one retry specifically for malformed JSON
            start = time.monotonic()
            resp = self._create_with_backoff(system, prompt, json_schema)
            ms = int((time.monotonic() - start) * 1000)
            usage = resp.usage
            tokens_in = usage.prompt_tokens if usage else 0
            tokens_out = usage.completion_tokens if usage else 0
            if self._on_call:
                self._on_call(agent, self.model, tokens_in, tokens_out,
                              compute_cost(self.model, tokens_in, tokens_out), ms)
            try:
                parsed = json.loads(resp.choices[0].message.content or "")
                return LLMResult(parsed=parsed, tokens_in=tokens_in, tokens_out=tokens_out, ms=ms, model=self.model)
            except (json.JSONDecodeError, IndexError) as err:
                last_err = err
                # Tell the model what went wrong. The retry used to re-send a
                # byte-identical prompt at a fixed temperature, so a deterministic
                # formatting failure reproduced exactly — two API calls, two
                # bills, one guaranteed-identical failure.
                raw = (resp.choices[0].message.content or "") if resp.choices else ""
                prompt = (f"{user}\n\nYOUR PREVIOUS REPLY WAS NOT VALID JSON and could not be "
                          f"parsed ({err}). Return ONLY a single JSON object matching the "
                          f"schema — no prose, no code fences. Your previous reply began: "
                          f"{raw[:200]!r}")
        raise LLMFormatError(f"{agent}: model returned malformed JSON twice: {last_err}")
