"""v15 single-case PM workflow: product decisions, partial challenges,
continuing a dead-end case with more budget, and sharing a brief outside the
app. Scripted LLM only — no network, no key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.db.session as db_session
from echolens import review
from echolens.backlog import backlog, quarter_plan
from echolens.calibration import calibration, weak_spots
from echolens.cases import NEEDS_REVIEW, case_history, case_rows, derive_status
from echolens.db.models import (
    AnomalyEvent, Base, EvidenceRow, Finding, FindingDecision, HypothesisRow,
    Investigation, Recommendation, ReviewFeedback, ShareLink, TraceStep)
from echolens.eval.harness import ScriptedLLM
from echolens.exporting import share_brief
from echolens.investigator import guards
from echolens.investigator.graph import Investigator
from echolens.investigator.recover import (
    EXTENSION_STEPS, MAX_HUMAN_EXTENSIONS, extend_investigation, extension_offer,
    grant_extension)
from echolens.synthetic.generate import generate
from echolens.tools.search_github_issues import search_github_issues
from echolens.tools.search_reviews import search_reviews


# ── fixtures ────────────────────────────────────────────────────────────

def _resolved(session) -> Finding:
    """A resolved two-source finding: ev_001 (review) + ev_002 (GitHub)."""
    ref_r = search_reviews(session, query="battery drain", date_from="2026-07-11",
                           rating_max=2)["reviews"][0]["ref"]
    ref_g = search_github_issues(session, "background sync battery wakelock")["issues"][0]["ref"]
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo1").one()
    responses = [
        {"thought": "form", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "sync causes drain", "confidence": 0.5,
                         "status": "active"}]},
        {"thought": "reviews", "action": "call_tool",
         "tool": {"name": "search_reviews", "args": {"query": "battery drain",
                  "date_from": "2026-07-11", "rating_max": 2}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_r, "snippet": "drain since update", "supports": ["H1"],
                       "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.6, "based_on_refs": [ref_r],
                                 "note": "x"}]},
        {"thought": "github", "action": "call_tool",
         "tool": {"name": "search_github_issues",
                  "args": {"query": "background sync battery wakelock"}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_g, "snippet": "wakelock leak", "supports": ["H1"],
                       "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.85, "based_on_refs": [ref_g],
                                 "note": "confirmed"}]},
        {"summary": "sync drives the spike",
         "prose": "The spike is caused by v3.2 sync [ev_001][ev_002].",
         "confidence": 0.85, "supported_hypothesis": "H1", "checked": ["play_store", "github"],
         "what_would_settle_it": ""},
    ]
    inv = Investigator(session, anomaly, llm=ScriptedLLM(responses)).run()
    assert inv.status == "resolved"
    return session.query(Finding).filter_by(investigation_id=inv.id).one()


def _insufficient(session) -> Investigation:
    anomaly = session.query(AnomalyEvent).filter_by(slug="demo2").one()
    responses = [
        {"thought": "Shipping-cost complaints.", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "a pricing change drove the complaints",
                         "confidence": 0.4, "status": "active"}]},
        {"thought": "Nothing corroborates.", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "single weak source"}},
        {"summary": "Insufficient evidence for the shipping-cost spike",
         "prose": "We checked reviews. No hypothesis passed the bar.",
         "confidence": 0.4, "supported_hypothesis": None, "checked": ["play_store"],
         "what_would_settle_it": "More data."},
    ]
    inv = Investigator(session, anomaly, llm=ScriptedLLM(responses), tier="quick").run()
    assert inv.status == "insufficient_evidence"
    return inv


def _add_recs(session, finding: Finding) -> None:
    session.add(Recommendation(finding_id=finding.id, action="Release the wakelock",
                               effort="MED", impact="HIGH", rank=1))
    session.add(Recommendation(finding_id=finding.id, action="Add a battery test",
                               effort="LOW", impact="MED", rank=2))
    session.flush()


# ── 11. product decisions ───────────────────────────────────────────────

def test_decision_validation(session):
    f = _resolved(session)
    with pytest.raises(ValueError):
        review.decide(session, f, "maybe")
    with pytest.raises(ValueError):
        review.decide(session, f, "wont_fix", reason="  ")  # a reason is required
    d = review.decide(session, f, "fix_now", revisit_by=datetime.now(timezone.utc))
    assert d.revisit_by is None, "only park carries a revisit date"


def test_wont_fix_leaves_backlog_and_parked_returns_after_revisit(session):
    f = _resolved(session)
    review.approve(session, f)
    inv_id = f.investigation_id
    assert inv_id in {i["investigation_id"] for i in backlog(session)["items"]}

    review.decide(session, f, "wont_fix", reason="by design")
    board = backlog(session)
    assert inv_id not in {i["investigation_id"] for i in board["items"]}
    assert board["set_aside"][0]["decision"]["decision"] == "wont_fix"

    soon = datetime.now(timezone.utc) + timedelta(days=30)
    review.decide(session, f, "park", revisit_by=soon)
    assert inv_id not in {i["investigation_id"] for i in backlog(session)["items"]}
    # ...and after the revisit date it is back, on its own.
    later = soon + timedelta(days=1)
    assert inv_id in {i["investigation_id"] for i in backlog(session, as_of=later)["items"]}

    review.decide(session, f, "cleared")
    assert inv_id in {i["investigation_id"] for i in backlog(session)["items"]}


def test_fix_now_is_forced_into_the_plan(session):
    f = _resolved(session)
    review.approve(session, f)
    review.decide(session, f, "fix_now")
    plan = quarter_plan(session, capacity_days=0.0)   # no room — fix now still goes in
    assert f.investigation_id in {i["investigation_id"] for i in plan["proposed"]}


def test_decision_shows_in_case_rows_and_history(session):
    f = _resolved(session)
    review.decide(session, f, "wont_fix", reason="by design", user_id=7)
    row = next(r for r in case_rows(session, None) if r["id"] == f.investigation_id)
    assert row["decision"]["decision"] == "wont_fix" and row["decision"]["hidden"] is True
    inv = session.get(Investigation, f.investigation_id)
    events = case_history(session, inv)
    assert any(e["kind"] == "decision" and "won't fix" in e["text"] and e["note"] == "by design"
               for e in events)


# ── 12. partial challenge ───────────────────────────────────────────────

def test_rejecting_evidence_recomputes_two_source_rule(session):
    f = _resolved(session)
    review.approve(session, f)
    result = review.reject_evidence(session, f, "ev_002", note="not about battery", user_id=3)

    # Same verdict guards.two_source_rule gives on the evidence that remains.
    h = session.scalars(select(HypothesisRow).where(
        HypothesisRow.investigation_id == f.investigation_id, HypothesisRow.hid == "H1")).one()
    remaining = [{"id": e.eid, "source": e.source, "snippet": e.snippet}
                 for e in session.scalars(select(EvidenceRow).where(
                     EvidenceRow.investigation_id == f.investigation_id)).all()
                 if e.eid != "ev_002"]
    expected = guards.two_source_rule(
        {**h.json, "evidence_for": [x for x in h.json["evidence_for"] if x != "ev_002"]}, remaining)
    assert result["two_source_ok"] is expected is False
    assert result["needs_review"] is True
    assert "no longer" in result["message"]

    # The approval is withdrawn and the case says why, without re-opening it.
    assert f.status == "draft"
    inv = session.get(Investigation, f.investigation_id)
    assert inv.status == "resolved", "a partial challenge must not re-open the case"
    status, why = derive_status(inv, f, None)
    assert status == NEEDS_REVIEW and "two independent sources" in why
    assert session.query(Investigation).filter_by(reopens_investigation_id=inv.id).count() == 0

    fb = session.scalars(select(ReviewFeedback).where(
        ReviewFeedback.finding_id == f.id, ReviewFeedback.action == "reject_evidence")).one()
    assert fb.reason == "weak_evidence" and fb.note.startswith("ev_002")
    assert any(e["kind"] == "evidence_rejected" for e in case_history(session, inv))

    # Re-approving clears the flag.
    review.approve(session, f)
    assert "needs_review" not in f.json


def test_reject_evidence_errors(session):
    f = _resolved(session)
    with pytest.raises(LookupError):
        review.reject_evidence(session, f, "ev_999")
    review.reject_evidence(session, f, "ev_001")
    with pytest.raises(ValueError):
        review.reject_evidence(session, f, "ev_001")


def test_partial_challenges_count_in_weak_spots_not_calibration(session):
    f = _resolved(session)
    review.approve(session, f)
    _add_recs(session, f)
    review.reject_evidence(session, f, "ev_001")
    review.edit_recommendation(session, f, 1, effort="HIGH", note="touches the sync engine")
    ws = weak_spots(session)
    reasons = {s["reason"]: s for s in ws["spots"]}
    assert reasons["weak_evidence"]["count"] == 1 and reasons["weak_evidence"]["partial"] == 1
    assert reasons["rec_estimate_off"]["count"] == 1
    assert ws["total_challenges"] == 0 and ws["partial_challenges"] == 2
    # The approval still counts as the finding's verdict in the curve.
    assert calibration(session)["n_reviewed"] == 1


def test_edit_recommendation(session):
    f = _resolved(session)
    _add_recs(session, f)
    rec = review.edit_recommendation(session, f, 2, impact="high")
    assert rec.impact == "HIGH"
    with pytest.raises(ValueError):
        review.edit_recommendation(session, f, 2, effort="HUGE")
    with pytest.raises(ValueError):
        review.edit_recommendation(session, f, 2, impact="HIGH")  # no change
    with pytest.raises(LookupError):
        review.edit_recommendation(session, f, 9, effort="LOW")
    assert f.status == "draft", "editing an estimate does not touch the finding's verdict"


# ── 13. continue a dead-end case ────────────────────────────────────────

def test_extension_offer_only_for_dead_ends(session):
    f = _resolved(session)
    resolved = session.get(Investigation, f.investigation_id)
    assert extension_offer(session, resolved)["eligible"] is False
    with pytest.raises(ValueError):
        grant_extension(session, resolved)

    inv = _insufficient(session)
    offer = extension_offer(session, inv)
    assert offer["eligible"] is True and offer["steps"] == EXTENSION_STEPS
    assert offer["remaining"] == MAX_HUMAN_EXTENSIONS
    # The estimate is this case's own recorded spend per step, times the steps.
    iterations = inv.checkpoint_json["budget"]["iterations"]
    assert offer["estimate_usd"] == round(offer["spent_usd"] / iterations * EXTENSION_STEPS, 2)


def test_extend_resumes_from_checkpoint_with_more_budget(session):
    inv = _insufficient(session)
    ckpt_hyps = inv.checkpoint_json["hypotheses"]
    iterations_before = inv.checkpoint_json["budget"]["iterations"]
    script = ScriptedLLM([
        {"thought": "Five more steps — still nothing corroborates.", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "still one source"}},
        {"summary": "Still insufficient", "prose": "Re-checked with more budget; nothing new.",
         "confidence": 0.4, "supported_hypothesis": None, "checked": ["play_store"],
         "what_would_settle_it": "Support tickets."},
    ])
    out = extend_investigation(session, inv, llm=script)
    assert out.id == inv.id, "continues the SAME case, not a new one"
    assert out.status == "insufficient_evidence"
    b = out.checkpoint_json["budget"]
    assert b["human_extensions"] == 1
    assert b["iterations"] == iterations_before + 1
    cap = int(str(out.budget_json["iterations"]).split("/")[1])
    assert cap == 5 + EXTENSION_STEPS          # quick tier (5) + the grant
    assert [h["id"] for h in out.checkpoint_json["hypotheses"]][:len(ckpt_hyps)] ==         [h["id"] for h in ckpt_hyps], "hypotheses carry over from the checkpoint"
    texts = [t.content_json.get("text", "") for t in session.scalars(select(TraceStep).where(
        TraceStep.investigation_id == inv.id)).all()]
    assert any("granted 5 more steps" in t for t in texts)
    assert session.query(Finding).filter_by(investigation_id=inv.id).count() == 2

    # Capped per case.
    extend_investigation(session, out, llm=ScriptedLLM([
        {"thought": "again", "action": "conclude",
         "conclusion": {"status": "insufficient_evidence", "reason": "x"}},
        {"summary": "s", "prose": "p.", "confidence": 0.3, "supported_hypothesis": None,
         "checked": [], "what_would_settle_it": ""}]))
    offer = extension_offer(session, out)
    assert offer["eligible"] is False and offer["remaining"] == 0
    with pytest.raises(ValueError):
        grant_extension(session, out)


def test_granted_budget_is_still_a_hard_ceiling(session):
    inv = _insufficient(session)
    grant_extension(session, inv)
    from echolens.investigator.recover import _restored_budget
    budget = _restored_budget(inv)
    budget.iterations = int(budget.cap_iterations())
    assert guards.budget_exceeded(budget), "the raised cap is enforced like any other"


# ── 14. sharing ─────────────────────────────────────────────────────────

def test_share_brief_is_clean_and_scoped(session):
    f = _resolved(session)
    _add_recs(session, f)
    brief = share_brief(session, f, link="https://x/#/share/abc")
    md = brief["markdown"]
    assert "ev_0" not in md and "H1" not in md and "MED" not in md
    assert "sync drives the spike" in md.lower() and "https://x/#/share/abc" in md
    assert 1 <= len(brief["quotes"]) <= 3
    assert "Release the wakelock (high impact, medium effort)" in md

    review.reject_evidence(session, f, "ev_001")
    struck = session.scalars(select(EvidenceRow).where(
        EvidenceRow.investigation_id == f.investigation_id, EvidenceRow.eid == "ev_001")).one()
    assert struck.snippet not in share_brief(session, f)["markdown"]


def test_share_brief_never_quotes_another_products_evidence(session):
    f = _resolved(session)
    inv = session.get(Investigation, f.investigation_id)
    f.product_id = (inv.product_id or 0) + 999          # finding and case disagree
    session.flush()
    assert share_brief(session, f)["quotes"] == []


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        generate(s)
        s.commit()
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    from echolens.api.app import app
    c = TestClient(app)
    c.Session = Session
    return c


def _seed_resolved(client) -> tuple[int, int]:
    with client.Session() as s:
        f = _resolved(s)
        _add_recs(s, f)
        s.commit()
        return f.id, f.investigation_id


def _token(client, role: str) -> dict:
    from echolens.auth import create_token, create_user
    from echolens.db.models import User
    with client.Session() as s:
        user = s.scalars(select(User).where(User.email == f"{role}@x.com")).first()
        if user is None:
            user = create_user(s, f"{role}@x.com", "pw", role)
            s.commit()
        return {"Authorization": "Bearer " + create_token(user)}


def test_api_decision_partial_and_case_payload(client):
    fid, inv_id = _seed_resolved(client)
    r = client.post(f"/findings/{fid}/decision",
                    json={"decision": "park", "revisit_by": "2099-01-01", "reason": "Q3"})
    assert r.status_code == 200
    assert r.json()["product_decision"]["revisit_by"] == "2099-01-01"
    assert client.post(f"/findings/{fid}/decision", json={"decision": "wont_fix"}).status_code == 422

    r = client.post(f"/findings/{fid}/evidence/ev_002/reject", json={"note": "off-topic"})
    assert r.status_code == 200 and r.json()["needs_review"] is True
    assert client.post(f"/findings/{fid}/evidence/ev_404/reject", json={}).status_code == 404

    r = client.patch(f"/findings/{fid}/recommendations/1", json={"effort": "HIGH"})
    assert r.status_code == 200 and r.json()["effort"] == "HIGH"

    case = client.get(f"/investigations/{inv_id}").json()
    assert case["product_decision"]["decision"] == "park"
    assert case["finding"]["needs_review"]["eid"] == "ev_002"
    assert next(e for e in case["evidence"] if e["id"] == "ev_002")["rejected"]
    assert case["extension"]["eligible"] is False
    assert case["case_status"] == "needs_review"

    # Parked: gone from the overview's open problems.
    ov = client.get("/overview").json()
    assert inv_id not in {p["investigation_id"] for p in ov["open_problems"]}


def test_api_extend(client, monkeypatch):
    import echolens.api.app as api_app
    started = []
    monkeypatch.setattr(api_app, "_extend_investigation_bg",
                        lambda inv_id, note: started.append((inv_id, note)))
    fid, resolved_id = _seed_resolved(client)
    assert client.post(f"/investigations/{resolved_id}/extend").status_code == 422
    with client.Session() as s:
        inv_id = _insufficient(s).id
        s.commit()
    case = client.get(f"/investigations/{inv_id}").json()
    assert case["extension"]["eligible"] is True
    r = client.post(f"/investigations/{inv_id}/extend")
    assert r.status_code == 200 and r.json()["remaining"] == MAX_HUMAN_EXTENSIONS - 1
    assert started and started[0][0] == inv_id
    assert client.get(f"/investigations/{inv_id}").json()["status"] == "running"


def test_api_share_link_lifecycle_and_public_read(client, monkeypatch):
    from echolens.config import settings
    fid, _ = _seed_resolved(client)
    monkeypatch.setattr(settings, "echolens_env", "staging", raising=False)

    # Viewers can neither mint nor see links; the brief itself is readable.
    assert client.post(f"/findings/{fid}/share", headers=_token(client, "viewer")).status_code == 403
    assert client.get(f"/findings/{fid}/brief", headers=_token(client, "viewer")).status_code == 200

    r = client.post(f"/findings/{fid}/share", headers=_token(client, "reviewer"))
    assert r.status_code == 200
    token = r.json()["token"]
    assert len(token) >= 40
    # Idempotent: one active credential per brief.
    assert client.post(f"/findings/{fid}/share", headers=_token(client, "reviewer")).json()["token"] == token

    # Public: no Authorization header at all, and only the brief comes back.
    pub = client.get(f"/share/{token}")
    assert pub.status_code == 200
    body = pub.json()
    assert set(body) == {"headline", "impact", "why", "quotes", "actions", "markdown",
                         "product", "shared_at", "verdict"}
    assert set(body["verdict"]) == {"support_level", "needs_review", "confidence", "fix"}
    assert "ev_0" not in body["markdown"]

    assert client.delete(f"/findings/{fid}/share", headers=_token(client, "reviewer")).status_code == 200
    assert client.get(f"/share/{token}").status_code == 404
    assert client.get("/share/" + "x" * 43).status_code == 404
    with client.Session() as s:
        assert s.scalars(select(ShareLink)).one().revoked_at is not None


def test_product_delete_purges_decisions_and_links(client):
    from echolens.db.models import Product
    fid, inv_id = _seed_resolved(client)
    with client.Session() as s:
        prod = Product(name="Acme")
        s.add(prod)
        s.flush()
        inv = s.get(Investigation, inv_id)
        inv.product_id = prod.id
        s.get(Finding, fid).product_id = prod.id
        s.get(AnomalyEvent, inv.anomaly_id).product_id = prod.id
        s.commit()
        pid = prod.id
    assert client.post(f"/findings/{fid}/decision?product_id={pid}",
                       json={"decision": "fix_now"}).status_code == 200
    token = client.post(f"/findings/{fid}/share?product_id={pid}").json()["token"]
    assert client.get(f"/share/{token}").status_code == 200
    r = client.delete(f"/products/{pid}", params={"confirm": "Acme"})
    assert r.status_code == 200, r.text
    assert client.get(f"/share/{token}").status_code == 404
    with client.Session() as s:
        assert s.scalars(select(FindingDecision)).first() is None
        assert s.scalars(select(ShareLink)).first() is None
