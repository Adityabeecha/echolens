"""Operations regressions: bounded critical-case continuation, incidents, reset."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from echolens.db.models import Base, Product, AnomalyEvent, Investigation, Finding, LLMCall, TraceStep
from echolens.eval.harness import ScriptedLLM
from echolens.investigator.graph import Investigator
from echolens.investigator.recover import grant_extension


@pytest.fixture()
def budget_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s
    engine.dispose()


def _budget_runner(s, z=4.0, limits=None, confidence=0.6, repeat=False):
    p = Product(name="Critical", limits_json=limits)
    s.add(p); s.flush()
    a = AnomalyEvent(slug="critical", product_id=p.id, type="negative_review_spike",
        metric="1-star rate", z=z, delta=0.5, window="7d", description="reviews spike", status="pending")
    s.add(a); s.flush()
    finding = {"summary": "No cause established", "prose": "More evidence is needed.",
        "confidence": confidence, "supported_hypothesis": None, "checked": [],
        "what_would_settle_it": "An independent source"}
    script = [{}, finding] + ([{}] * 5 if repeat else [
        {"action": "conclude", "conclusion": {"status": "insufficient_evidence", "reason": "still no source"}}]) + [finding]
    runner = Investigator(s, a, llm=ScriptedLLM(script), tier="quick")
    runner.budget.iterations = 4
    seed = {"hypotheses": [{"id": "H1", "statement": "Review spike under investigation",
        "confidence": confidence, "status": "active", "evidence_for": [], "evidence_against": []}], "evidence": []}
    return runner, seed, p


def test_critical_budget_extension_is_audited_once_and_resumes_the_same_case(budget_session):
    s = budget_session
    runner, seed, p = _budget_runner(s, repeat=True)
    out = runner.run(seed_state=seed)
    assert len(out.extensions_json or []) == 1
    audit = out.extensions_json[0]
    assert audit["by"] == "auto" and audit["steps"] == 5 and audit["reason"]
    assert out.checkpoint_json["budget"]["auto_extensions"] == 1
    assert out.checkpoint_json["budget"]["human_extensions"] == 1
    assert out.budget_json["iterations"] == "10/10"
    assert s.query(Investigation).count() == 1
    assert s.query(Finding).count() == 2
    assert out.status == "budget_exhausted"
    texts = [t.content_json.get("text", "") for t in s.scalars(select(TraceStep)).all()]
    assert any("Automatic" in text and "5" in text for text in texts)
    # A restart cannot grant another automatic extension.
    with pytest.raises(ValueError):
        grant_extension(s, out, by="auto")


@pytest.mark.parametrize("z,confidence", [(1.0, 0.7), (4.0, 0.49)])
def test_low_severity_or_weak_hypothesis_never_auto_extends(budget_session, z, confidence):
    runner, seed, _ = _budget_runner(budget_session, z=z, confidence=confidence)
    out = runner.run(seed_state=seed)
    assert not out.extensions_json
    assert not runner.budget.extended


@pytest.mark.parametrize("limits,cost", [
    ({"daily_investigations": 1}, 0),
    ({"per_case_budget": 0.01}, 0.02),
    ({"daily_cost_budget": 0.01}, 0.02),
    ({"monthly_budget": 0.01}, 0.02),
])
def test_auto_extension_respects_each_effective_cap(budget_session, limits, cost):
    s = budget_session
    runner, seed, p = _budget_runner(s, limits=limits)
    if "per_case_budget" in limits:
        runner.budget.cost_usd = cost
    elif cost:
        s.add(LLMCall(product_id=p.id, agent="ask", cost=cost, tokens_in=0, tokens_out=0))
        s.flush()
    out = runner.run(seed_state=seed)
    assert not out.extensions_json


def test_auto_extension_counts_toward_the_existing_two_grant_cap(budget_session):
    runner, seed, _ = _budget_runner(budget_session)
    runner.budget.human_extensions = 2
    out = runner.run(seed_state=seed)
    assert not out.extensions_json


def test_auto_extension_hard_cost_cap_survives_checkpoint_restore(budget_session):
    from echolens.investigator.recover import _restored_budget
    s = budget_session
    runner, seed, _ = _budget_runner(s, limits={"per_case_budget": 0.26})
    out = runner.run(seed_state=seed)
    assert len(out.extensions_json or []) == 1
    budget = _restored_budget(out)
    assert budget.cap_cost_usd() <= 0.26
    assert budget.auto_extensions == 1


def test_settings_and_auto_extension_read_the_same_limits(budget_session):
    from echolens.api.app import _limits
    from echolens.orchestrator.queue import effective_limits
    s = budget_session
    p = Product(name="Settings", limits_json={"monthly_budget": 1.5, "daily_cost_budget": 0.3})
    s.add(p); s.flush()
    assert _limits(s, p.id) == effective_limits(s, p.id)
    assert _limits(s, p.id)["monthly_budget"] == 1.5


@pytest.fixture()
def ops_api(monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from echolens import auth
    from echolens.config import settings
    from echolens.db import session as db_session
    from echolens.db.models import User
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", factory)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "ops-test-secret-with-at-least-thirty-two-characters")
    with factory() as s:
        products = [Product(name="Ops One"), Product(name="Ops Two")]
        users = [User(email=f"{r}@ops.local", password_hash="unused", role=r) for r in ("admin", "reviewer")]
        s.add_all(products + users); s.commit()
        pids = [p.id for p in products]
        tokens = [auth.create_token(u) for u in users]
    import echolens.api.app as app_mod
    app_mod.limiter.reset()
    clients = [TestClient(app_mod.app) for _ in users]
    for tc, token in zip(clients, tokens):
        tc.cookies.set(auth.SESSION_COOKIE, token); tc.cookies.set(auth.CSRF_COOKIE, "ops-csrf")
        tc.headers["X-CSRF-Token"] = "ops-csrf"
    yield clients, pids, factory, app_mod
    for tc in clients: tc.close()
    engine.dispose()


def test_reset_endpoint_is_admin_csrf_scoped_and_replays_without_duplicates(ops_api, monkeypatch):
    from echolens.collectors import registry
    from echolens.collectors.play_store import PlayStoreCollector
    from echolens.db.models import CollectorState, Review
    (admin, reviewer), (pid, other), factory, _ = ops_api
    rows = [{"reviewId": "ops-r1", "score": 1, "content": "battery drain", "at": datetime.now(timezone.utc)}]
    fetched = []
    def fetch():
        fetched.append(True); return rows
    monkeypatch.setitem(registry._BUILDERS, "play_store", lambda ident, product:
        PlayStoreCollector(ident, product, fetch_fn=fetch))
    with factory() as s:
        s.add(CollectorState(source="play_store", identifier="ops.app", product="Ops One",
                            product_id=pid, enabled=True, status="healthy", watermark="old"))
        s.commit()
    body = {"source": "play_store", "identifier": "ops.app", "product_id": pid}
    assert reviewer.post("/collectors/reset", json=body).status_code == 403
    assert admin.post("/collectors/reset", json={**body, "product_id": other}).status_code == 404
    first = admin.post("/collectors/reset", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["inserted"] == 1 and first.json()["fetched"] == 1
    again = admin.post("/collectors/reset", json=body)
    assert again.json()["inserted"] == 0 and again.json()["skipped_duplicate"] == 1
    with factory() as s:
        assert s.query(Review).count() == 1
        s.query(CollectorState).update({"status": "running"}); s.commit()
    assert admin.post("/collectors/reset", json=body).status_code == 409
    assert len(fetched) == 2
    del admin.headers["X-CSRF-Token"]
    assert admin.post("/collectors/reset", json=body).status_code == 403


def test_digest_endpoint_returns_incident_count_and_deduplicates_runs(ops_api, monkeypatch):
    from echolens import notify
    (admin, _), (pid, _), factory, _ = ops_api
    now = datetime.now(timezone.utc)
    with factory() as s:
        for slug, typ, z in [("ops-spike", "negative_review_spike", 4), ("ops-rating", "rating_drop", 3)]:
            a = AnomalyEvent(slug=slug, product_id=pid, type=typ, metric="rating", z=z, delta=.5,
                window="7d", window_start=now-timedelta(days=7), window_end=now, status="closed")
            s.add(a); s.flush()
            inv = Investigation(anomaly_id=a.id, product_id=pid, status="resolved", budget_tier="quick")
            s.add(inv); s.flush()
            s.add(Finding(investigation_id=inv.id, product_id=pid, summary="Rating finding", confidence=.9,
                          json={"summary": "Rating finding", "confidence": .9, "impact": {"impact_score": .8}}))
        s.commit()
    deliveries = []
    monkeypatch.setattr(notify, "_send_slack", lambda payload, post_fn=None: deliveries.append(payload) or True)
    monkeypatch.setattr(notify, "_send_email", lambda *args, **kw: True)
    first = admin.post(f"/alerts/digest?product_id={pid}")
    assert first.status_code == 200
    assert first.json()["count"] == 1 and first.json()["finding_count"] == 2
    assert "2 signals" in deliveries[0]["blocks"][1]["text"]["text"]
    assert admin.post(f"/alerts/digest?product_id={pid}").json()["sent"] is False
    assert len(deliveries) == 1


def test_auto_extension_reason_is_visible_in_case_history(budget_session):
    from echolens.api.app import _extension_history
    runner, seed, _ = _budget_runner(budget_session)
    out = runner.run(seed_state=seed)
    events = [e for e in _extension_history(budget_session, out) if e["kind"] == "extended"]
    assert len(events) == 1 and events[0]["by"] == "auto"
    assert "confidence" in events[0]["note"]


def test_high_impact_finding_qualifies_without_a_sev1_signal(budget_session):
    from echolens.investigator.recover import automatic_extension_offer
    s = budget_session
    runner, seed, _ = _budget_runner(s, z=1, confidence=.9)
    # A previous measured high-impact finding can qualify this exhausted case.
    runner.inv.status = "budget_exhausted"
    runner.inv.checkpoint_json = {"hypotheses": seed["hypotheses"], "budget": {"iterations": 5}}
    s.add(Finding(investigation_id=runner.inv.id, product_id=runner.inv.product_id, confidence=.9,
                  status="draft", summary="High impact", json={"impact": {"impact_score": .9}}))
    s.flush()
    assert automatic_extension_offer(s, runner.inv)["eligible"] is True


def test_another_calls_spend_stops_an_already_granted_auto_extension(budget_session):
    s = budget_session
    runner, seed, p = _budget_runner(s)
    calls = []
    scripted = runner.llm.complete_json
    def complete(*args):
        calls.append(args[3]); return scripted(*args)
    runner.llm.complete_json = complete
    def on_step(kind, content):
        if content.get("text", "").startswith("Automatic +"):
            s.add(LLMCall(product_id=p.id, agent="ask", cost=25, tokens_in=0, tokens_out=0)); s.flush()
    runner.on_step = on_step
    out = runner.run(seed_state=seed)
    assert len(out.extensions_json or []) == 1
    assert len(calls) == 2, "no paid work after another caller consumes the monthly budget"
    assert out.status == "budget_exhausted"


def test_legacy_automatic_extension_is_not_granted_another_auto_budget(budget_session):
    runner, seed, _ = _budget_runner(budget_session)
    runner.budget.extended = True
    runner.budget.extension_factor = 1.5
    runner.budget.iterations = 7
    out = runner.run(seed_state=seed)
    assert not out.extensions_json



"""Incident alert routing regressions; all delivery is injected."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from echolens import notify
from echolens.config import settings
from echolens.db.models import AnomalyEvent, Base, Finding, Investigation, Product, TriageDecision

ALERTS_NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.fixture
def alerts_session(monkeypatch):
    for name, value in {"alerts_enabled": True, "slack_webhook_url": "https://fake.invalid/slack",
                        "smtp_host": "fake.invalid", "alert_email_to": "pm@example.invalid",
                        "app_base_url": "https://echolens.example", "alert_instant_min_severity": .5}.items():
        monkeypatch.setattr(settings, name, value)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([Product(id=1, name="one"), Product(id=2, name="two")])
        session.flush()
        yield session
    engine.dispose()


def alerts_signal(session, slug, *, kind="negative_review_spike", z=4., product_id=1, merged_into_id=None):
    row = AnomalyEvent(slug=slug, type=kind, metric="battery share of reviews", delta=2., z=z,
                       window="week", product_id=product_id, status="closed",
                       window_start=ALERTS_NOW-timedelta(days=7), window_end=ALERTS_NOW, merged_into_id=merged_into_id)
    session.add(row)
    session.flush()
    return row


def alerts_finding(session, anomaly, *, impact=.9):
    inv = Investigation(anomaly_id=anomaly.id, product_id=anomaly.product_id, status="resolved")
    session.add(inv)
    session.flush()
    row = Finding(investigation_id=inv.id, product_id=anomaly.product_id, summary="Battery finding",
                  confidence=.9, json={"summary": "Battery finding", "confidence": .9,
                                       "impact": {"impact_score": impact}}, created_at=ALERTS_NOW)
    session.add(row)
    session.flush()
    return row


class AlertsDelivery:
    def __init__(self):
        self.slack, self.email = [], []
        self.slack_ok, self.email_ok = True, True

    def post(self, url, json):
        self.slack.append(json)
        return SimpleNamespace(status_code=200 if self.slack_ok else 503)

    def send(self, subject, body):
        self.email.append((subject, body))
        if not self.email_ok:
            raise OSError("temporary smtp failure")


def alerts_notify(session, row, delivery, **kwargs):
    kwargs.setdefault("as_of", ALERTS_NOW)
    return notify.notify_finding(session, row, slack_post_fn=delivery.post,
                                 email_send_fn=delivery.send, **kwargs)


def test_alerts_instant_collapses_group_with_lead_count_strength_and_link(alerts_session):
    first = alerts_signal(alerts_session, "first", z=4.)
    lead = alerts_signal(alerts_session, "lead", kind="rating_drop", z=6.)
    f1, f2 = alerts_finding(alerts_session, first), alerts_finding(alerts_session, lead)
    delivery = AlertsDelivery()
    alerts_notify(alerts_session, f1, delivery)
    alerts_notify(alerts_session, f2, delivery)
    assert len(delivery.slack) == len(delivery.email) == 1
    rendered = str(delivery.slack[0])
    for text in ("Average rating is falling", "2 signals", "z=6", "+1 related finding", f"/#/cases/{f2.investigation_id}"):
        assert text in rendered
        assert text in delivery.email[0][1]


def test_alerts_instant_dedup_persists_and_new_stronger_member_does_not_resend(alerts_session):
    from echolens.db.models import SentAlert
    first = alerts_signal(alerts_session, "first")
    row = alerts_finding(alerts_session, first)
    delivery = AlertsDelivery()
    alerts_notify(alerts_session, row, delivery)
    alerts_session.commit()
    alerts_session.expunge_all()
    stronger = alerts_signal(alerts_session, "stronger", kind="rating_drop", z=8.)
    alerts_notify(alerts_session, alerts_finding(alerts_session, stronger), delivery)
    assert len(delivery.slack) == len(delivery.email) == 1
    assert len(alerts_session.scalars(select(SentAlert)).all()) == 2


def test_alerts_instant_dedup_is_product_scoped(alerts_session):
    delivery = AlertsDelivery()
    for product_id in (1, 2):
        alerts_notify(alerts_session, alerts_finding(alerts_session, alerts_signal(alerts_session, f"p{product_id}", product_id=product_id)), delivery)
    assert len(delivery.slack) == len(delivery.email) == 2


def test_alerts_failed_channel_retries_without_resending_successful_channel(alerts_session):
    row = alerts_finding(alerts_session, alerts_signal(alerts_session, "first"))
    delivery = AlertsDelivery()
    delivery.email_ok = False
    result = alerts_notify(alerts_session, row, delivery)
    assert result["sent"] == ["slack"]
    alerts_session.commit()
    delivery.email_ok = True
    result = alerts_notify(alerts_session, row, delivery)
    assert result["sent"] == ["email"]
    assert len(delivery.slack) == 1 and len(delivery.email) == 2


def test_alerts_instant_window_is_rolling_24_hours(alerts_session):
    row = alerts_finding(alerts_session, alerts_signal(alerts_session, "first"))
    delivery = AlertsDelivery()
    alerts_notify(alerts_session, row, delivery, as_of=ALERTS_NOW)
    alerts_notify(alerts_session, row, delivery, as_of=ALERTS_NOW+timedelta(hours=23, minutes=59))
    assert len(delivery.slack) == 1
    alerts_notify(alerts_session, row, delivery, as_of=ALERTS_NOW+timedelta(hours=24))
    assert len(delivery.slack) == 2


def test_alerts_digest_uses_triage_merge_and_all_signal_statuses(alerts_session):
    first = alerts_signal(alerts_session, "first", kind="theme_volume_surge")
    second = alerts_signal(alerts_session, "second", kind="rating_drop", z=7.)
    third = alerts_signal(alerts_session, "third", kind="manual", z=3., merged_into_id=second.id)
    alerts_session.add(TriageDecision(anomaly_id=first.id, decision="merge", merge_into_anomaly_id=second.id))
    rows = [alerts_finding(alerts_session, a) for a in (first, second, third)]
    other = alerts_finding(alerts_session, alerts_signal(alerts_session, "other", product_id=2))
    delivery = AlertsDelivery()
    result = notify.notify_digest(alerts_session, rows, slack_post_fn=delivery.post, email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert result["count"] == 1 and result["finding_count"] == 3
    assert result["sent"] is True
    rendered = delivery.slack[0]["blocks"][1]["text"]["text"]
    assert len(rendered.splitlines()) == 1
    for text in ("Average rating is falling", "3 signals", "z=7", "+2 related findings", f"/#/cases/{rows[1].investigation_id}"):
        assert text in rendered and text in delivery.email[0][1]
    assert f"/#/cases/{other.investigation_id}" not in rendered
    result = notify.notify_digest(alerts_session, rows, slack_post_fn=delivery.post, email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert result["sent"] is False and result["suppressed"] == 1
    assert len(delivery.slack) == len(delivery.email) == 1


def test_alerts_digest_retries_only_failed_channel(alerts_session):
    row = alerts_finding(alerts_session, alerts_signal(alerts_session, "first"))
    delivery = AlertsDelivery()
    delivery.slack_ok = False
    result = notify.notify_digest(alerts_session, [row], slack_post_fn=delivery.post, email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert result["sent_channels"] == ["email"]
    alerts_session.commit()
    delivery.slack_ok = True
    result = notify.notify_digest(alerts_session, [row], slack_post_fn=delivery.post, email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert result["sent_channels"] == ["slack"]
    assert len(delivery.email) == 1 and len(delivery.slack) == 2


def test_alerts_instant_severity_gate_stays_ahead_of_delivery(alerts_session):
    delivery = AlertsDelivery()
    result = alerts_notify(alerts_session, alerts_finding(alerts_session, alerts_signal(alerts_session, "low"), impact=.1), delivery)
    assert result["routed"] == "digest"
    assert delivery.slack == delivery.email == []


def test_alerts_digest_does_not_join_nonoverlapping_windows_or_other_products(alerts_session):
    first = alerts_signal(alerts_session, "current")
    old = alerts_signal(alerts_session, "old", kind="rating_drop", z=9.)
    old.window_start = ALERTS_NOW - timedelta(days=30)
    old.window_end = ALERTS_NOW - timedelta(days=23)
    foreign = alerts_signal(alerts_session, "foreign", kind="rating_drop", z=12., product_id=2)
    # Invalid cross-product merge metadata must not disclose another product.
    first.merged_into_id = foreign.id
    alerts_session.add(TriageDecision(anomaly_id=old.id, decision="merge", merge_into_anomaly_id=foreign.id))
    rows = [alerts_finding(alerts_session, a) for a in (first, old)]
    alerts_finding(alerts_session, foreign)
    delivery = AlertsDelivery()
    result = notify.notify_digest(alerts_session, rows, slack_post_fn=delivery.post,
                                  email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert result["count"] == 2
    lines = delivery.slack[0]["blocks"][1]["text"]["text"].splitlines()
    assert len(lines) == 2 and all("1 signal" in line for line in lines)
    assert "z=12" not in str(delivery.slack)


def test_alerts_false_email_result_is_retryable(alerts_session):
    row = alerts_finding(alerts_session, alerts_signal(alerts_session, "first"))
    delivery = AlertsDelivery()
    result = notify.notify_finding(alerts_session, row, slack_post_fn=delivery.post,
                                   email_send_fn=lambda subject, body: False, as_of=ALERTS_NOW)
    assert result["sent"] == ["slack"]
    result = alerts_notify(alerts_session, row, delivery, as_of=ALERTS_NOW)
    assert result["sent"] == ["email"]
    assert len(delivery.slack) == len(delivery.email) == 1


@pytest.mark.parametrize("kind", ["instant", "digest"])
def test_alerts_stale_findings_never_inflate_snapshot_or_supply_case_link(alerts_session, kind):
    lead = alerts_signal(alerts_session, "stale-lead", kind="rating_drop", z=8.)
    member = alerts_signal(alerts_session, "fresh-member", z=4.)
    old = alerts_finding(alerts_session, lead)
    old.created_at = ALERTS_NOW - timedelta(days=10)
    fresh = alerts_finding(alerts_session, member)
    delivery = AlertsDelivery()
    if kind == "instant":
        alerts_notify(alerts_session, fresh, delivery, as_of=ALERTS_NOW)
        line = delivery.slack[0]["blocks"][1]["text"]["text"]
    else:
        notify.notify_digest(alerts_session, [fresh], slack_post_fn=delivery.post,
                             email_send_fn=delivery.send, as_of=ALERTS_NOW)
        line = delivery.slack[0]["blocks"][1]["text"]["text"]
    assert "Average rating is falling | 2 signals | strongest z=8" in line
    assert f"/#/cases/{fresh.investigation_id}" in line
    assert f"/#/cases/{old.investigation_id}" not in line
    assert "related finding" not in line
    assert "?" not in line
    assert f"/#/cases/{old.investigation_id}" not in delivery.email[0][1]


def test_alerts_digest_excludes_unselected_recent_findings(alerts_session):
    lead = alerts_signal(alerts_session, "lead", kind="rating_drop", z=8.)
    excluded = alerts_finding(alerts_session, lead)
    selected = alerts_finding(alerts_session, alerts_signal(alerts_session, "member"))
    delivery = AlertsDelivery()
    notify.notify_digest(alerts_session, [selected], slack_post_fn=delivery.post,
                         email_send_fn=delivery.send, as_of=ALERTS_NOW)
    line = delivery.slack[0]["blocks"][1]["text"]["text"]
    assert "related finding" not in line
    assert f"/#/cases/{excluded.investigation_id}" not in line
    assert f"/#/cases/{selected.investigation_id}" in line


def test_alerts_single_signal_grammar_and_ascii_digest_header(alerts_session):
    row = alerts_finding(alerts_session, alerts_signal(alerts_session, "single"))
    delivery = AlertsDelivery()
    notify.notify_digest(alerts_session, [row], slack_post_fn=delivery.post,
                         email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert delivery.slack[0]["blocks"][0]["text"]["text"] == "EchoLens digest | 1 incident"
    line = delivery.slack[0]["blocks"][1]["text"]["text"]
    assert " | 1 signal | " in line
    assert "+0" not in line


"""Source reset contracts; all fetches and databases are local test fixtures."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from echolens.collectors import registry
from echolens.collectors.play_store import PlayStoreCollector
from echolens.db.models import Base, CollectorState, Review


@pytest.fixture
def reset_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reset.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session, factory
    engine.dispose()


def _reset_configured(session, *, product="Product A", product_id=11, status="healthy"):
    state = CollectorState(source="play_store", identifier="com.example.app",
                           product=product, product_id=product_id, enabled=True,
                           status=status, watermark="2026-07-20T00:00:00+00:00",
                           items_last_run=8, last_error="old failure")
    session.add(state)
    session.commit()
    return state


def _reset_review(native_id, day):
    return {"reviewId": native_id, "score": 1, "content": native_id,
            "at": datetime(2026, 7, day, tzinfo=timezone.utc)}


def test_reset_replays_old_rows_keeps_feedback_and_deduplicates(reset_db):
    session, _ = reset_db
    state = _reset_configured(session)
    state.watermark = None
    PlayStoreCollector(state.identifier, state.product,
                       fetch_fn=lambda: [_reset_review("kept", 12)]).run(session)
    state.watermark = "2026-07-20T00:00:00+00:00"
    session.commit()
    kept_id = session.scalars(select(Review.id)).one()

    result = registry.reset_source(session, state.source, state.identifier, 11,
                                   fetch_fn=lambda: [_reset_review("kept", 12), _reset_review("older", 14)])

    assert (result.fetched, result.inserted, result.skipped_duplicate) == (2, 1, 1)
    assert result.error is None
    assert session.scalars(select(Review.id).where(Review.ext_id == "gp_kept")).one() == kept_id
    assert len(session.scalars(select(Review)).all()) == 2
    session.refresh(state)
    assert state.status == "healthy"
    assert state.watermark == "2026-07-14T00:00:00+00:00"
    assert state.last_error is None
    assert state.items_last_run == 1


def test_reset_claim_is_visible_and_blocks_concurrent_reset_before_fetch_returns(reset_db):
    session, factory = reset_db
    state = _reset_configured(session)

    def fetch():
        with factory() as observer:
            visible = observer.get(CollectorState, state.id)
            assert visible.status == "running"
            assert visible.watermark is None
            assert visible.last_error is None
            assert visible.last_run_at is not None
            with pytest.raises(RuntimeError, match="running|collecting"):
                registry.reset_source(observer, state.source, state.identifier, 11,
                                      fetch_fn=lambda: pytest.fail("second fetch must not start"))
        return [_reset_review("old", 12)]

    result = registry.reset_source(session, state.source, state.identifier, 11, fetch_fn=fetch)
    assert result.error is None
    assert result.inserted == 1


def test_reset_running_source_preserves_watermark(reset_db):
    session, _ = reset_db
    state = _reset_configured(session, status="running")
    with pytest.raises(RuntimeError, match="running|collecting"):
        registry.reset_source(session, state.source, state.identifier, 11,
                              fetch_fn=lambda: pytest.fail("busy source must not fetch"))
    session.refresh(state)
    assert state.watermark == "2026-07-20T00:00:00+00:00"


@pytest.mark.parametrize("source,identifier,product_id", [
    ("play_store", "com.example.app", 22),
    ("play_store", "missing.app", 11),
    ("github", "com.example.app", 11),
    ("play_store", "com.example.app", None),
])
def test_reset_requires_exact_reset_configured_source(reset_db, source, identifier, product_id):
    session, _ = reset_db
    state = _reset_configured(session)
    with pytest.raises(LookupError):
        registry.reset_source(session, source, identifier, product_id,
                              fetch_fn=lambda: pytest.fail("missing source must not fetch"))
    session.refresh(state)
    assert state.watermark == "2026-07-20T00:00:00+00:00"
    assert len(session.scalars(select(CollectorState)).all()) == 1


def test_reset_disabled_source_is_not_reenabled(reset_db):
    session, _ = reset_db
    state = _reset_configured(session)
    state.enabled = False
    session.commit()
    with pytest.raises(LookupError):
        registry.reset_source(session, state.source, state.identifier, 11, fetch_fn=lambda: [])
    session.refresh(state)
    assert state.enabled is False
    assert state.watermark == "2026-07-20T00:00:00+00:00"


def test_reset_rejects_unsupported_source(reset_db):
    session, _ = reset_db
    with pytest.raises(ValueError, match="unknown source"):
        registry.reset_source(session, "reddit", "example", 11, fetch_fn=lambda: [])


def test_reset_only_changes_target_product(reset_db):
    session, _ = reset_db
    target = _reset_configured(session)
    other = _reset_configured(session, product="Product B", product_id=22)
    result = registry.reset_source(session, target.source, target.identifier, 11,
                                   fetch_fn=lambda: [_reset_review("shared", 12)])
    assert result.inserted == 1
    session.refresh(other)
    assert other.status == "healthy"
    assert other.watermark == "2026-07-20T00:00:00+00:00"
    assert session.scalars(select(Review.product)).all() == ["Product A"]


def test_reset_fetch_failure_records_terminal_error(reset_db):
    session, _ = reset_db
    state = _reset_configured(session)

    def broken():
        raise OSError("offline fixture")

    result = registry.reset_source(session, state.source, state.identifier, 11, fetch_fn=broken)
    assert "offline fixture" in result.error
    session.refresh(state)
    assert state.status == "error"
    assert "offline fixture" in state.last_error
    assert state.watermark is None
    assert state.items_last_run == 0


def test_reset_obeys_normal_backfill_limit(reset_db):
    session, _ = reset_db
    state = _reset_configured(session)
    payload = [_reset_review(str(i), 12) for i in range(350)]
    result = registry.reset_source(session, state.source, state.identifier, 11, fetch_fn=lambda: payload)
    assert (result.fetched, result.inserted) == (300, 300)


def test_reset_reuses_bounded_fetch_timeout(reset_db, monkeypatch):
    import threading
    session, _ = reset_db
    state = _reset_configured(session)
    finished = threading.Event()
    monkeypatch.setattr(registry, "COLLECTOR_TIMEOUT_S", 0.02)
    try:
        result = registry.reset_source(session, state.source, state.identifier, 11,
                                       fetch_fn=lambda: finished.wait(1) or [])
        assert "timed out" in result.error
        session.refresh(state)
        assert state.status == "error"
        assert state.watermark is None
    finally:
        finished.set()

def test_reset_concurrent_claims_start_only_one_fetch(reset_db):
    """Both requests read the idle row before either tries to reserve it."""
    import threading
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    from sqlalchemy import event

    session, factory = reset_db
    state = _reset_configured(session)
    engine = session.get_bind()
    reads = threading.Barrier(2)
    fetched = threading.Event()
    release = threading.Event()
    seen_threads = set()
    fetch_calls = []

    def synchronize_initial_read(conn, cursor, statement, parameters, context, many):
        thread_id = threading.get_ident()
        if statement.startswith("SELECT collector_state.") and thread_id not in seen_threads:
            seen_threads.add(thread_id)
            reads.wait(timeout=3)

    def fetch():
        fetch_calls.append(True)
        fetched.set()
        assert release.wait(timeout=3), "test must release the winning fetch"
        return [_reset_review("raced", 12)]

    def reset():
        with factory() as worker:
            try:
                return registry.reset_source(worker, state.source, state.identifier, 11, fetch_fn=fetch)
            except RuntimeError as error:
                return str(error)

    event.listen(engine, "after_cursor_execute", synchronize_initial_read)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(reset) for _ in range(2)]
            try:
                assert fetched.wait(timeout=3), "one reset must start fetching"
                done, _ = wait(futures, timeout=3, return_when=FIRST_COMPLETED)
                assert len(done) == 1, "the other reset must promptly report busy"
                assert "already collecting" in next(iter(done)).result()
            finally:
                release.set()
            results = [future.result(timeout=3) for future in futures]
    finally:
        event.remove(engine, "after_cursor_execute", synchronize_initial_read)
    assert len(fetch_calls) == 1
    successful = [result for result in results if not isinstance(result, str)]
    assert len(successful) == 1
    assert successful[0].inserted == 1


def test_instant_then_digest_does_not_send_same_incident_again(alerts_session):
    s = alerts_session
    anomaly = alerts_signal(s, "cross-mode")
    finding = alerts_finding(s, anomaly)
    delivery = AlertsDelivery()
    alerts_notify(s, finding, delivery)
    result = notify.notify_digest(s, [finding], slack_post_fn=delivery.post,
                                 email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert result["sent"] is False
    assert len(delivery.slack) == 1 and len(delivery.email) == 1


def test_automatic_resume_records_cost_on_the_resumed_budget(budget_session, monkeypatch):
    from echolens.llm import openai_client
    from sqlalchemy import func
    s = budget_session
    runner, seed, _ = _budget_runner(s)
    scripted = runner.llm
    def fake_client(on_call):
        class MeteredScript:
            def complete_json(self, system, user, schema, agent):
                result = scripted.complete_json(system, user, schema, agent)
                on_call(agent, "scripted", result.tokens_in, result.tokens_out, .01, result.ms)
                return result
        return MeteredScript()
    monkeypatch.setattr(openai_client, "OpenAIClient", fake_client)
    # Production uses the default-owned client. All IO here is still scripted.
    production = Investigator(s, runner.anomaly, tier="quick")
    production.budget.iterations = 4
    out = production.run(seed_state=seed)
    cost = s.scalar(select(func.sum(LLMCall.cost)).where(LLMCall.investigation_id == out.id))
    assert len(out.extensions_json or []) == 1
    assert out.checkpoint_json["budget"]["cost_usd"] == pytest.approx(cost)
    assert out.checkpoint_json["budget"]["tokens"] == 4 * 250


def test_lowered_product_cap_is_reloaded_during_a_running_case(budget_session):
    from echolens.investigator.recover import automatic_extension_offer
    from sqlalchemy import update
    s = budget_session
    runner, seed, product = _budget_runner(s)
    runner.inv.status = "budget_exhausted"
    runner.inv.checkpoint_json = {"hypotheses": seed["hypotheses"], "budget": {"iterations": 5}}
    s.commit()
    with sessionmaker(bind=s.bind)() as other:
        other.execute(update(Product).where(Product.id == product.id).values(limits_json={"monthly_budget": 0}))
        other.commit()
    offer = automatic_extension_offer(s, runner.inv)
    assert offer["eligible"] is False and "Monthly" in offer["reason"]


def test_ledger_ahead_of_checkpoint_blocks_per_case_auto_spend(budget_session):
    from echolens.investigator.recover import automatic_extension_offer, auto_budget_room, _restored_budget
    from echolens.investigator import guards
    s = budget_session
    runner, seed, product = _budget_runner(s, limits={"per_case_budget": .10})
    runner.inv.status = "budget_exhausted"
    runner.inv.checkpoint_json = {"hypotheses": seed["hypotheses"],
        "budget": {"iterations": 5, "cost_usd": .05, "tokens": 100}}
    s.add(LLMCall(investigation_id=runner.inv.id, product_id=product.id, agent="investigator.plan",
                  cost=.15, tokens_in=60000, tokens_out=100))
    s.flush()
    offer = automatic_extension_offer(s, runner.inv)
    assert offer["eligible"] is False and "Per-case" in offer["reason"]
    restored = _restored_budget(runner.inv)
    restored.cost_ceiling_usd = .10
    auto_budget_room(s, runner.inv, restored)
    assert restored.cost_usd == .15 and restored.tokens == 60100
    assert guards.budget_exceeded(restored)


def test_large_digest_is_bounded_without_dropping_incidents(alerts_session):
    from echolens.db.models import SentAlert
    rows = []
    for i in range(60):
        signal = alerts_signal(alerts_session, f"manual-{i}", kind="manual")
        signal.description = f"Complaint {i}: " + "detail " * 30
        rows.append(alerts_finding(alerts_session, signal))
    delivery = AlertsDelivery()
    def bounded_slack(url, json):
        assert all(len(b["text"]["text"]) <= 3000 for b in json["blocks"] if "text" in b)
        return delivery.post(url, json)
    result = notify.notify_digest(alerts_session, rows, slack_post_fn=bounded_slack,
                                  email_send_fn=delivery.send, as_of=ALERTS_NOW)
    assert "slack" in result["sent_channels"]
    assert alerts_session.query(SentAlert).filter_by(channel="slack").count() == 60


def test_automatic_grants_reserve_headroom_for_other_running_cases(budget_session):
    from echolens.investigator.recover import automatic_extension_offer
    s = budget_session
    runner, seed, product = _budget_runner(s, limits={"monthly_budget": .05})
    runner.inv.status = "budget_exhausted"
    runner.inv.checkpoint_json = {"hypotheses": seed["hypotheses"], "budget": {"iterations": 5}}
    other_anomaly = AnomalyEvent(slug="second-critical", product_id=product.id, type="rating_drop",
        metric="rating", z=4, delta=.5, window="7d", description="rating drop", status="budget_exhausted")
    s.add(other_anomaly); s.flush()
    other = Investigation(anomaly_id=other_anomaly.id, product_id=product.id, status="budget_exhausted",
        budget_tier="quick", checkpoint_json={"hypotheses": seed["hypotheses"], "budget": {"iterations": 5}})
    s.add(other); s.flush()
    grant_extension(s, runner.inv, by="auto")
    offer = automatic_extension_offer(s, other)
    assert offer["eligible"] is False
    assert "Monthly" in offer["reason"]


def test_stale_session_cannot_grant_the_same_case_twice(budget_session):
    s = budget_session
    runner, seed, _ = _budget_runner(s)
    runner.inv.status = "budget_exhausted"
    runner.inv.checkpoint_json = {"hypotheses": seed["hypotheses"], "budget": {"iterations": 5}}
    s.commit()
    with sessionmaker(bind=s.bind, expire_on_commit=False)() as stale_session:
        stale = stale_session.get(Investigation, runner.inv.id)
        grant_extension(s, runner.inv, by="auto"); s.commit()
        with pytest.raises(ValueError):
            grant_extension(stale_session, stale, by="auto")
    s.refresh(runner.inv)
    assert len(runner.inv.extensions_json) == 1
