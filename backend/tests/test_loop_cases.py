"""Manual fixes, human priors, duplicate cases and quiet weekly delivery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import auth, cases, fixwatch, review
from echolens.config import settings
from echolens.brief import weekly_brief
from echolens.db import session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, CollectorState, EvidenceRow, Finding, FixWatch, Investigation,
    Product, Review, ReviewFeedback, User)
from echolens.investigator.memory import digest_for, digest_text

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture()
def s(factory):
    with factory() as session:
        yield session


def case(s, product="Lumo", *, age=2, status="resolved", summary="Battery drains overnight"):
    p = s.scalars(select(Product).where(Product.name == product)).first()
    if p is None:
        p = Product(name=product)
        s.add(p)
        s.flush()
    a = AnomalyEvent(slug=f"battery-{product}-{s.query(AnomalyEvent).count()}",
                     product_id=p.id, type="manual", metric="battery drain",
                     description="Battery drains overnight", delta=1, z=3, window="7d")
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, product_id=p.id, status=status,
                        created_at=NOW - timedelta(days=age))
    s.add(inv)
    s.flush()
    f = Finding(investigation_id=inv.id, product_id=p.id, summary=summary,
                confidence=.85, json={"supported_hypothesis": "H1", "summary": summary,
                                      "impact": {"terms": ["battery", "drain"]}})
    s.add(f)
    s.flush()
    return p, a, inv, f


def test_manual_fix_can_be_updated_then_verified_by_the_existing_watch(s):
    p, _, inv, f = case(s)
    s.add(CollectorState(source="play_store", identifier="test", product=p.name,
                         enabled=True, status="healthy", last_run_at=NOW + timedelta(days=30)))
    for d in range(-14, 0):
        s.add(Review(source="play_store", ext_id=f"old{d}", product=p.name,
                     rating=1, text="battery drain", created_at=NOW + timedelta(days=d)))
    s.flush()
    w = fixwatch.mark_shipped(s, f, NOW, note="Scheduler fix deployed")
    assert w.status == "watching" and w.baseline_rate > 0
    assert not w.issue_url and w.investigation_id == inv.id
    again = fixwatch.mark_shipped(s, f, NOW, note="Updated rollout note")
    assert again.id == w.id and s.query(FixWatch).count() == 1
    assert again.shipped_note == "Updated rollout note"
    fixwatch.evaluate(s, NOW + timedelta(days=14))
    assert w.status == "confirmed" and w.chart_json["fix_date"] == "2026-10-24"
    assert w.chart_json.get("window_start") != "issue_closed"
    events = cases.case_history(s, inv)
    assert not any(e["kind"] == "issue" for e in events)
    assert any(e["kind"] == "fix_shipped" and e["note"] == "Updated rollout note" for e in events)


def test_manual_fix_waits_for_the_fixed_version_and_preserves_issue_link(s):
    _, _, _, f = case(s)
    w = fixwatch.link_issue(s, f, "acme/lumo", 8, "https://example.test/8")
    result = fixwatch.mark_shipped(s, f, NOW, version="v3.2.1")
    assert result.id == w.id and w.issue_number == 8 and w.repo == "acme/lumo"
    assert w.status == "waiting_for_release" and w.fixed_in_version == "3.2.1"
    fixwatch.evaluate(s, NOW + timedelta(days=30))
    assert w.status == "waiting_for_release"
    with pytest.raises(ValueError):
        fixwatch.mark_shipped(s, f, NOW, version="tomorrow")
    assert w.fixed_in_version == "3.2.1"


def test_later_issue_link_keeps_the_manual_verification(s):
    _, _, _, f = case(s)
    w = fixwatch.mark_shipped(s, f, NOW, version="3.2.1")
    linked = fixwatch.link_issue(s, f, "acme/lumo", 12, "https://example.test/12")
    assert linked.id == w.id and linked.status == "waiting_for_release"
    assert linked.issue_number == 12 and s.query(FixWatch).count() == 1


def test_manual_version_verifies_and_earns_a_pattern_after_rollout(s):
    from echolens.patterns import patterns
    p, _, _, f = case(s)
    w = fixwatch.mark_shipped(s, f, NOW, version="3.2.1")
    s.add(CollectorState(source="play_store", identifier="manual-version", product=p.name,
                         enabled=True, status="healthy", last_run_at=NOW + timedelta(days=30)))
    for d in range(-14, 0):
        s.add(Review(source="play_store", ext_id=f"before{d}", product=p.name,
                     rating=1, text="battery drain", version="3.2.0", created_at=NOW + timedelta(days=d)))
    for i in range(10):
        s.add(Review(source="play_store", ext_id=f"after{i}", product=p.name, rating=5,
                     text="all good", version="3.2.1", created_at=NOW + timedelta(days=1, hours=i)))
    s.flush()
    assert not patterns(s, p.id)
    fixwatch.evaluate(s, NOW + timedelta(days=15))
    assert w.status == "confirmed"
    assert w.chart_json["window_start"] == "first_review_on_fixed_version"
    assert patterns(s, p.id)[0]["verified_count"] == 1


def test_challenge_cause_is_a_theme_scoped_human_prior_not_supported_evidence(s):
    p, anomaly, inv, f = case(s, summary="Wrong theory about the scheduler")
    review.record_challenge(s, f, "Checked the incident", reason="wrong_cause",
                            actual_cause="A retry timer held a wakelock")
    feedback = s.scalars(select(ReviewFeedback)).one()
    assert feedback.actual_cause == "A retry timer held a wakelock"
    prior = digest_for(s, anomaly)[0]
    assert prior["source"] == "human_provided" and prior["confidence"] is None
    assert prior["confirmed_cause"] == feedback.actual_cause
    text = digest_text(s, anomaly)
    assert "human-provided" in text and "not evidence" in text and feedback.actual_cause in text
    event = next(e for e in cases.case_history(s, inv) if e["kind"] == "challenged")
    assert event["actual_cause"] == feedback.actual_cause
    _, other, other_inv, _ = case(s, product="Other")
    assert not digest_for(s, other, exclude_investigation_id=other_inv.id)
    unrelated = AnomalyEvent(product_id=p.id, metric="checkout payments",
                             description="Duplicate charges at checkout")
    assert not digest_for(s, unrelated)


def test_single_channel_memory_does_not_claim_full_support(s):
    _, anomaly, _, f = case(s)
    f.json = {**f.json, "status": "supported_single_channel"}
    assert digest_for(s, anomaly)[0]["support"] == "single_channel"
    assert "single-channel" in digest_text(s, anomaly)


def test_memory_queries_are_bounded_by_recall_limit(s):
    for _ in range(20):
        _, anomaly, _, _ = case(s)
    statements = []
    def counted(*args):
        statements.append(args[2])
    event.listen(s.bind, "before_cursor_execute", counted)
    try:
        assert len(digest_for(s, anomaly, limit=3)) == 3
    finally:
        event.remove(s.bind, "before_cursor_execute", counted)
    assert len(statements) <= 8


def test_merge_links_evidence_keeps_both_histories_and_hides_duplicate(s):
    _, _, target, _ = case(s)
    _, _, source, _ = case(s)
    s.add(EvidenceRow(investigation_id=source.id, eid="ev_001", source="play_store",
                      ref="play_store:review1", snippet="Battery drains", retrieved_by="search"))
    s.flush()
    cases.merge_cases(s, source, target)
    assert source.status == "merged" and cases.merged_into(s, source.id) == target.id
    assert s.query(EvidenceRow).count() == 1
    linked = cases.related_evidence(s, target)
    assert linked[0]["source_case_id"] == source.id and linked[0]["ref"] == "play_store:review1"
    assert not s.scalars(select(EvidenceRow).where(EvidenceRow.investigation_id == target.id)).all()
    assert any(e["kind"] == "merged" and e["case_id"] == target.id
               for e in cases.case_history(s, source))
    assert any(e["kind"] == "merged" and e["case_id"] == source.id
               for e in cases.case_history(s, target))
    assert source.id not in [r["id"] for r in cases.case_rows(s, source.product_id)]
    cases.merge_cases(s, source, target)
    assert len([e for e in cases.case_history(s, target) if e["kind"] == "merged"]) == 1


def test_merge_refuses_other_products_self_and_running_cases(s):
    _, _, source, _ = case(s)
    _, _, other, _ = case(s, product="Other")
    with pytest.raises(ValueError, match="product"):
        cases.merge_cases(s, source, other)
    with pytest.raises(ValueError):
        cases.merge_cases(s, source, source)
    _, _, running, _ = case(s, status="running")
    with pytest.raises(ValueError):
        cases.merge_cases(s, source, running)
    assert source.status == "resolved"


def test_merge_chain_redirects_and_related_evidence_follows_the_chain(s):
    _, _, first, _ = case(s)
    _, _, second, _ = case(s)
    _, _, third, _ = case(s)
    s.add(EvidenceRow(investigation_id=first.id, eid="ev_001", source="play_store",
                      ref="play_store:nested", snippet="Battery drain", retrieved_by="search"))
    s.flush()
    cases.merge_cases(s, first, second)
    cases.merge_cases(s, second, third)
    assert cases.merged_into(s, first.id) == third.id
    assert cases.related_evidence(s, third)[0]["source_case_id"] == first.id
    with pytest.raises(ValueError):
        cases.merge_cases(s, third, first)


def test_merge_resolves_legacy_product_scope_and_refuses_legacy_cross_product(s):
    _, _, source, _ = case(s)
    _, _, target, _ = case(s)
    source.product_id = None
    target.product_id = None
    s.add(EvidenceRow(investigation_id=source.id, eid="ev_001", source="play_store",
                      ref="play_store:legacy", snippet="Battery drains", retrieved_by="search"))
    s.flush()
    cases.merge_cases(s, source, target)
    assert source.status == "merged"
    assert cases.related_evidence(s, target)[0]["ref"] == "play_store:legacy"
    _, _, other, _ = case(s, product="Other")
    _, _, fresh, _ = case(s)
    other.product_id = fresh.product_id = None
    s.flush()
    with pytest.raises(ValueError, match="product"):
        cases.merge_cases(s, fresh, other)


def test_stale_review_cannot_revive_a_merged_case(s):
    _, _, source, f = case(s)
    _, _, target, _ = case(s)
    cases.merge_cases(s, source, target)
    with pytest.raises(ValueError, match="merged"):
        review.approve(s, f)
    with pytest.raises(ValueError, match="merged"):
        review.record_challenge(s, f, "Stale review")
    assert source.status == "merged"


def test_quiet_brief_has_no_delivery_lines_but_old_open_work_still_gets_attention(s):
    quiet = weekly_brief(s, NOW)
    assert quiet["quiet"] and quiet["lines"] == []
    _, _, _, _ = case(s, age=30)
    attention = weekly_brief(s, NOW)
    assert not attention["quiet"] and attention["fix_next"]
    assert "Fix next" in " ".join(attention["lines"])
    assert "0 new" not in " ".join(attention["lines"])


def test_brief_only_includes_nonempty_sections(s):
    case(s)
    b = weekly_brief(s, NOW)
    assert not b["quiet"] and b["new_problems"]
    text = " ".join(b["lines"])
    assert "1 new problem" in text
    assert "0 fixes" not in text and "0 regressions" not in text


@pytest.mark.parametrize("decision", ["park", "wont_fix"])
def test_unchanged_chronic_work_with_no_open_action_is_quiet(s, decision):
    _, _, _, f = case(s, age=90)
    review.decide(s, f, decision, reason="By design")
    b = weekly_brief(s, NOW)
    assert b["quiet"] and b["lines"] == []


@pytest.fixture()
def client(factory, monkeypatch):
    from echolens.api import app as api_module
    monkeypatch.setattr(db_session, "_engine", factory.kw["bind"])
    monkeypatch.setattr(db_session, "_SessionLocal", factory)
    monkeypatch.setattr(api_module, "_spawn", lambda *a, **kw: None)
    return TestClient(api_module.app)


def test_api_manual_fix_and_merge_are_product_scoped(client, factory):
    with factory() as s:
        p, _, a, f = case(s)
        _, _, b, _ = case(s)
        _, _, other, _ = case(s, product="Other")
        s.commit()
        pid, fid, aid, bid, other_id = p.id, f.id, a.id, b.id, other.id
    assert client.post(f"/findings/{fid}/fix-shipped?product_id={pid}",
                       json={"date": "2026-10-24", "note": "Manual rollout"}).status_code == 200
    assert client.post(f"/investigations/{bid}/merge?product_id={pid}",
                       json={"target_id": other_id}).status_code in (404, 422)
    merged = client.post(f"/investigations/{bid}/merge?product_id={pid}", json={"target_id": aid})
    assert merged.status_code == 200 and merged.json()["merged_into_id"] == aid
    assert client.get(f"/investigations/{bid}?product_id={pid}").json()["merged_into_id"] == aid


def test_api_challenge_records_cause_without_external_investigation(client, factory):
    with factory() as s:
        p, _, inv, f = case(s)
        s.commit()
        pid, fid, inv_id = p.id, f.id, inv.id
    response = client.post(f"/findings/{fid}/review?product_id={pid}", json={
        "action": "challenge", "note": "We checked the incident", "actual_cause": "Retry timer never stopped"})
    assert response.status_code == 200
    history = client.get(f"/investigations/{inv_id}?product_id={pid}").json()["history"]
    assert next(e for e in history if e["kind"] == "challenged")["actual_cause"] == "Retry timer never stopped"


def test_api_rejects_invalid_shipment_and_stale_merged_review(client, factory):
    with factory() as s:
        p, _, source, f = case(s)
        _, _, target, _ = case(s)
        s.commit()
        pid, fid, source_id, target_id = p.id, f.id, source.id, target.id
    path = f"/findings/{fid}/fix-shipped?product_id={pid}"
    assert client.post(path, json={"version": "next week"}).status_code == 422
    assert client.post(path, json={"date": "2999-01-01"}).status_code == 422
    with factory() as s:
        assert s.query(FixWatch).count() == 0
    assert client.post(f"/investigations/{source_id}/merge?product_id={pid}",
                       json={"target_id": target_id}).status_code == 200
    assert client.post(f"/findings/{fid}/review?product_id={pid}", json={"action": "approve"}).status_code == 409
    assert client.post(f"/findings/{fid}/review?product_id={pid}",
                       json={"action": "challenge", "note": "Stale"}).status_code == 409


def test_additive_migration_keeps_manual_fixes_and_human_causes_writable(factory, monkeypatch):
    engine = factory.kw["bind"]
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE case_merges"))
        conn.execute(text("ALTER TABLE fix_watches DROP COLUMN shipped_at"))
        conn.execute(text("ALTER TABLE fix_watches DROP COLUMN shipped_note"))
        conn.execute(text("ALTER TABLE review_feedback DROP COLUMN actual_cause"))
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    db_session.init_db()
    db_session.init_db()
    with factory() as s:
        _, _, source, f = case(s)
        _, _, target, _ = case(s)
        fixwatch.mark_shipped(s, f, NOW, note="Migrated")
        review.record_challenge(s, f, "Corrected", actual_cause="A retry timer")
        # The challenged source is closed to review, but the new table is also writable.
        from echolens.db.models import CaseMerge
        s.add(CaseMerge(source_id=source.id, target_id=target.id))
        s.commit()
    with factory() as s:
        assert s.scalars(select(FixWatch)).one().shipped_note == "Migrated"
        assert s.scalars(select(ReviewFeedback)).one().actual_cause == "A retry timer"


@pytest.mark.parametrize("role", ["viewer", "reviewer"])
def test_mutations_need_reviewer_cookie_and_csrf(client, factory, monkeypatch, role):
    monkeypatch.setattr(settings, "echolens_env", "production")
    monkeypatch.setattr(settings, "jwt_secret", "loop-cases-test-secret-at-least-32-characters")
    with factory() as s:
        p, _, a, f = case(s)
        _, _, b, _ = case(s)
        user = User(email=f"{role}@example.test", password_hash="unused", role=role)
        s.add(user)
        s.commit()
        pid, fid, aid, bid, token = p.id, f.id, a.id, b.id, auth.create_token(user)
    client.cookies.set(auth.SESSION_COOKIE, token)
    client.cookies.set(auth.CSRF_COOKIE, "loop-csrf")
    routes = [(f"/findings/{fid}/fix-shipped?product_id={pid}", {}),
              (f"/investigations/{bid}/merge?product_id={pid}", {"target_id": aid})]
    for path, body in routes:
        assert client.post(path, json=body).status_code == 403
    client.headers["X-CSRF-Token"] = "loop-csrf"
    for path, body in routes:
        assert client.post(path, json=body).status_code == (200 if role == "reviewer" else 403)


@pytest.mark.parametrize("products", [0, 1, 2])
def test_scheduled_send_skips_quiet_workspaces(client, factory, monkeypatch, products):
    from echolens import notify
    with factory() as s:
        s.add_all([Product(name=f"Quiet {i}") for i in range(products)])
        s.commit()
    def unexpected(*a, **kw):
        pytest.fail("quiet brief attempted external delivery")
    monkeypatch.setattr(notify, "_send_slack", unexpected)
    monkeypatch.setattr(notify, "_send_email", unexpected)
    response = client.post("/brief/send")
    assert response.status_code == 200
    assert response.json()["skipped"] == "quiet_week"
