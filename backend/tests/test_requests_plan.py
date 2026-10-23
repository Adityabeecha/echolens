"""Plan: bugs vs requests, and specs (PRDs) filed from a request."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.backlog import HAPPY_WEIGHT, quarter_plan, request_items, save_plan
from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, Finding, Investigation, Product, Review, ThemeOverride)
from echolens.integrations import github_issue, trackers
from echolens.prd import build_spec, check_rewrite, file_spec, find_request, quotes_in

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)

# dark mode: 3 requesters, all 4-5★ -> 3 + 1.5 = 4.5
# export pdf: 4 requesters, all 3★  -> 4 + 0   = 4.0  (more askers, less demand)
CORPUS = [
    ("Love it, but I wish it had dark mode", 4),
    ("Please add dark mode, my eyes hurt at night", 5),
    ("Would love a dark mode option", 4),
    ("Can you add export to pdf? Otherwise fine", 3),
    ("It would be great if you could add export to pdf", 3),
    ("Please add export to pdf for my reports", 3),
    ("I wish it had export to pdf like the old version", 3),
    ("Works perfectly, thank you", 5),
]


def _seed(s, name="Notely", corpus=CORPUS):
    p = Product(name=name)
    s.add(p)
    s.flush()
    for i, (t, r) in enumerate(corpus):
        s.add(Review(source="play_store", ext_id=f"{name}{i}", rating=r, text=t,
                     product=name, created_at=NOW - timedelta(days=1 + i % 5)))
    a = AnomalyEvent(slug=f"a-{name}", type="volume_spike", metric="sync", delta=1.0, z=3.0,
                     window="7d", description="d", status="investigating", product_id=p.id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="resolved", product_id=p.id)
    s.add(inv)
    s.flush()
    s.add(Finding(investigation_id=inv.id, product_id=p.id, confidence=0.8, status="approved",
                  summary="Sync drops edits", json={"summary": "Sync drops edits",
                                                    "impact": {"affected_volume": 5, "impact_score": 0.6}}))
    s.flush()
    return p


@pytest.fixture()
def Session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def s(Session):
    sess = Session()
    yield sess
    sess.close()


# ── item 1: ranking + persistence ───────────────────────────────────────

def test_requests_rank_by_weighted_demand_per_day(s):
    p = _seed(s)
    items = request_items(s, p.id, {})
    by = {i["phrase"]: i for i in items}
    assert set(by) == {"dark mode", "export pdf"}
    dark, pdf = by["dark mode"], by["export pdf"]
    assert dark["slug"] == f"request-p{p.id}-dark-mode"
    assert (dark["count"], dark["happy_count"]) == (3, 3)
    assert dark["demand"] == 3 + HAPPY_WEIGHT * 3
    assert (pdf["count"], pdf["happy_count"], pdf["demand"]) == (4, 0, 4.0)
    # Happier requesters win despite fewer of them; both on the default effort.
    assert [i["phrase"] for i in items] == ["dark mode", "export pdf"]
    assert dark["value_per_day"] == round(4.5 / 5.0, 2) and not dark["effort"]["known"]
    assert dark["avg_rating"] == 4.3 and 1 <= len(dark["verbatims"]) <= 2


def test_request_overrides_persist_and_rerank(s):
    p = _seed(s)
    pdf = f"request-p{p.id}-export-pdf"
    save_plan(s, p.id, included=[], excluded=[],
              overrides={pdf: {"effort_days": 1, "impact": 4, "segment": "paying_users"},
                         "request-p1-<script>": {"effort_days": 2}})
    plan = quarter_plan(s, p.id, kind="requests")
    assert set(plan["overrides"]) == {pdf}             # a junk key never lands
    top = plan["proposed"][0]
    assert top["slug"] == pdf and top["effort"]["overridden"] and top["effort"]["days"] == 1
    assert top["impact"]["overridden"] and top["segment"]["key"] == "paying_users"
    assert top["value_per_day"] == round(4.0 * 2.0 * 2.0 / 1.0, 2)
    # A plain include/exclude save keeps the request overrides.
    save_plan(s, p.id, included=[pdf], excluded=[f"request-p{p.id}-dark-mode"])
    plan = quarter_plan(s, p.id, kind="requests")
    assert pdf in plan["overrides"]
    assert [i["slug"] for i in plan["proposed"]] == [pdf]
    assert [i["slug"] for i in plan["deferred"]] == [f"request-p{p.id}-dark-mode"]


def test_kinds_share_capacity_and_picks(s):
    p = _seed(s)
    bugs = quarter_plan(s, p.id, capacity_days=20)
    assert bugs["kind"] == "bugs" and all(i["kind"] == "bug" for i in bugs["proposed"])
    assert bugs["counts"] == {"bugs": 1, "requests": 2}
    both = quarter_plan(s, p.id, capacity_days=10, kind="all")
    kinds = {i["kind"] for i in both["proposed"] + both["deferred"]}
    assert kinds == {"bug", "request"}
    # 3 items x 5d default into 10d: two fit, the committed days say so.
    assert len(both["proposed"]) == 2 and both["committed_days"] == 10.0
    assert both["proposed"][0]["relative_value"] == 1.0
    assert both["proposed"][0]["kind"] == "bug"        # ties go to the bug
    assert quarter_plan(s, p.id, kind="nonsense")["kind"] == "bugs"


def test_muted_and_merged_requests_follow_overrides(s):
    p = _seed(s)
    dark, pdf = f"request-p{p.id}-dark-mode", f"request-p{p.id}-export-pdf"
    s.add(ThemeOverride(product_id=p.id, slug=pdf, merged_into=dark, muted=False))
    s.flush()
    items = request_items(s, p.id, {})
    assert [i["slug"] for i in items] == [dark] and items[0]["count"] == 7
    s.add(ThemeOverride(product_id=p.id, slug=dark, muted=True))
    s.flush()
    assert request_items(s, p.id, {}) == []


# ── item 2: the spec ────────────────────────────────────────────────────

def _theme(s):
    p = _seed(s)
    return p, find_request(s, p.id, f"request-p{p.id}-dark-mode")


def test_spec_has_every_section_and_only_real_quotes(s):
    p, theme = _theme(s)
    spec = build_spec(theme, p.name)
    md = spec["markdown"]
    for h in ("## Problem", "## Who asks", "## User stories", "## Acceptance criteria",
              "## Out of scope", "## Open questions", "## Evidence"):
        assert h in md
    assert spec["engine"] == "template"
    stories = [l for l in md.split("## User stories")[1].split("##")[0].splitlines()
               if l.startswith("- ")]
    criteria = [l for l in md.split("## Acceptance criteria")[1].split("##")[0].splitlines()
                if l.startswith("- ")]
    assert 2 <= len(stories) <= 4 and all(l.startswith("- As a") for l in stories)
    assert 3 <= len(criteria) <= 6 and all("Given" in l and "then" in l for l in criteria)
    quoted = quotes_in(md)
    texts = [r["text"] for r in theme["reviews"]]
    assert quoted and all(any(q in t for t in texts) for q in quoted)
    assert "export pdf" not in "\n".join(quoted).lower()   # another request's words
    assert "Users ask for export pdf" in md.split("## Out of scope")[1]


def test_long_review_is_clipped_outside_the_quote(s):
    p = _seed(s, corpus=CORPUS + [("Please add dark mode " + "really " * 80 + "now", 5)])
    theme = find_request(s, p.id, f"request-p{p.id}-dark-mode")
    md = build_spec(theme, p.name)["markdown"]
    texts = [r["text"] for r in theme["reviews"]]
    assert "” …" in md and all(any(q in t for t in texts) for q in quotes_in(md))


class _LLM:
    def __init__(self, parsed):
        self.parsed, self.calls = parsed, 0

    def complete_json(self, *a, **k):
        self.calls += 1
        parsed = self.parsed

        class R:
            pass
        r = R()
        r.parsed = parsed
        return r


GOOD = {"user_stories": ["As a night reader, I want a dark mode, so that my eyes do not hurt.",
                         "As a 5★ user, I want a dark theme, so that I keep using the app."],
        "acceptance_criteria": [
            "Given dark mode is on, when I open a note, then the background is dark.",
            "Given the system theme is dark, when I launch, then the app follows it.",
            "Given dark mode is off, when I update, then nothing changes."]}


def test_llm_rewrite_used_when_it_passes(s):
    p, theme = _theme(s)
    spec = build_spec(theme, p.name, llm=_LLM(GOOD))
    assert spec["engine"] == "model" and spec["rejected"] is None
    assert "As a night reader" in spec["markdown"]
    assert "## Evidence" in spec["markdown"]        # the rest is still the template


@pytest.mark.parametrize("bad,reason", [
    ({"user_stories": [], "acceptance_criteria": []}, "empty"),
    (None, "empty"),
    ({**GOOD, "user_stories": GOOD["user_stories"] * 3}, "too long"),
    ({**GOOD, "acceptance_criteria": ["Given x, when y, then " + "z" * 400] * 3}, "too long"),
    ({**GOOD, "user_stories": ["Dark mode please", "Make it dark"]}, "off-format"),
    ({**GOOD, "user_stories": [
        'As a user, I want dark mode, so that, as one review says, "it is unusable without it".',
        GOOD["user_stories"][1]]}, "quotes something not in the evidence"),
])
def test_llm_rewrite_rejected_falls_back_to_template(s, bad, reason):
    p, theme = _theme(s)
    template = build_spec(theme, p.name)["markdown"]
    spec = build_spec(theme, p.name, llm=_LLM(bad))
    assert spec["engine"] == "template" and spec["rejected"] == reason
    assert spec["markdown"] == template


def test_llm_may_quote_real_review_words(s):
    p, theme = _theme(s)
    ok = {**GOOD, "user_stories": [
        'As a user, I want dark mode, so that, in one review\'s words, "my eyes hurt at night" stops.',
        GOOD["user_stories"][1]]}
    stories, _ = check_rewrite(ok, [r["text"] for r in theme["reviews"]])
    assert "my eyes hurt at night" in stories[0]


def test_file_spec_github_uses_injected_post_fn(s):
    p, theme = _theme(s)
    spec = build_spec(theme, p.name)
    sent = {}

    def post(repo, title, body, token, labels):
        sent.update(repo=repo, title=title, body=body)
        return {"number": 7, "html_url": "https://github.com/acme/notely/issues/7"}

    import echolens.integrations.github_issue as gi
    old = gi.settings.github_token
    gi.settings.github_token = "t"
    try:
        out = file_spec("github", spec, repo="acme/notely", post_fn=post)
    finally:
        gi.settings.github_token = old
    assert out["number"] == 7 and sent["repo"] == "acme/notely"
    assert sent["title"].startswith("[EchoLens] Spec:") and "## User stories" in sent["body"]
    assert not sent["body"].startswith("# Spec")


# ── endpoints ───────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch, Session):
    engine = Session.kw["bind"]
    with Session() as sess:
        a = _seed(sess, "Notely")
        b = _seed(sess, "Other")
        sess.commit()
        pid, other = a.id, b.id
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    for key in ("openai_api_key", "github_token", "github_default_repo", "linear_api_key",
                "linear_team_id", "jira_base_url", "jira_email", "jira_api_token",
                "jira_project_key"):
        monkeypatch.setattr(settings, key, "", raising=False)
    from echolens.api.app import app
    c = TestClient(app)
    c.pid, c.other, c.app = pid, other, app
    return c


def test_plan_endpoint_kinds_and_request_picks(client):
    slug = f"request-p{client.pid}-dark-mode"
    r = client.get(f"/backlog/plan?product_id={client.pid}&kind=requests")
    assert r.status_code == 200 and r.json()["kind"] == "requests"
    assert {i["slug"] for i in r.json()["proposed"]} >= {slug}
    assert client.get(f"/backlog/plan?product_id={client.pid}&kind=x").status_code == 422
    r = client.put("/backlog/plan", json={
        "product_id": client.pid, "kind": "requests", "included": [], "excluded": [slug],
        "overrides": {slug: {"effort_days": 2}}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["excluded"] == [slug] and body["overrides"][slug]["effort_days"] == 2
    assert slug in [i["slug"] for i in body["deferred"]]


def test_spec_endpoint_is_product_scoped(client):
    slug = f"request-p{client.pid}-dark-mode"
    r = client.get(f"/requests/{slug}/spec?product_id={client.pid}")
    assert r.status_code == 200, r.text
    assert r.json()["markdown"].startswith("# Spec: Users ask for dark mode")
    # Another product's id with this slug, or the other product's slug here: 404.
    assert client.get(f"/requests/{slug}/spec?product_id={client.other}").status_code == 404
    other = f"request-p{client.other}-dark-mode"
    assert client.get(f"/requests/{other}/spec?product_id={client.pid}").status_code == 404
    assert client.get(f"/requests/request-p{client.pid}-nope/spec?product_id={client.pid}"
                      ).status_code == 404


def test_spec_endpoint_never_calls_a_model_without_a_key(client, monkeypatch):
    import echolens.api.app as appmod

    def boom(*a, **k):
        raise AssertionError("no live LLM without a key")
    monkeypatch.setattr(appmod, "_metered_llm", boom)
    r = client.get(f"/requests/request-p{client.pid}-dark-mode/spec?product_id={client.pid}")
    assert r.status_code == 200 and r.json()["engine"] == "template"


def test_ticket_endpoint_files_spec_to_linear(client, monkeypatch):
    monkeypatch.setattr(settings, "linear_api_key", "lin", raising=False)
    monkeypatch.setattr(settings, "linear_team_id", "team", raising=False)
    sent = {}

    def fake_post(url, payload, headers):
        sent["input"] = payload["variables"]["input"]
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "identifier": "ENG-9", "url": "https://linear.app/i/ENG-9"}}}}

    monkeypatch.setattr(trackers, "_default_post", fake_post)
    slug = f"request-p{client.pid}-dark-mode"
    r = client.post(f"/requests/{slug}/ticket?tracker=linear&product_id={client.pid}")
    assert r.status_code == 200, r.text
    assert r.json()["number"] == "ENG-9"
    assert sent["input"]["title"] == "[EchoLens] Spec: Users ask for dark mode"
    assert "## Acceptance criteria" in sent["input"]["description"]
    # Cross-product filing is refused before anything is sent.
    sent.clear()
    r = client.post(f"/requests/{slug}/ticket?tracker=linear&product_id={client.other}")
    assert r.status_code == 404 and not sent


def test_ticket_endpoint_github_and_errors(client, monkeypatch):
    slug = f"request-p{client.pid}-dark-mode"
    url = f"/requests/{slug}/ticket?product_id={client.pid}"
    assert client.post(url + "&tracker=trello").status_code == 422
    assert client.post(url + "&tracker=jira").status_code == 422          # not configured
    monkeypatch.setattr(settings, "github_token", "t", raising=False)
    r = client.post(url + "&tracker=github")
    assert r.status_code == 422 and "GitHub repo" in r.json()["detail"]
    monkeypatch.setattr(settings, "github_default_repo", "acme/notely", raising=False)
    monkeypatch.setattr(github_issue, "_default_post",
                        lambda repo, title, body, token, labels: {"number": 3, "html_url": "u"})
    r = client.post(url + "&tracker=github")
    assert r.status_code == 200 and r.json()["repo"] == "acme/notely" and r.json()["number"] == 3
    # Upstream error bodies stay in the logs.
    for k, v in (("jira_base_url", "https://acme.atlassian.net"), ("jira_email", "pm@acme.test"),
                 ("jira_api_token", "tok"), ("jira_project_key", "APP")):
        monkeypatch.setattr(settings, k, v, raising=False)
    monkeypatch.setattr(trackers, "_default_post",
                        lambda *a: (400, {"errors": {"secret": "account pm@acme.test"}}))
    r = client.post(url + "&tracker=jira")
    assert r.status_code == 422 and "pm@acme.test" not in r.text


def test_ticket_endpoint_requires_reviewer(client):
    from echolens.auth import current_user
    client.app.dependency_overrides[current_user] = lambda: {
        "id": 9, "email": "v@x", "role": "viewer"}
    try:
        slug = f"request-p{client.pid}-dark-mode"
        assert client.post(f"/requests/{slug}/ticket?tracker=github&product_id={client.pid}"
                           ).status_code == 403
        assert client.get(f"/requests/{slug}/spec?product_id={client.pid}").status_code == 200
    finally:
        client.app.dependency_overrides.clear()
