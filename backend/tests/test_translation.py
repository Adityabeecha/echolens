"""Translate instead of dropping: detection, cached translation, metered spend,
analysis on text_en, and quotes that stay verbatim in the original language."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import echolens.llm.openai_client as openai_client
from echolens import fixwatch
from echolens.config import settings
from echolens.db import session as db_session
from echolens.db.models import (
    AnomalyEvent, Base, EvidenceRow, Finding, Investigation, LLMCall, Product, Review)
from echolens.replies import reply_drafts
from echolens.textkit import detect_language, language_name
from echolens.tools.search_reviews import search_reviews
from echolens.translate import analysis_text, translate_reviews

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)
ES = "La batería se agota muy rápido desde la actualización"
ES_EN = "The battery drains very fast since the update"


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


def _product(s, name="Lumo"):
    p = Product(name=name)
    s.add(p)
    s.flush()
    return p


def _review(s, key, text, rating=1, product="Lumo", days_ago=1, **kw):
    r = Review(source="play_store", ext_id=key, rating=rating, text=text, product=product,
               created_at=NOW - timedelta(days=days_ago), **kw)
    s.add(r)
    s.flush()
    return r


class FakeLLM:
    """Translates by lookup; counts calls."""
    def __init__(self, table=None):
        self.table, self.calls = table or {}, 0

    def complete_json(self, system, user, schema, agent):
        import json
        self.calls += 1
        items = json.loads(user)

        class R:
            pass
        r = R()
        r.parsed = {"translations": [{"id": i["id"], "text": self.table.get(i["text"], "Translated")}
                                     for i in items]}
        return r


# ── detection ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,lang", [
    (ES, "es"),
    ("O aplicativo não abre e está muito lento desde a atualização", "pt"),
    ("L'application plante depuis la mise à jour, je ne peux pas ouvrir mes notes", "fr"),
    ("Die App stürzt seit dem Update ständig ab und ist sehr langsam", "de"),
    ("L'app si blocca sempre e non riesco a sincronizzare le note", "it"),
    ("Приложение постоянно вылетает после обновления", "ru"),
    ("Додаток постійно вилітає після оновлення, і це дратує", "uk"),
    ("アップデート後にバッテリーの消耗が激しい", "ja"),
    ("更新后电池消耗很快", "zh"),
    ("업데이트 후 배터리가 너무 빨리 닳아요", "ko"),
    ("التطبيق يتوقف بعد التحديث", "ar"),
    ("अपडेट के बाद ऐप बार बार बंद हो जाता है", "hi"),
    ("The battery drains overnight since the update and it is very annoying", "en"),
    ("battery drain", "und"),       # too little to call: left alone
    ("👍👍👍", "und"),
])
def test_detects_languages(text, lang):
    assert detect_language(text) == lang


def test_mostly_english_with_a_foreign_word_is_english():
    assert detect_language("I love it but the sync is slow when I open the app de nada") == "en"
    assert language_name("es") == "Spanish"


# ── translation: cache, cap, spend ──────────────────────────────────────

def test_translates_once_and_caches(s):
    p = _product(s)
    _review(s, "es1", ES)
    _review(s, "en1", "The battery drains overnight since the update and it is very bad")
    llm = FakeLLM({ES: ES_EN})
    out = translate_reviews(s, p, llm)
    assert out["translated"] == 1 and llm.calls == 1
    es = s.scalars(select(Review).where(Review.ext_id == "es1")).one()
    assert es.lang == "es" and es.text_en == ES_EN and es.text == ES   # original untouched
    en = s.scalars(select(Review).where(Review.ext_id == "en1")).one()
    assert en.lang == "en" and en.text_en is None
    again = translate_reviews(s, p, llm)
    assert again["translated"] == 0 and again["pending"] == 0 and llm.calls == 1


def test_run_is_capped_and_scoped_to_the_product(s):
    p = _product(s)
    _product(s, "Other")
    for i in range(30):
        _review(s, f"es{i}", f"{ES} {i}")
    _review(s, "other", ES, product="Other")
    llm = FakeLLM()
    out = translate_reviews(s, p, llm, limit=25)
    assert out["translated"] == 25 and llm.calls == 2           # batches of 20
    other = s.scalars(select(Review).where(Review.product == "Other")).one()
    assert other.text_en is None


def test_daily_budget_stops_before_calling(s):
    p = _product(s)
    _review(s, "es1", ES)
    s.add(LLMCall(product_id=p.id, agent="translate.reviews", cost=0.9))
    s.flush()
    llm = FakeLLM()
    out = translate_reviews(s, p, llm, daily_usd=0.5)
    assert out["stopped"] == "daily_budget" and llm.calls == 0
    # Another product's spend does not count against this one.
    q = _product(s, "Quiet")
    _review(s, "q1", ES, product="Quiet")
    assert translate_reviews(s, q, llm, daily_usd=0.5)["translated"] == 1


def test_no_llm_means_detection_only(s):
    p = _product(s)
    _review(s, "es1", ES)
    out = translate_reviews(s, p, None)
    assert out["stopped"] == "no_llm" and out["pending"] == 1
    assert s.scalars(select(Review)).one().lang == "es"


# ── analysis reads text_en, quotes keep the original ────────────────────

def test_search_matches_on_translation_but_quotes_original(s):
    _product(s)
    _review(s, "es1", ES, lang="es", text_en=ES_EN)
    out = search_reviews(s, "battery drains", product="Lumo")
    assert out["total_matches"] == 1
    hit = out["reviews"][0]
    assert hit["snippet"] == ES and hit["lang"] == "es"
    assert ES_EN not in str(out)       # the investigator only ever sees the original


def test_request_discovery_groups_translated_reviews(s):
    from echolens.themes.requests import discover_requests
    _product(s, "Notely")
    originals = ["Por favor añadan el modo oscuro, me duelen los ojos",
                 "Me encantaría un modo oscuro en la aplicación"]
    for i, t in enumerate(originals):
        _review(s, f"r{i}", t, rating=5, product="Notely", lang="es",
                text_en=["Please add dark mode, my eyes hurt", "I would love a dark mode option"][i])
    out = discover_requests(s, "Notely", as_of=NOW)
    dark = [r for r in out["requests"] if r["phrase"] == "dark mode"]
    assert dark and dark[0]["count"] == 2
    assert set(dark[0]["verbatims"]) == set(originals)


def test_analysis_text_prefers_translation():
    class R:
        text, text_en = ES, ES_EN
    assert analysis_text(R()) == ES_EN
    R.text_en = None
    assert analysis_text(R()) == ES


def test_reply_draft_for_spanish_reviewer(s):
    from tests.test_pm_loop import CLOSE, _finding, _watch_closed
    _, f = _finding(s)
    s.add(Review(source="play_store", ext_id="es", rating=1, text=ES, lang="es",
                 text_en=ES_EN, created_at=CLOSE - timedelta(days=1)))
    s.flush()
    _watch_closed(s, f)
    row = reply_drafts(s, f)["drafts"][0]       # matched via the translation
    assert row["excerpt"] == ES and row["excerpt_en"] == ES_EN
    assert row["draft"] and row["note"] == "Reviewer wrote in Spanish — translate before posting."

    class LLM:
        def complete_json(self, system, user, schema, agent):
            class R:
                parsed = {"reply": "Gracias por avisarnos: estamos trabajando en ello."}
            return R()
    row = reply_drafts(s, f, llm=LLM())["drafts"][0]
    assert row["machine_translated"] and row["draft_translated"].startswith("Gracias")
    assert "Machine-translated into Spanish" in row["note"]
    assert row["draft"] != row["draft_translated"]       # the English is still there


# ── endpoints ───────────────────────────────────────────────────────────

class FakeClient:
    """Stands in for OpenAIClient: translates and reports spend via on_call."""
    made = 0

    def __init__(self, on_call=None, **kw):
        FakeClient.made += 1
        self.on_call = on_call

    def complete_json(self, system, user, schema, agent):
        self.on_call(agent, "gpt-test", 100, 50, 0.002, 5)
        return FakeLLM({ES: ES_EN}).complete_json(system, user, schema, agent)


@pytest.fixture()
def client(monkeypatch, Session):
    engine = Session.kw["bind"]
    with Session() as sess:
        p = _product(sess)
        _review(sess, "es1", ES)
        a = AnomalyEvent(slug="a1", type="volume_spike", metric="battery", delta=1.0, z=3.0,
                         window="7d", description="d", status="investigating", product_id=p.id)
        sess.add(a)
        sess.flush()
        inv = Investigation(anomaly_id=a.id, status="resolved", product_id=p.id)
        sess.add(inv)
        sess.flush()
        sess.add(EvidenceRow(investigation_id=inv.id, eid="ev_001", source="play_store",
                             ref="es1", snippet="La batería se agota muy rápido",
                             retrieved_by="search_reviews(...)", json={}))
        sess.add(Finding(investigation_id=inv.id, product_id=p.id, confidence=0.8,
                         status="draft", summary="Battery", json={"summary": "Battery"}))
        sess.commit()
        ids = {"pid": p.id, "inv": inv.id}
    monkeypatch.setattr(db_session, "_engine", engine)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: engine)
    monkeypatch.setattr(openai_client, "OpenAIClient", FakeClient)
    FakeClient.made = 0
    from echolens.api.app import app
    c = TestClient(app)
    c.ids, c.app, c.Session = ids, app, Session
    return c


def test_translate_endpoint_records_spend_with_product_id(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    r = client.post(f"/translate?product_id={client.ids['pid']}")
    assert r.status_code == 200, r.text
    assert r.json()["translated"] == 1
    with client.Session() as sess:
        calls = sess.scalars(select(LLMCall)).all()
        assert [(c.product_id, c.agent) for c in calls] == [(client.ids["pid"], "translate.reviews")]
        assert sess.scalars(select(Review)).one().text_en == ES_EN


def test_no_model_without_a_key_or_for_a_guest(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "", raising=False)
    r = client.post(f"/translate?product_id={client.ids['pid']}")
    assert r.status_code == 200 and r.json()["translated"] == 0 and FakeClient.made == 0
    assert "No model key" in r.json()["note"]
    # A guest cannot reach the endpoint, and the helper refuses them a model too.
    monkeypatch.setattr(settings, "openai_api_key", "sk-test", raising=False)
    from echolens.api.app import _translate_product
    from echolens.auth import GUEST
    with client.Session() as sess:
        out = _translate_product(sess, sess.get(Product, client.ids["pid"]), GUEST)
    assert out["stopped"] == "no_llm" and FakeClient.made == 0


def test_translate_requires_reviewer(client):
    from echolens.auth import current_user
    client.app.dependency_overrides[current_user] = lambda: {
        "id": 9, "email": "v@x", "role": "viewer"}
    try:
        assert client.post(f"/translate?product_id={client.ids['pid']}").status_code == 403
    finally:
        client.app.dependency_overrides.clear()


def test_evidence_keeps_original_quote_and_shows_translation(client):
    with client.Session() as sess:
        sess.scalars(select(Review)).one().text_en = ES_EN
        sess.commit()
    inv = client.get(f"/investigations/{client.ids['inv']}?product_id={client.ids['pid']}").json()
    ev = inv["evidence"][0]
    assert ev["snippet"] == "La batería se agota muy rápido"      # verbatim, original
    assert ev["translation"] == {"lang": "es", "lang_name": "Spanish", "text_en": ES_EN}
