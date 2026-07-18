from __future__ import annotations

import json
import random
import time

from openai import OpenAI

from echolens.config import MODEL_PRICING, settings
from echolens.llm.client import LLMFormatError, LLMResult
from echolens.logging import get_logger

log = get_logger("llm")

# Transient errors worth retrying with backoff (rate limits, timeouts, 5xx).
try:  # keep import-safe across openai SDK versions
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    _TRANSIENT = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)
except Exception:  # pragma: no cover
    _TRANSIENT = ()


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = MODEL_PRICING.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


class OpenAIClient:
    """OpenAI structured-output client with exponential backoff on transient
    errors (v1.0) and one retry on malformed JSON. A rate limit pauses and
    retries with jittered backoff instead of failing the investigation."""

    def __init__(self, model: str | None = None, on_call=None,
                 max_retries: int = 5, base_delay: float = 1.0, sleep=time.sleep):
        self.model = model or settings.echolens_model
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._on_call = on_call
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._sleep = sleep  # injectable so tests don't actually wait

    def _create_with_backoff(self, system: str, user: str, json_schema: dict):
        attempt = 0
        while True:
            try:
                return self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": "response", "schema": json_schema, "strict": False},
                    },
                    temperature=0.2,
                )
            except _TRANSIENT as err:
                attempt += 1
                if attempt > self._max_retries:
                    log.error("llm_giving_up", attempts=attempt, error=str(err))
                    raise
                delay = self._base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log.warning("llm_backoff", attempt=attempt, delay_s=round(delay, 2), error=type(err).__name__)
                self._sleep(delay)

    def complete_json(self, system: str, user: str, json_schema: dict, agent: str) -> LLMResult:
        last_err: Exception | None = None
        for _attempt in range(2):  # one retry specifically for malformed JSON
            start = time.monotonic()
            resp = self._create_with_backoff(system, user, json_schema)
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
        raise LLMFormatError(f"{agent}: model returned malformed JSON twice: {last_err}")
