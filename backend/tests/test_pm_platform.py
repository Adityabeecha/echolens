"""PM platform: issue trackers (Linear/Jira), the MCP server, onboarding preview.

Everything external is injected — no network, no real tracker, no real API.
"""
from __future__ import annotations

import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens.config import settings
from echolens.db.models import AnomalyEvent, Base, Finding, Investigation, Product
from echolens.integrations import trackers
from echolens.mcp_server import ApiClient, handle, serve
from echolens.onboarding import preview


# ── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="a1", type="volume_spike", metric="battery drain", delta=1.0,
                         z=3.0, window="7d", description="d", status="investigating",
                         product_id=p.id)
        s.add(a)
        s.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", product_id=p.id)
        s.add(inv)
        s.flush()
        s.add(Finding(investigation_id=inv.id, product_id=p.id, confidence=0.88,
                      status="approved", summary="Wakelock in the 3.2 sync scheduler",
                      json={"summary": "Battery drains overnight", "prose": "3.2 holds a wakelock."}))
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    c = TestClient(app)
    with Session() as s:
        c.finding_id = s.scalars(select(Finding.id)).first()
    return c


@pytest.fixture()
def no_trackers(monkeypatch):
    # github_default_repo too: Settings reads the developer's .env, and a
    # GITHUB_DEFAULT_REPO there means "no repo connected" finds one.
    for key in ("github_token", "github_default_repo", "linear_api_key", "linear_team_id",
                "jira_base_url", "jira_email", "jira_api_token", "jira_project_key"):
        monkeypatch.setattr(settings, key, "", raising=False)


@pytest.fixture()
def linear_on(monkeypatch, no_trackers):
    monkeypatch.setattr(settings, "linear_api_key", "lin_test", raising=False)
    monkeypatch.setattr(settings, "linear_team_id", "team-1", raising=False)


@pytest.fixture()
def jira_on(monkeypatch, no_trackers):
    monkeypatch.setattr(settings, "jira_base_url", "https://acme.atlassian.net/", raising=False)
    monkeypatch.setattr(settings, "jira_email", "pm@acme.test", raising=False)
    monkeypatch.setattr(settings, "jira_api_token", "tok", raising=False)
    monkeypatch.setattr(settings, "jira_project_key", "APP", raising=False)


# ── item 25: Linear + Jira ──────────────────────────────────────────────

def test_linear_issue_create_sends_graphql_mutation(linear_on):
    seen = {}

    def post(url, payload, headers):
        seen.update(url=url, payload=payload, headers=headers)
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "id": "x", "identifier": "ENG-7", "url": "https://linear.app/a/issue/ENG-7"}}}}

    out = trackers.create_linear_issue("Title", "### Body", post_fn=post)
    assert out == {"number": "ENG-7", "url": "https://linear.app/a/issue/ENG-7"}
    assert seen["url"] == "https://api.linear.app/graphql"
    assert "issueCreate" in seen["payload"]["query"]
    assert seen["payload"]["variables"]["input"] == {
        "teamId": "team-1", "title": "Title", "description": "### Body"}
    assert seen["headers"]["Authorization"] == "lin_test"


def test_linear_graphql_errors_raise(linear_on):
    with pytest.raises(trackers.TrackerError):
        trackers.create_linear_issue("t", "b", post_fn=lambda *a: (200, {"errors": [{"message": "no"}]}))


def test_jira_issue_create_uses_rest_v3_and_adf(jira_on):
    seen = {}

    def post(url, payload, headers):
        seen.update(url=url, payload=payload, headers=headers)
        return 201, {"key": "APP-12", "id": "1"}

    out = trackers.create_jira_issue("T" * 300, "### What's broken\nIt crashes\n\n- [ ] fix it",
                                     post_fn=post)
    assert out == {"number": "APP-12", "url": "https://acme.atlassian.net/browse/APP-12"}
    assert seen["url"] == "https://acme.atlassian.net/rest/api/3/issue"
    fields = seen["payload"]["fields"]
    assert fields["project"] == {"key": "APP"} and len(fields["summary"]) == 255
    doc = fields["description"]
    assert doc["type"] == "doc" and doc["version"] == 1
    kinds = [n["type"] for n in doc["content"]]
    assert kinds == ["heading", "paragraph", "bulletList"]
    assert seen["headers"]["Authorization"].startswith("Basic ")


def test_jira_refuses_plain_http(jira_on, monkeypatch):
    monkeypatch.setattr(settings, "jira_base_url", "http://acme.atlassian.net", raising=False)
    with pytest.raises(trackers.TrackerError):
        trackers.create_jira_issue("t", "b", post_fn=lambda *a: (201, {"key": "X-1"}))


def test_configured_trackers_reports_booleans_only(jira_on):
    assert trackers.configured_trackers() == {"github": False, "linear": False, "jira": True}


def test_trackers_endpoint_never_leaks_secrets(client, jira_on):
    r = client.get("/integrations/trackers").json()
    assert {t["id"]: t["configured"] for t in r["trackers"]} == {
        "github": False, "linear": False, "jira": True}
    assert "tok" not in json.dumps(r)


def test_ticket_endpoint_files_to_linear(client, linear_on, monkeypatch):
    sent = {}

    def fake_post(url, payload, headers):
        sent["input"] = payload["variables"]["input"]
        return 200, {"data": {"issueCreate": {"success": True, "issue": {
            "identifier": "ENG-1", "url": "https://linear.app/i/ENG-1"}}}}

    monkeypatch.setattr(trackers, "_default_post", fake_post)
    r = client.post(f"/findings/{client.finding_id}/ticket?tracker=linear")
    assert r.status_code == 200, r.text
    assert r.json()["tracker"] == "linear" and r.json()["number"] == "ENG-1"
    # Same body the GitHub path and the copy-markdown button use.
    assert sent["input"]["title"].startswith("[EchoLens]")
    assert "### Root cause" in sent["input"]["description"]


def test_ticket_endpoint_rejects_unconfigured_and_unknown(client, no_trackers):
    assert client.post(f"/findings/{client.finding_id}/ticket?tracker=jira").status_code == 422
    assert client.post(f"/findings/{client.finding_id}/ticket?tracker=trello").status_code == 422


def test_ticket_endpoint_hides_upstream_error_body(client, jira_on, monkeypatch):
    monkeypatch.setattr(trackers, "_default_post",
                        lambda *a: (400, {"errors": {"secret": "account pm@acme.test"}}))
    r = client.post(f"/findings/{client.finding_id}/ticket?tracker=jira")
    assert r.status_code == 422
    assert "pm@acme.test" not in r.text


def test_legacy_github_issue_endpoint_still_answers(client, no_trackers):
    # No repo connected: the old endpoint keeps its old, specific 422.
    r = client.post(f"/findings/{client.finding_id}/github-issue")
    assert r.status_code == 422 and "GitHub repo" in r.json()["detail"]


# ── item 24: MCP server ─────────────────────────────────────────────────

def _api(routes: dict, seen: list | None = None) -> ApiClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "nope"})
        return httpx.Response(200, json=body)
    return ApiClient(base_url="https://el.test", token="t0k",
                     transport=httpx.MockTransport(handler))


def _rpc(method, params=None, msg_id=1):
    m = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        m["params"] = params
    return m


def test_mcp_initialize_negotiates_version():
    api = _api({})
    r = handle(_rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "1"}}), api)
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert r["result"]["serverInfo"]["name"] == "echolens"
    # An unknown version gets ours.
    r = handle(_rpc("initialize", {"protocolVersion": "1999-01-01"}), api)
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_mcp_tools_list_has_the_read_only_tools():
    r = handle(_rpc("tools/list"), _api({}))
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"list_open_problems", "get_finding", "search_findings", "product_health"} <= names
    for t in r["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object"
        assert t["annotations"]["readOnlyHint"] is True


def test_mcp_list_open_problems_filters_closed_and_sends_token():
    seen: list = []
    api = _api({"/cases": {"product": "Lumo", "product_id": 3, "cases": [
        {"id": 1, "title": "Crash", "status": "needs_review", "severity_score": 0.4},
        {"id": 2, "title": "Old", "status": "verified_fixed", "severity_score": 0.9},
        {"id": 3, "title": "Battery", "status": "regressed", "severity_score": 0.8},
        {"id": 4, "title": "Noise", "status": "dismissed"},
    ]}}, seen)
    r = handle(_rpc("tools/call", {"name": "list_open_problems",
                                   "arguments": {"product_id": 3}}), api)["result"]
    assert r["isError"] is False
    data = r["structuredContent"]
    assert [c["case_id"] for c in data["cases"]] == [3, 1]
    assert json.loads(r["content"][0]["text"]) == data
    assert seen[0].headers["Authorization"] == "Bearer t0k"
    assert seen[0].url.params["product_id"] == "3"


def test_mcp_get_finding_and_search():
    api = _api({
        "/investigations/9": {"id": 9, "title": "Battery", "case_status": "resolved",
                              "finding": {"summary": "wakelock", "confidence": 0.9, "prose": "3.2"},
                              "recommendations": [{"rank": 1, "action": "revert"}],
                              "evidence": [{"source": "play_store", "ref": "r1", "snippet": "dies"}]},
        "/archive": {"rows": [
            {"id": "#9", "cause": "Wakelock in sync", "summary": "battery drain", "status": "Resolved"},
            {"id": "#5", "cause": "Login loop", "summary": "", "status": "Resolved"},
        ]},
    })
    f = handle(_rpc("tools/call", {"name": "get_finding", "arguments": {"case_id": 9}}), api)
    data = f["result"]["structuredContent"]
    assert data["finding"]["root_cause"] == "3.2" and data["recommendations"][0]["action"] == "revert"
    s = handle(_rpc("tools/call", {"name": "search_findings",
                                   "arguments": {"query": "battery"}}), api)
    assert [x["case_id"] for x in s["result"]["structuredContent"]["results"]] == [9]


def test_mcp_tool_failure_is_an_error_result_not_a_crash():
    r = handle(_rpc("tools/call", {"name": "get_finding", "arguments": {"case_id": 404}}), _api({}))
    assert r["result"]["isError"] is True
    missing = handle(_rpc("tools/call", {"name": "get_finding", "arguments": {}}), _api({}))
    assert missing["result"]["isError"] is True
    unknown = handle(_rpc("tools/call", {"name": "drop_tables"}), _api({}))
    assert unknown["error"]["code"] == -32602


def test_mcp_needs_an_api_url():
    api = ApiClient(base_url="", token="", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    r = handle(_rpc("tools/call", {"name": "product_health"}), api)
    assert r["result"]["isError"] is True and "ECHOLENS_API_URL" in r["result"]["content"][0]["text"]


def test_mcp_stdio_loop_ignores_notifications_and_reports_parse_errors():
    lines = "\n".join([
        json.dumps(_rpc("initialize", {"protocolVersion": "2025-06-18"}, 1)),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "{not json",
        json.dumps(_rpc("nope/method", msg_id=2)),
        json.dumps(_rpc("ping", msg_id=3)),
    ]) + "\n"
    out = io.StringIO()
    assert serve(io.StringIO(lines), out, _api({})) == 0
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2, 3]
    assert replies[1]["error"]["code"] == -32700
    assert replies[2]["error"]["code"] == -32601
    assert replies[3]["result"] == {}


def test_cli_registers_mcp_command(monkeypatch):
    from echolens import cli
    called = {}
    monkeypatch.setattr("echolens.mcp_server.serve", lambda api=None: called.setdefault("api", api) and 0)
    cli.main(["mcp", "--api-url", "https://el.test", "--token", "abc"])
    assert called["api"].base_url == "https://el.test" and called["api"].token == "abc"


# ── item 26: onboarding preview ─────────────────────────────────────────

def test_play_store_preview_reads_listing():
    out = preview.preview_play_store("com.lumo.app", fetch_fn=lambda pkg: {
        "title": "Lumo", "ratings": 12345, "score": 4.123, "developer": "Lumo Inc"})
    assert out["ok"] and out["title"] == "Lumo" and out["ratings"] == 12345 and out["score"] == 4.12


def test_play_store_preview_degrades_gracefully():
    assert preview.preview_play_store("not a package")["kind"] == "invalid"

    class NotFoundError(Exception):
        pass

    def missing(pkg):
        raise NotFoundError()
    assert preview.preview_play_store("com.nope.app", fetch_fn=missing)["kind"] == "not_found"

    def boom(pkg):
        raise RuntimeError("throttled")
    assert preview.preview_play_store("com.x.app", fetch_fn=boom)["kind"] == "unavailable"

    import time

    def slow(pkg):
        time.sleep(1.0)
        return {"title": "late"}
    out = preview.preview_play_store("com.x.app", fetch_fn=slow, timeout=0.05)
    assert out == {"ok": False, "kind": "timeout", "reason": out["reason"]}


def test_github_preview_normalizes_url_and_reports_missing():
    out = preview.preview_github("https://github.com/acme/app.git", fetch_fn=lambda repo: {
        "full_name": repo, "open_issues_count": 42, "stargazers_count": 7})
    assert out["ok"] and out["identifier"] == "acme/app" and out["open_issues"] == 42
    assert preview.preview_github("acme/gone", fetch_fn=lambda r: None)["kind"] == "not_found"
    assert preview.preview_github("not a repo!")["kind"] == "invalid"


def test_onboard_preview_endpoint(client, monkeypatch):
    monkeypatch.setattr("echolens.collectors.play_store.fetch_app_details",
                        lambda pkg: {"title": "Lumo", "ratings": 10})
    monkeypatch.setattr("echolens.collectors.github.fetch_repo_meta",
                        lambda repo, timeout=4.0: {"full_name": repo, "open_issues_count": 3})
    r = client.get("/onboard/preview", params={"play_store": "com.lumo.app", "github": "acme/app"})
    assert r.status_code == 200
    body = r.json()
    assert body["play_store"]["title"] == "Lumo" and body["github"]["open_issues"] == 3
    assert client.get("/onboard/preview").json() == {}
