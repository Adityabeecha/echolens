"""The problem page (case v2): exhibit dates on the citation map, and an issue
preview a person can edit without losing the attached proof."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db.models import (
    Base, EvidenceRow, Finding, Investigation, Issue, Product, Release, Review)
from echolens.exporting import EVIDENCE_HEADING, apply_ticket_edits
from echolens.forensics import citations


@pytest.fixture()
def bare():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        yield s


def test_citations_carry_each_exhibits_date_and_stars(bare):
    inv = Investigation(status="resolved", product_id=1)
    bare.add(inv)
    bare.flush()
    bare.add_all([
        Review(ext_id="r1", rating=1, text="Phone dies by 2pm", product="P", created_at=datetime(2026, 10, 15, 9)),
        Review(ext_id="r1", rating=5, text="other product", product="Q", created_at=datetime(2026, 1, 1)),
        Issue(ext_id="acme/app#42", title="Wakelock", body_snippet="wakelock", created_at=datetime(2026, 10, 16)),
        Release(version="3.2.0", notes="Background sync", released_at=datetime(2026, 10, 13), product="P"),
        EvidenceRow(investigation_id=inv.id, eid="ev_001", source="play_store", ref="r1",
                    snippet="Phone dies by 2pm", retrieved_by="t", json={}),
        EvidenceRow(investigation_id=inv.id, eid="ev_002", source="github", ref="issue acme/app#42",
                    snippet="wakelock", retrieved_by="t", json={}),
        EvidenceRow(investigation_id=inv.id, eid="ev_003", source="release_notes", ref="release v3.2.0",
                    snippet="Background sync", retrieved_by="t", json={}),
        EvidenceRow(investigation_id=inv.id, eid="ev_004", source="reddit", ref="t3_missing",
                    snippet="?", retrieved_by="t", json={}),
        Finding(investigation_id=inv.id, summary="s", confidence=0.9,
                json={"prose": "Phones die [ev_001]. A wakelock [ev_002] since 3.2.0 [ev_003]."}),
    ])
    bare.flush()
    c = {x["id"]: x for x in citations(bare, inv, "P")["citations"]}
    assert (c["ev_001"]["date"], c["ev_001"]["rating"]) == ("2026-10-15", 1)   # this product's review
    assert (c["ev_002"]["date"], c["ev_002"]["rating"]) == ("2026-10-16", None)
    assert c["ev_003"]["date"] == "2026-10-13"
    assert (c["ev_004"]["date"], c["ev_004"]["rating"]) == (None, None)        # never guessed


GENERATED = {"title": "[EchoLens] Battery drain",
             "body": f"### What's broken\nSync.\n\n{EVIDENCE_HEADING}\n- ev_001 Phone dies\n- ev_002 wakelock"}


def test_edits_keep_every_exhibit_attached():
    out = apply_ticket_edits(GENERATED, "Battery drain since 3.2.0", "Short version for the team.")
    assert out["title"] == "Battery drain since 3.2.0"
    assert out["body"].startswith("Short version for the team.")
    assert out["body"].endswith(f"{EVIDENCE_HEADING}\n- ev_001 Phone dies\n- ev_002 wakelock")
    kept = apply_ticket_edits(GENERATED, None, f"Mine.\n\n{EVIDENCE_HEADING}\n- ev_001 only")
    assert kept["body"] == f"Mine.\n\n{EVIDENCE_HEADING}\n- ev_001 only"
    assert apply_ticket_edits(GENERATED, "  ", "") == GENERATED


def _client(monkeypatch):
    from fastapi.testclient import TestClient

    import echolens.api.app as app_module
    import echolens.db.session as dbs
    import echolens.integrations.trackers as trackers

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        p = Product(name="P")
        s.add(p)
        s.flush()
        inv = Investigation(status="resolved", product_id=p.id, budget_json={})
        s.add(inv)
        s.flush()
        s.add(Finding(investigation_id=inv.id, summary="Battery drain", confidence=0.9, product_id=p.id,
                      json={"summary": "Battery drain", "prose": "Sync [ev_001].", "confidence": 0.9}))
        s.add(EvidenceRow(investigation_id=inv.id, eid="ev_001", source="play_store", ref="r1",
                          snippet="Phone dies by 2pm", retrieved_by="t", json={}))
        s.commit()
        fid, pid = s.query(Finding).first().id, p.id
    monkeypatch.setattr(dbs, "_engine", engine, raising=False)
    monkeypatch.setattr(dbs, "_SessionLocal", Session, raising=False)
    filed = []
    # The product's repo comes from its connected sources; one is assumed here.
    monkeypatch.setattr(app_module, "_github_repo", lambda session, product_id=None: "acme/app")
    monkeypatch.setattr(trackers, "configured_trackers", lambda: {"github": True, "linear": False, "jira": False})
    monkeypatch.setattr(trackers, "create_ticket",
                        lambda tracker, title, body, repo=None: filed.append((tracker, title, body, repo)) or {})
    return TestClient(app_module.app), fid, pid, filed, app_module


def test_ticket_endpoint_files_the_edited_preview_with_its_exhibits(monkeypatch):
    tc, fid, pid, filed, _ = _client(monkeypatch)
    r = tc.post(f"/findings/{fid}/ticket?tracker=github&product_id={pid}",
                json={"title": "Battery drain since 3.2.0", "body": "Our words."})
    assert r.status_code == 200, r.text
    tracker, title, body, repo = filed[-1]
    assert (tracker, title, repo) == ("github", "Battery drain since 3.2.0", "acme/app")
    assert body.startswith("Our words.") and EVIDENCE_HEADING in body and "Phone dies by 2pm" in body
    # Without edits, the generated ticket is filed as before.
    assert tc.post(f"/findings/{fid}/ticket?tracker=github&product_id={pid}").status_code == 200
    assert filed[-1][1].startswith("[EchoLens]")


def test_ticket_endpoint_still_needs_a_reviewer(monkeypatch):
    tc, fid, pid, filed, app_module = _client(monkeypatch)
    from echolens.auth import current_user
    app_module.app.dependency_overrides[current_user] = lambda: {"id": 9, "email": "v@x", "role": "viewer"}
    try:
        assert tc.post(f"/findings/{fid}/ticket?tracker=github&product_id={pid}",
                       json={"title": "x"}).status_code == 403
        assert filed == []
    finally:
        app_module.app.dependency_overrides.clear()
