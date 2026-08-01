from __future__ import annotations

import pytest

from echolens.config import FALLBACK_PRICING, MODEL_PRICING
from echolens.llm import openai_client as oc


def _bad_request(message: str) -> Exception:
    try:
        import httpx
        return oc.BadRequestError(
            message,
            response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
            body=None,
        )
    except TypeError:
        return oc.BadRequestError(message)


class _Resp:
    def __init__(self):
        self.usage = type("U", (), {"prompt_tokens": 40, "completion_tokens": 10})()
        msg = type("M", (), {"content": '{"ok": true}'})()
        self.choices = [type("C", (), {"message": msg})()]


class _FakeCompletions:
    def __init__(self, reject_temperature: bool):
        self.reject = reject_temperature
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject and "temperature" in kwargs:
            raise _bad_request(
                "Error code: 400 - Unsupported value: 'temperature' does not "
                "support 0.2 with this model. Only the default (1) value is supported.")
        return _Resp()


def _client(monkeypatch, reject_temperature: bool):
    fake = _FakeCompletions(reject_temperature)
    monkeypatch.setattr(oc, "OpenAI", lambda api_key=None: type(
        "X", (), {"chat": type("Y", (), {"completions": fake})()})())
    c = oc.OpenAIClient(model="test-model")
    return c, fake


def test_a_model_that_rejects_temperature_still_works(monkeypatch):
    c, fake = _client(monkeypatch, reject_temperature=True)
    r = c.complete_json("s", "u", {"type": "object"}, "agent")
    assert r.parsed == {"ok": True}
    assert "temperature" in fake.calls[0]
    assert "temperature" not in fake.calls[1]


def test_temperature_is_dropped_only_once(monkeypatch):
    c, fake = _client(monkeypatch, reject_temperature=True)
    c.complete_json("s", "u", {"type": "object"}, "agent")
    before = len(fake.calls)
    c.complete_json("s", "u", {"type": "object"}, "agent")
    assert all("temperature" not in k for k in fake.calls[before:])


def test_a_model_that_accepts_temperature_keeps_it(monkeypatch):
    c, fake = _client(monkeypatch, reject_temperature=False)
    c.complete_json("s", "u", {"type": "object"}, "agent")
    assert fake.calls[0]["temperature"] == oc.LOW_TEMPERATURE
    assert c._supports_temperature is True


def test_an_unrelated_bad_request_is_not_swallowed(monkeypatch):
    fake = _FakeCompletions(False)

    def boom(**kwargs):
        raise _bad_request("Error code: 400 - context_length_exceeded")

    fake.create = boom
    monkeypatch.setattr(oc, "OpenAI", lambda api_key=None: type(
        "X", (), {"chat": type("Y", (), {"completions": fake})()})())
    with pytest.raises(oc.BadRequestError):
        oc.OpenAIClient(model="m").complete_json("s", "u", {"type": "object"}, "a")


def test_an_unpriced_model_is_never_free():
    cost = oc.compute_cost("some-brand-new-model", 100_000, 20_000)
    assert cost > 0, "a zero cost makes max_cost_usd unenforceable"
    expected = (100_000 * FALLBACK_PRICING[0] + 20_000 * FALLBACK_PRICING[1]) / 1_000_000
    assert cost == pytest.approx(expected)


def test_a_priced_model_uses_its_real_rate():
    price_in, price_out = MODEL_PRICING["gpt-4o-mini"]
    expected = (100_000 * price_in + 20_000 * price_out) / 1_000_000
    assert oc.compute_cost("gpt-4o-mini", 100_000, 20_000) == pytest.approx(expected)


def test_the_temperature_refusal_detector_is_specific():
    assert oc._is_temperature_refusal(Exception(
        "Unsupported value: 'temperature' does not support 0.2 with this model"))
    assert not oc._is_temperature_refusal(Exception("context_length_exceeded"))
    assert not oc._is_temperature_refusal(Exception("invalid api key"))
