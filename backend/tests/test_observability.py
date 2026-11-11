"""Error tracking: off without a DSN; with one, log.error lines reach Sentry."""
import sentry_sdk
from sentry_sdk.transport import Transport

import echolens.observability as obs
from echolens.config import settings


def test_no_dsn_means_no_sentry(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    monkeypatch.setattr(obs, "_active", False)
    assert obs.init_sentry("test") is False
    # The log processor is a pass-through when Sentry is off.
    event = {"event": "x_failed", "error": "boom"}
    assert obs.forward_errors(None, "error", event) is event


def test_logged_errors_reach_sentry_grouped_by_event(monkeypatch):
    sent = []

    class Capture(Transport):
        def capture_envelope(self, envelope):
            sent.append(envelope)

    real_init = sentry_sdk.init
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: real_init(transport=Capture, **kw))
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@o0.ingest.sentry.io/1")
    monkeypatch.setattr(obs, "_active", False)
    try:
        assert obs.init_sentry("test") is True
        obs.forward_errors(None, "info", {"event": "fine"})
        obs.forward_errors(None, "error", {"event": "collector_fetch_failed",
                                           "source": "play_store", "error": "boom"})
        sentry_sdk.flush()
        events = [item.payload.json for env in sent for item in env.items if item.type == "event"]
        assert len(events) == 1
        assert events[0]["fingerprint"] == ["collector_fetch_failed"]
        assert events[0]["extra"]["source"] == "play_store"
        assert events[0]["tags"]["process"] == "test"
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.init()  # back to a disabled client for the rest of the suite
