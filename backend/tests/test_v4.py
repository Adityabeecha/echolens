"""v4.0 tests: impact quantification, decision doc, severity routing, ticket
export, GitHub issue creation (injected), Slack reply-to-act, and delivery."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.config import settings
from echolens.db.models import (
    AnomalyEvent,
    Base,
    EvidenceRow,
    Finding,
    Investigation,
    Recommendation,
)
from echolens.impact import decision_doc, quantify, severity
from echolens.integrations.github_issue import GitHubIssueError, create_issue
from echolens.synthetic.generate import generate


def _lumo():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    generate(s)
    s.commit()
    return s


def _resolved_finding(s, impact: dict | None = None) -> Finding:
    """A resolved battery finding with one evidence row + one recommendation."""
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    inv = Investigation(anomaly_id=anomaly.id, status="resolved", opened_by="anomaly",
                        budget_tier="standard", budget_json={})
    s.add(inv)
    s.flush()
    fj = {
        "summary": "Background sync in v3.2 drives the battery drain",
        "prose": "The v3.2 background sync causes the battery drain [ev_001].",
        "confidence": 0.85, "supported_hypothesis": "H1",
        "checked": ["play_store", "github"], "what_would_settle_it": "",
        "impact": impact if impact is not None else quantify(s, anomaly, {
            "summary": "Background sync v3.2 battery drain", "prose": ""}),
    }
    f = Finding(investigation_id=inv.id, summary=fj["summary"], confidence=0.85, status="draft", json=fj)
    s.add(f)
    s.add(EvidenceRow(investigation_id=inv.id, eid="ev_001", source="github", ref="#2841",
                      snippet="wakelock never released when queue empty", retrieved_by="tool", json={}))
    s.flush()
    s.add(Recommendation(finding_id=f.id, action="Gate background sync behind a wakelock timeout",
                         rationale="stops the drain", effort="MED", impact="HIGH", rank=1))
    s.flush()
    return f


# ── impact quantification ───────────────────────────────────────────────

def test_quantify_reports_affected_and_rating():
    s = _lumo()
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    imp = quantify(s, anomaly, {"summary": "battery drain since the v3.2 background sync", "prose": ""})
    assert imp["affected_volume"] > 0
    assert 0 <= imp["affected_pct"] <= 100
    assert imp["rating_impact"] >= 0
    assert "impact_score" in imp
    # battery complaints concentrate in the 3.2 cohort
    assert imp["blast_radius"]["top_cohort"] is not None


def test_severity_scales_with_confidence_and_impact():
    big = severity(0.9, {"impact_score": 0.9})
    small = severity(0.4, {"impact_score": 0.1})
    assert big["score"] > small["score"]
    assert big["band"] == "high" and small["band"] == "low"


def test_decision_doc_answers_three_questions():
    s = _lumo()
    f = _resolved_finding(s)
    recs = s.scalars(select(Recommendation).where(Recommendation.finding_id == f.id)).all()
    d = decision_doc(f.json, list(recs), f.json["impact"], "resolved")
    assert d["whats_broken"] and d["how_bad"] and d["what_to_do"]
    assert "sync" in d["what_to_do"].lower()  # comes from the top recommendation


# ── ticket export ───────────────────────────────────────────────────────

def test_finding_ticket_carries_evidence_chain():
    from echolens.exporting import finding_ticket
    s = _lumo()
    f = _resolved_finding(s)
    ticket = finding_ticket(s, f, repo="acme/app", deep_link="https://x/#case/1")
    assert ticket["title"].startswith("[EchoLens]")
    body = ticket["body"]
    assert "What's broken" in body and "Acceptance criteria" in body
    assert "ev_001" in body                                   # evidence travels with the ticket
    assert "https://github.com/acme/app/issues/2841" in body  # github refs linkified


# ── GitHub issue creation (injected) ────────────────────────────────────

def test_create_issue_uses_injected_poster():
    captured = {}

    def fake_post(repo, title, body, token, labels):
        captured.update(repo=repo, title=title, labels=labels)
        return {"number": 7, "html_url": f"https://github.com/{repo}/issues/7"}

    out = create_issue("acme/app", "T", "B", token="x", post_fn=fake_post)
    assert out == {"number": 7, "url": "https://github.com/acme/app/issues/7"}
    assert captured["repo"] == "acme/app"


def test_create_issue_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "github_token", "")  # no ambient token to fall back on
    with pytest.raises(GitHubIssueError):
        create_issue("acme/app", "T", "B", token="", post_fn=lambda *a: {})


# ── delivery routing ────────────────────────────────────────────────────

def test_high_severity_pings_instantly(monkeypatch):
    from echolens import notify
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack/x")
    monkeypatch.setattr(settings, "app_base_url", "https://echolens.app")
    s = _lumo()
    f = _resolved_finding(s, impact={"impact_score": 0.9, "affected_pct": 40, "affected_volume": 30,
                                     "rating_impact": 0.5, "blast_radius": {"top_cohort": "3.2", "ratio": 4.0}})
    sent = {}
    res = notify.notify_finding(s, f, slack_post_fn=lambda url, json: sent.update(url=url, json=json) or _Ok())
    assert res["routed"] == "instant" and "slack" in res["sent"]
    # the 5-line decision summary is in the blocks
    text = str(sent["json"])
    assert "What to do" in text and "case #" in text


def test_low_severity_goes_to_digest(monkeypatch):
    from echolens import notify
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "slack_webhook_url", "https://hooks.slack/x")
    s = _lumo()
    f = _resolved_finding(s, impact={"impact_score": 0.05, "affected_pct": 1, "affected_volume": 1,
                                     "rating_impact": 0.0, "blast_radius": {}})
    called = {"slack": False}
    res = notify.notify_finding(s, f, slack_post_fn=lambda *a, **k: called.update(slack=True) or _Ok())
    assert res["routed"] == "digest" and called["slack"] is False


class _Ok:
    status_code = 200


# ── API: reply-to-act + ticket endpoints ────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        generate(s)
        _resolved_finding(s)
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    return TestClient(app)


def test_issue_markdown_endpoint(client):
    r = client.get("/findings/1/issue")
    assert r.status_code == 200 and "What's broken" in r.json()["body"]


def test_slack_act_approve(client, monkeypatch):
    monkeypatch.setattr(settings, "slack_action_token", "s3cret")
    monkeypatch.setattr(settings, "auto_create_issue_on_approve", False)
    r = client.post("/integrations/slack/act", json={"token": "s3cret", "action": "approve", "finding_id": 1})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.get("/investigations/1").json()["status"] == "resolved"


def test_slack_act_rejects_bad_token(client, monkeypatch):
    monkeypatch.setattr(settings, "slack_action_token", "s3cret")
    r = client.post("/integrations/slack/act", json={"token": "wrong", "action": "approve", "finding_id": 1})
    assert r.status_code == 401


def test_finding_dict_exposes_decision_and_severity(client):
    f = client.get("/investigations/1").json()["finding"]
    assert f["decision"]["whats_broken"] and "score" in f["severity"]
    assert "impact" in f


def test_slack_approve_creates_github_issue(client, monkeypatch):
    """The headline exit criterion: approve from Slack → GitHub issue with the
    evidence chain, dashboard never opened."""
    import echolens.integrations.github_issue as gh
    monkeypatch.setattr(settings, "slack_action_token", "s3cret")
    monkeypatch.setattr(settings, "auto_create_issue_on_approve", True)
    monkeypatch.setattr(settings, "github_token", "tok")
    monkeypatch.setattr(settings, "github_default_repo", "acme/app")
    captured = {}

    def fake_post(repo, title, body, token, labels):
        captured.update(repo=repo, body=body)
        return {"number": 42, "html_url": f"https://github.com/{repo}/issues/42"}

    monkeypatch.setattr(gh, "_default_post", fake_post)
    r = client.post("/integrations/slack/act", json={"token": "s3cret", "action": "approve", "finding_id": 1})
    assert r.status_code == 200
    assert r.json()["issue"]["url"].endswith("/issues/42")
    assert "ev_001" in captured["body"]  # evidence chain rode along
