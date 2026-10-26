"""Product-owned human hints and saved-plan ticket exports; no live services."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens import backlog, brain
from echolens.db.models import Base, Product, AnomalyEvent, Investigation, Finding, ReviewFeedback, User
from echolens.investigator.memory import digest_text


@pytest.fixture()
def s():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


def seed(s, name="One"):
    p = Product(name=name)
    s.add(p)
    s.flush()
    a = AnomalyEvent(slug=name, type="volume_spike", metric="sync", description="sync fails",
                     delta=1, z=3, window="7d", status="investigating", product_id=p.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", product_id=p.id)
    s.add(inv)
    s.flush()
    f = Finding(investigation_id=inv.id, product_id=p.id, status="approved", confidence=.8,
                summary="Sync fails", json={"summary": "Sync fails", "impact": {
                    "affected_volume": 5, "affected_pct": 20, "impact_score": .6,
                    "rating_impact": .2}})
    s.add(f)
    s.flush()
    return p, a, inv, f


def test_rules_are_editable_scoped_hints_and_retirement_stops_seeding(s):
    p, a, inv, _ = seed(s)
    other, *_ = seed(s, "Other")
    rule = brain.add_rule(s, p.id, " Sync requires foreground access ", "owner@example.test")
    assert rule["text"] == "Sync requires foreground access"
    assert rule["origin"] == "team" and rule["status"] == "active"
    assert brain.rules(s, other.id) == []
    assert brain.update_rule(s, other.id, rule["id"], text="stolen") is None
    brain.update_rule(s, p.id, rule["id"], text="Sync requires network access")
    hint = digest_text(s, a, exclude_investigation_id=inv.id)
    assert "Sync requires network access" in hint
    assert "not evidence" in hint
    assert "supported finding" not in hint
    brain.update_rule(s, p.id, rule["id"], status="retired")
    assert digest_text(s, a) is None
    assert brain.rules(s, p.id)[0]["author"] == "owner@example.test"


def test_corrections_import_once_keep_audit_and_respect_edits_and_retirement(s):
    p, a, inv, f = seed(s)
    user = User(email="reviewer@example.test", password_hash="unused", role="reviewer")
    s.add(user)
    s.flush()
    s.add(ReviewFeedback(finding_id=f.id, action="challenge", actual_cause="Sync token expired",
                         user_id=user.id, created_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    s.flush()
    first = brain.rules(s, p.id)
    assert len(first) == 1 and first[0]["case_id"] == inv.id
    assert first[0]["origin"] == "correction" and first[0]["author"] == user.email
    assert first[0]["created_at"].startswith("2026-10-01")
    assert brain.rules(s, p.id) == first
    brain.update_rule(s, p.id, first[0]["id"], text="Sync credentials expired", status="retired")
    assert brain.human_cause_priors(s, p.id) == []
    assert brain.rules(s, p.id)[0]["text"] == "Sync credentials expired"


def test_export_requires_saved_plan_and_reuses_successes(s):
    p, _, inv, _ = seed(s)
    with pytest.raises(ValueError, match="Save"):
        backlog.export_plan(s, p.id, "github", repo="one/repo", post_fn=lambda *a: {})
    backlog.save_plan(s, p.id, included=[inv.id], excluded=[])
    s.commit()
    def post(repo, title, body, token, labels):
        assert repo == "one/repo" and "Evidence" in body
        return {"number": 7, "html_url": "https://github.test/7"}
    from echolens.config import settings
    old = settings.github_token
    settings.github_token = "fake"
    try:
        first = backlog.export_plan(s, p.id, "github", repo="one/repo", post_fn=post)
        again = backlog.export_plan(s, p.id, "github", repo="one/repo",
                                    post_fn=lambda *a: pytest.fail("duplicate ticket"))
    finally:
        settings.github_token = old
    assert first["results"][0]["status"] == "created"
    assert again["results"][0]["status"] == "existing"
    assert again["results"][0]["url"] == "https://github.test/7"


def test_export_does_not_re_rank_unsaved_items_or_cross_products(s, monkeypatch):
    from echolens.config import settings
    monkeypatch.setattr(settings, "github_token", "fake")
    p, _, inv, _ = seed(s)
    other, _, other_inv, _ = seed(s, "Other")
    backlog.save_plan(s, p.id, included=[inv.id, other_inv.id], excluded=[])
    # A new finding after Save never joins the exported selection.
    a = AnomalyEvent(slug="later", type="volume_spike", metric="crashes", description="new",
                     delta=1, z=3, window="7d", product_id=p.id)
    s.add(a)
    s.flush()
    later = Investigation(anomaly_id=a.id, status="resolved", product_id=p.id)
    s.add(later)
    s.flush()
    s.add(Finding(investigation_id=later.id, product_id=p.id, status="approved", confidence=.8,
                  summary="Later", json={"summary": "Later", "impact": {}}))
    s.commit()
    result = backlog.export_plan(s, p.id, "github", repo="one/repo",
        post_fn=lambda *a: {"number": 8, "html_url": "https://github.test/8"})
    assert [r["key"] for r in result["results"]] == [inv.id]


def test_export_ambiguous_failure_is_held_while_other_items_finish(s, monkeypatch):
    from echolens.config import settings
    monkeypatch.setattr(settings, "github_token", "fake")
    p, _, inv, _ = seed(s)
    backlog.save_plan(s, p.id, included=[inv.id], excluded=[])
    s.commit()
    def timeout(*args):
        raise TimeoutError("sensitive upstream response")
    result = backlog.export_plan(s, p.id, "github", repo="one/repo", post_fn=timeout)
    assert result["results"][0]["status"] == "failed"
    assert "sensitive" not in result["results"][0]["error"]
    again = backlog.export_plan(s, p.id, "github", repo="one/repo",
                                post_fn=lambda *a: pytest.fail("unsafe retry"))
    assert again["results"][0]["status"] == "failed"


def test_rules_and_export_api_permissions_validation_and_ownership(s, monkeypatch):
    from contextlib import contextmanager
    from fastapi.testclient import TestClient
    from echolens.api import app as api
    from echolens.auth import current_user

    p, _, inv, _ = seed(s)
    other, *_ = seed(s, "Other")
    @contextmanager
    def sessions():
        yield s
    monkeypatch.setattr(api, "session_scope", sessions)
    api.app.dependency_overrides[current_user] = lambda: {"role": "reviewer", "email": "r@test"}
    try:
        client = TestClient(api.app)
        response = client.post(f"/brain/rules?product_id={p.id}", json={"text": "Sync uses wifi"})
        assert response.status_code == 200
        rule = response.json()
        assert rule["author"] == "r@test"
        assert client.get(f"/brain/rules?product_id={other.id}").json() == {"rules": []}
        assert client.patch(f"/brain/rules/{rule['id']}?product_id={other.id}",
                            json={"status": "retired"}).status_code == 404
        assert client.post(f"/brain/rules?product_id={p.id}", json={"text": "  "}).status_code == 422
        assert client.patch(f"/brain/rules/{rule['id']}?product_id={p.id}",
                            json={"status": "made_up"}).status_code == 422
        api.app.dependency_overrides[current_user] = lambda: {"role": "viewer"}
        assert client.post(f"/brain/rules?product_id={p.id}", json={"text": "x"}).status_code == 403
        assert client.post(f"/backlog/plan/export?product_id={p.id}",
                           json={"tracker": "github", "kind": "bugs"}).status_code == 403
    finally:
        api.app.dependency_overrides.clear()


def test_export_reuses_existing_case_ticket(s, monkeypatch):
    from echolens.config import settings
    from echolens.fixwatch import link_issue
    monkeypatch.setattr(settings, "github_token", "fake")
    p, _, inv, finding = seed(s)
    link_issue(s, finding, "one/repo", 123, "https://github.test/123")
    backlog.save_plan(s, p.id, included=[inv.id], excluded=[])
    s.commit()
    result = backlog.export_plan(s, p.id, "github", repo="one/repo",
                                post_fn=lambda *a: pytest.fail("duplicate prior case ticket"))
    assert result["results"][0]["status"] == "existing"
    assert result["results"][0]["url"] == "https://github.test/123"


def test_requests_export_deterministically_and_mismatched_kind_refuses(s, monkeypatch):
    from echolens.config import settings
    from echolens.db.models import Review
    monkeypatch.setattr(settings, "linear_api_key", "fake")
    monkeypatch.setattr(settings, "linear_team_id", "team-one")
    p, *_ = seed(s)
    for i, text in enumerate(["Please add dark mode", "I wish it had dark mode", "Would love dark mode"]):
        s.add(Review(source="play_store", ext_id=str(i), rating=4, text=text,
                     product=p.name, created_at=datetime.now(timezone.utc)))
    s.flush()
    backlog.save_plan(s, p.id, included=[], excluded=[], kind="requests")
    s.commit()
    with pytest.raises(ValueError, match="view"):
        backlog.export_plan(s, p.id, "linear", kind="bugs")
    def post(url, payload, headers):
        assert "Open questions" in payload["variables"]["input"]["description"]
        assert payload["variables"]["input"]["teamId"] == "team-one"
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "id": "abc", "identifier": "ONE-1", "url": "https://linear.test/1"}}}}
    result = backlog.export_plan(s, p.id, "linear", kind="requests", post_fn=post)
    assert len(result["results"]) == 1
    assert result["results"][0]["status"] == "created"


def test_definite_rejection_retries_but_success_does_not(s, monkeypatch):
    from echolens.config import settings
    monkeypatch.setattr(settings, "linear_api_key", "fake")
    monkeypatch.setattr(settings, "linear_team_id", "team-one")
    p, _, inv, _ = seed(s)
    backlog.save_plan(s, p.id, included=[inv.id], excluded=[])
    s.commit()
    failed = backlog.export_plan(s, p.id, "linear", post_fn=lambda *a: (401, {"error": "fake"}))
    assert failed["results"][0]["status"] == "failed"
    def post(*args):
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "id": "abc", "identifier": "ONE-1", "url": "https://linear.test/1"}}}}
    assert backlog.export_plan(s, p.id, "linear", post_fn=post)["results"][0]["status"] == "created"


def test_product_purge_removes_rules_and_export_claims_before_feedback(s, monkeypatch):
    from echolens.config import settings
    from echolens.db.models import HumanRule, PlanExport
    from echolens.db.purge import purge_product_data
    monkeypatch.setattr(settings, "github_token", "fake")
    p, _, inv, finding = seed(s)
    other, *_ = seed(s, "Other")
    brain.add_rule(s, other.id, "Keep this fact", None)
    s.add(ReviewFeedback(finding_id=finding.id, action="challenge", actual_cause="Sync failed"))
    s.flush()
    brain.rules(s, p.id)
    backlog.save_plan(s, p.id, included=[inv.id], excluded=[])
    s.commit()
    backlog.export_plan(s, p.id, "github", repo="one/repo", post_fn=lambda *a: {
        "number": 3, "html_url": "https://github.test/3"})
    purge_product_data(s, p)
    s.delete(p)
    s.flush()
    assert s.scalars(select(PlanExport)).all() == []
    assert [r.text for r in s.scalars(select(HumanRule)).all()] == ["Keep this fact"]


def test_new_correction_supersedes_prior_imported_hint_without_erasing_history(s):
    p, anomaly, inv, finding = seed(s)
    s.add(ReviewFeedback(finding_id=finding.id, action="challenge", actual_cause="Sync cause one"))
    s.flush()
    old_id = brain.rules(s, p.id)[0]["id"]
    s.add(ReviewFeedback(finding_id=finding.id, action="challenge", actual_cause="Sync cause two"))
    s.flush()
    assert [r["cause"] for r in brain.human_cause_priors(s, p.id)] == ["Sync cause two"]
    assert next(r for r in brain.rules(s, p.id) if r["id"] == old_id)["status"] == "retired"


def test_batch_retries_rejected_item_without_repeating_success(s, monkeypatch):
    from echolens.config import settings
    monkeypatch.setattr(settings, "linear_api_key", "fake")
    monkeypatch.setattr(settings, "linear_team_id", "team-one")
    p, anomaly, first_inv, first = seed(s)
    second_inv = Investigation(anomaly_id=anomaly.id, status="resolved", product_id=p.id)
    s.add(second_inv)
    s.flush()
    s.add(Finding(investigation_id=second_inv.id, product_id=p.id, status="approved", confidence=.8,
                  summary="Second sync issue", json={**first.json, "summary": "Second sync issue"}))
    s.flush()
    backlog.save_plan(s, p.id, included=[first_inv.id, second_inv.id], excluded=[])
    s.commit()
    def post(url, payload, headers):
        if "Second" in payload["variables"]["input"]["title"]:
            return 401, {"error": "rejected"}
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "id": "abc", "identifier": "ONE-1", "url": "https://linear.test/1"}}}}
    first_send = backlog.export_plan(s, p.id, "linear", post_fn=post)
    assert [r["status"] for r in first_send["results"]] == ["created", "failed"]
    def retry(url, payload, headers):
        assert "Second" in payload["variables"]["input"]["title"]
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "id": "def", "identifier": "ONE-2", "url": "https://linear.test/2"}}}}
    second_send = backlog.export_plan(s, p.id, "linear", post_fn=retry)
    assert [r["status"] for r in second_send["results"]] == ["existing", "created"]


def test_unrounded_bug_base_reproduces_override_tie_and_capacity_choice(s):
    """Rounded per-day display values cannot be inverted into ranking inputs."""
    from datetime import timedelta
    p, anomaly, first_inv, first = seed(s)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    first_inv.created_at = now - timedelta(days=1)
    first.json = {**first.json, "impact": {"affected_volume": 10, "impact_score": .2}}
    second_inv = Investigation(anomaly_id=anomaly.id, status="resolved", product_id=p.id,
                               created_at=first_inv.created_at)
    s.add(second_inv)
    s.flush()
    s.add(Finding(investigation_id=second_inv.id, product_id=p.id, status="approved", confidence=.8,
                  summary="Second issue", json={"impact": {"affected_volume": 10, "impact_score": .4}}))
    s.flush()
    initial = {str(first_inv.id): {"effort_days": 6}, str(second_inv.id): {"effort_days": 6}}
    backlog.save_plan(s, p.id, included=[], excluded=[], overrides=initial, capacity_days=10)
    before = backlog.backlog(s, p.id, as_of=now)["items"]
    assert [i["key"] for i in before] == [second_inv.id, first_inv.id]
    assert [i["value_per_day"] for i in before] == [.61, .30]
    by_key = {i["key"]: i for i in before}
    low = by_key[first_inv.id]
    assert low["base_value"] == pytest.approx(1.8177100881684638)
    assert low["base_value"] != low["score"]
    assert [by_key[k]["tie_order"] for k in (first_inv.id, second_inv.id)] == [first_inv.id, second_inv.id]
    initial[str(first_inv.id)]["impact"] = 3
    backlog.save_plan(s, p.id, included=[], excluded=[], overrides=initial, capacity_days=10)
    after = backlog.quarter_plan(s, p.id, as_of=now)
    assert [i["key"] for i in after["proposed"]] == [first_inv.id]
    assert after["proposed"][0]["value_per_day"] == .61
    assert after["deferred"][0]["value_per_day"] == .61


def test_request_base_and_slug_ties_stay_stable_after_priority_changes(s, monkeypatch):
    themes = [
        {"slug": "request-p1-zebra", "statement": "Zebra", "phrase": "zebra", "reviews": [
            {"id": 1, "rating": 4, "text": "Please add zebra", "date": "2026-10-24"}]},
        {"slug": "request-p1-alpha", "statement": "Alpha", "phrase": "alpha", "reviews": [
            {"id": 2, "rating": 3, "text": "Please add alpha", "date": "2026-10-24"}]}]
    monkeypatch.setattr(backlog, "request_themes", lambda *args: themes)
    before = backlog.request_items(s, 1, {})
    assert [(i["key"], i["base_value"], i["tie_order"]) for i in before] == [
        ("request-p1-zebra", 1.5, 2), ("request-p1-alpha", 1, 1)]
    after = backlog.request_items(s, 1, {"request-p1-alpha": {"effort_days": 2},
                                         "request-p1-zebra": {"effort_days": 3}})
    assert [(i["key"], i["value_per_day"], i["tie_order"]) for i in after] == [
        ("request-p1-alpha", .5, 1), ("request-p1-zebra", .5, 2)]
    halfway = backlog.request_items(s, 1, {"request-p1-alpha": {"effort_days": 8}})
    assert next(i for i in halfway if i["key"] == "request-p1-alpha")["value_per_day"] == .13
