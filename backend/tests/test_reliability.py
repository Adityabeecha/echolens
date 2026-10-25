"""Reliability at live-site scale: zombie-case watchdog, a separate worker,
cached role lookups, bounded semantic search, stored portfolio rows, and
statement counts that do not grow with the corpus."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from echolens.db.models import (
    AnomalyEvent, CollectorState, EvidenceRow, Finding, FixWatch, HypothesisRow,
    Investigation, Issue, LLMCall, Product, Recommendation, Review, TraceStep)

NOW = datetime.now(timezone.utc).replace(microsecond=0)

_WORDS = ("tab", "crash", "sync", "bookmark", "slow", "memory", "video", "password",
          "extension", "update", "battery", "login", "theme", "download", "private")


# ── the scale fixture ───────────────────────────────────────────────────

def build_scale_fixture(s, reviews: int = 10_000, issues: int = 100, cases: int = 60,
                        products: tuple[str, ...] = ("Firefox", "Focus", "Klar"),
                        embed: bool = False, seed: int = 7) -> dict:
    """A Firefox-sized workspace: ~10k reviews, 100 issues and 60 finished
    cases (with evidence, hypotheses, trace, spend) across three products.
    Deterministic for a given seed."""
    rnd = random.Random(seed)
    shares = [0.7, 0.2, 0.1][:len(products)]
    prods = []
    for name in products:
        p = Product(name=name, package_name=f"org.mozilla.{name.lower()}")
        s.add(p)
        prods.append(p)
    s.flush()
    for p in prods:
        s.add(CollectorState(source="play_store", identifier=p.package_name, product=p.name,
                             product_id=p.id, status="healthy", enabled=True,
                             last_run_at=NOW))
    embedder = None
    if embed:
        from echolens.search.embedder import get_embedder
        embedder = get_embedder()
    rows = []
    ext_ids: dict[int, list[str]] = {p.id: [] for p in prods}
    for i in range(reviews):
        p = prods[0] if i < reviews * shares[0] else (
            prods[1] if i < reviews * (shares[0] + shares[1]) else prods[-1])
        words = rnd.sample(_WORDS, 3)
        text = (f"The {words[0]} keeps failing after the {words[1]} change, "
                f"and {words[2]} is worse than before. Review {i}.")
        ext = f"{p.name[:2]}-{i}"
        ext_ids[p.id].append(ext)
        rows.append(Review(source="play_store", ext_id=ext, rating=rnd.choice((1, 1, 2, 3, 4, 5)),
                           text=text, version=f"13{rnd.randint(0, 5)}.0", product=p.name,
                           created_at=NOW - timedelta(days=rnd.randint(0, 120),
                                                      minutes=rnd.randint(0, 1440)),
                           lang="en"))
    if embedder is not None:
        for i in range(0, len(rows), 512):
            chunk = rows[i:i + 512]
            for r, v in zip(chunk, embedder.embed([r.text for r in chunk])):
                r.embedding = v
    s.add_all(rows)
    for i in range(issues):
        p = prods[i % len(prods)]
        s.add(Issue(ext_id=f"mozilla/{p.name.lower()}#{i}", title=f"{_WORDS[i % 15]} broken",
                    body_snippet="steps to reproduce …", state="open", product=p.name,
                    created_at=NOW - timedelta(days=i % 90)))
    s.flush()
    inv_ids = []
    for c in range(cases):
        p = prods[c % len(prods)]
        a = AnomalyEvent(slug=f"scale-{c}", type="theme_volume_surge",
                         metric=f"{_WORDS[c % 15]} complaints", delta=1.0, z=3.0, window="7d",
                         description="surge", status="closed", product_id=p.id)
        s.add(a)
        s.flush()
        status = ("resolved", "resolved", "resolved", "insufficient_evidence", "needs_human")[c % 5]
        inv = Investigation(anomaly_id=a.id, status=status, product_id=p.id, budget_tier="standard",
                            budget_json={}, created_at=NOW - timedelta(days=c),
                            resolved_at=NOW - timedelta(days=c) + timedelta(minutes=20))
        s.add(inv)
        s.flush()
        inv_ids.append(inv.id)
        refs = rnd.sample(ext_ids[p.id], 8)
        for k, ref in enumerate(refs):
            s.add(EvidenceRow(investigation_id=inv.id, eid=f"ev_{k + 1:03d}", source="play_store",
                              ref=ref, snippet=f"quote {k}", retrieved_by="search_reviews()",
                              json={"supports": ["H1"]}))
        for h in range(3):
            s.add(HypothesisRow(investigation_id=inv.id, hid=f"H{h + 1}", statement=f"cause {h}",
                                confidence=0.85 if h == 0 else 0.3,
                                status="supported" if h == 0 else "rejected",
                                json={"evidence_for": [f"ev_00{j}" for j in range(1, 4)] if h == 0 else []}))
        for t in range(30):
            s.add(TraceStep(investigation_id=inv.id, seq=t, kind="THINK", content_json={"text": "…"},
                            created_at=inv.created_at + timedelta(seconds=20 * t)))
        for t in range(10):
            s.add(LLMCall(investigation_id=inv.id, product_id=p.id, agent="investigator.plan",
                          model="gpt-test", tokens_in=2000, tokens_out=400, cost=0.004,
                          created_at=inv.created_at))
        if status != "needs_human":
            f = Finding(investigation_id=inv.id, product_id=p.id, confidence=0.86,
                        status="approved" if c % 3 == 0 else "draft",
                        summary=f"{_WORDS[c % 15].title()} regressed in 13{c % 5}",
                        json={"summary": f"{_WORDS[c % 15]} regressed", "confidence": 0.86,
                              "supported_hypothesis": "H1", "prose": "…",
                              "impact": {"affected_volume": 40, "affected_pct": 12.0,
                                         "impact_score": 0.6, "rating_impact": 0.2,
                                         "terms": [_WORDS[c % 15]]}})
            s.add(f)
            s.flush()
            for r in range(2):
                s.add(Recommendation(finding_id=f.id, action=f"Fix {r}", rank=r + 1))
            if c % 6 == 0:
                s.add(FixWatch(finding_id=f.id, investigation_id=inv.id, repo="mozilla/x",
                               issue_number=c, status="confirmed" if c % 12 == 0 else "watching",
                               terms=[_WORDS[c % 15]], metric=f"{_WORDS[c % 15]} complaints",
                               fix_date=NOW - timedelta(days=10), baseline_rate=0.2,
                               post_rate=0.05, confirmed_at=NOW - timedelta(days=2),
                               product_id=p.id))
    s.flush()
    return {"products": [p.id for p in prods], "investigations": inv_ids}


# ── shared wiring ───────────────────────────────────────────────────────

import threading  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, select, text  # noqa: E402
from sqlalchemy.orm import Session as _OrmSession, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from echolens.config import settings  # noqa: E402
from echolens.db import session as db_session  # noqa: E402
from echolens.db.models import (  # noqa: E402
    Base, QueuedInvestigation, Setting, User, WorkerJob)


def _engine(url: str = "sqlite://"):
    if url == "sqlite://":
        eng = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def wired(monkeypatch):
    """A fresh in-memory DB that the app, the worker and the CLI all use."""
    from echolens import memo
    memo.clear_all()
    eng = _engine()
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", Session)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    import echolens.cli as cli
    monkeypatch.setattr(cli, "init_db", lambda db_url=None: None)
    Session.engine = eng
    return Session


class _Count:
    def __init__(self, eng):
        self.n, self.eng = 0, eng

    def __call__(self, *a, **k):
        self.n += 1

    def __enter__(self):
        event.listen(self.eng, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc):
        event.remove(self.eng, "before_cursor_execute", self)


def _case(s, *, minutes_ago: int, step_minutes_ago: int | None, paused: bool = False,
          product_id: int | None = None):
    a = AnomalyEvent(slug=f"z-{random.random()}", type="volume_spike", metric="m", delta=1.0,
                     z=3.0, window="7d", description="d", status="investigating",
                     product_id=product_id)
    s.add(a)
    s.flush()
    inv = Investigation(anomaly_id=a.id, status="running", paused=paused, product_id=product_id,
                        created_at=NOW - timedelta(minutes=minutes_ago))
    s.add(inv)
    s.flush()
    if step_minutes_ago is not None:
        s.add(TraceStep(investigation_id=inv.id, seq=0, kind="THINK", content_json={},
                        created_at=NOW - timedelta(minutes=step_minutes_ago)))
    q = QueuedInvestigation(product_id=product_id, anomaly_id=a.id, status="running",
                            investigation_id=inv.id, started_at=inv.created_at)
    s.add(q)
    s.flush()
    return inv, a, q


# ── item 1: zombie watchdog ─────────────────────────────────────────────

def test_watchdog_ends_only_cases_without_recent_progress(wired):
    from echolens.cases import case_history, derive_status
    from echolens.investigator.recover import ZOMBIE_REASON, end_zombies
    with wired() as s:
        dead, dead_a, dead_q = _case(s, minutes_ago=40, step_minutes_ago=20)
        silent, _, _ = _case(s, minutes_ago=30, step_minutes_ago=None)    # never wrote a step
        alive, _, _ = _case(s, minutes_ago=60, step_minutes_ago=2)        # writing steps
        young, _, _ = _case(s, minutes_ago=5, step_minutes_ago=None)      # just started
        held, _, _ = _case(s, minutes_ago=90, step_minutes_ago=80, paused=True)
        s.commit()
        ended = end_zombies(s, as_of=NOW)
        s.commit()
        assert sorted(ended) == sorted([dead.id, silent.id])
        for inv in (alive, young, held):
            s.refresh(inv)
            assert inv.status == "running"
        s.refresh(dead)
        assert dead.status == "failed" and dead.data_notes[-1] == ZOMBIE_REASON + "."
        assert s.get(AnomalyEvent, dead_a.id).status == "pending"
        assert s.get(QueuedInvestigation, dead_q.id).status == "failed"
        fail = s.scalars(select(TraceStep).where(TraceStep.investigation_id == dead.id,
                                                 TraceStep.kind == "FAIL")).one()
        assert fail.content_json["text"] == ZOMBIE_REASON and fail.seq == 1
        assert any(e["kind"] == "stopped" and e["text"] == ZOMBIE_REASON
                   for e in case_history(s, dead))
        assert derive_status(dead, None, None)[1] == ZOMBIE_REASON + "."
        assert ZOMBIE_REASON == ("Stopped: no progress for 15 minutes — "
                                 "the worker may have restarted")
        assert end_zombies(s, as_of=NOW) == []          # idempotent


def test_watchdog_never_ends_a_case_whose_step_lands_first(wired):
    """The end is a conditional UPDATE: a step written after the scan picked the
    case (by this process or another) still saves it."""
    from echolens.investigator import recover
    with wired() as s:
        inv, _, _ = _case(s, minutes_ago=40, step_minutes_ago=20)
        s.commit()
        real_execute = s.execute
        raced = []

        def racing_execute(stmt, *a, **k):
            if getattr(stmt, "is_update", False) and not raced:
                raced.append(True)
                with wired.engine.begin() as conn:     # "another worker" writes a step
                    conn.execute(TraceStep.__table__.insert().values(
                        investigation_id=inv.id, seq=1, kind="THINK", content_json={},
                        tokens=0, ms=0, created_at=NOW.replace(tzinfo=None)))
            return real_execute(stmt, *a, **k)

        s.execute = racing_execute
        assert recover.end_zombies(s, as_of=NOW) == [] and raced
        s.refresh(inv)
        assert inv.status == "running"


def test_watchdog_runs_on_startup_on_drain_and_from_the_cli(wired, monkeypatch):
    import echolens.api.app as app_mod
    from echolens.cli import main
    from echolens.investigator import recover
    monkeypatch.setattr(recover, "resume_running", lambda s, *a, **k: [])
    real = recover.end_zombies
    monkeypatch.setattr(recover, "end_zombies", lambda s, *a, **k: real(s, as_of=NOW))
    with wired() as s:
        a, _, _ = _case(s, minutes_ago=60, step_minutes_ago=50)
        s.commit()
    app_mod._recover_running_bg()                         # startup
    with wired() as s:
        assert s.get(Investigation, a.id).status == "failed"
        b, _, _ = _case(s, minutes_ago=60, step_minutes_ago=50)
        s.commit()
    monkeypatch.setattr(app_mod, "_drain_one", lambda pid: False)
    app_mod._drain_queue_bg(None)                         # every queue drain
    with wired() as s:
        assert s.get(Investigation, b.id).status == "failed"
        c, _, _ = _case(s, minutes_ago=60, step_minutes_ago=50)
        s.commit()
    assert main(["watchdog"]) == 0                        # `echolens watchdog`
    with wired() as s:
        assert s.get(Investigation, c.id).status == "failed"


# ── item 2: the worker ──────────────────────────────────────────────────

def test_web_mode_is_unchanged_when_the_setting_is_true(wired, monkeypatch):
    import echolens.api.app as app_mod
    monkeypatch.setattr(settings, "run_investigations_in_web", True, raising=False)
    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, **k):
            self.target, self.args = target, args

        def start(self):
            started.append((self.target, self.args))

    import types
    monkeypatch.setattr(app_mod, "threading", types.SimpleNamespace(Thread=FakeThread))
    fake = lambda *a: None  # noqa: E731
    monkeypatch.setattr(app_mod, "_run_investigation_bg", fake)
    app_mod._spawn("run", 7, "quick")
    assert started == [(fake, (7, "quick"))]
    with wired() as s:
        assert s.scalars(select(WorkerJob)).all() == []


def test_worker_mode_enqueues_in_web_and_runs_in_worker(wired, monkeypatch):
    import echolens.api.app as app_mod
    from echolens.worker import run_once
    monkeypatch.setattr(settings, "run_investigations_in_web", False, raising=False)

    def no_thread(*a, **k):
        raise AssertionError("no investigation thread in worker mode")

    import types
    monkeypatch.setattr(app_mod, "threading", types.SimpleNamespace(Thread=no_thread))
    ran = []
    monkeypatch.setattr(app_mod, "_run_investigation_bg",
                        lambda inv_id, tier: ran.append((inv_id, tier)))
    with wired() as s:
        s.add(Product(name="Lumo"))
        s.commit()
    client = TestClient(app_mod.app)
    r = client.post("/investigations", json={"description": "battery drains overnight",
                                             "tier": "quick", "product_id": 1})
    assert r.status_code == 200, r.text
    inv_id = r.json()["investigation_id"]
    with wired() as s:
        job = s.scalars(select(WorkerJob)).one()
        assert (job.kind, job.args, job.status) == ("run", [inv_id, "quick"], "queued")
    assert ran == []                                       # the web process ran nothing
    assert run_once("w1") == "job:run"
    assert ran == [(inv_id, "quick")]
    with wired() as s:
        job = s.scalars(select(WorkerJob)).one()
        assert job.status == "done" and job.claimed_by == "w1"
    assert run_once("w1") is None                          # idle
    health = client.get("/health").json()
    assert health["investigations_run_in"] == "worker" and health["jobs_queued"] == 0
    assert health["worker_last_seen"]


def test_worker_drains_the_investigation_queue(wired, monkeypatch):
    import echolens.api.app as app_mod
    from echolens.worker import run_once
    monkeypatch.setattr(settings, "run_investigations_in_web", False, raising=False)
    ran = []
    monkeypatch.setattr(app_mod, "_run_investigation_bg", lambda inv_id, tier: ran.append(inv_id))
    with wired() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="q1", type="manual_theme", metric="m", delta=0.0, z=0.0,
                         window="7d", description="d", status="pending", product_id=p.id)
        s.add(a)
        s.flush()
        s.add(QueuedInvestigation(product_id=p.id, anomaly_id=a.id, status="queued",
                                  budget_tier="quick"))
        s.commit()
    assert run_once("w1") == "queue"
    with wired() as s:
        q = s.scalars(select(QueuedInvestigation)).one()
        assert q.status == "done" and q.investigation_id == ran[0]


def test_a_job_is_never_claimed_twice(wired):
    from echolens.worker import claim_job, enqueue_job
    with wired() as s:
        enqueue_job(s, "run", [1, "quick"])
        s.commit()
    a, b = wired(), wired()
    first = claim_job(a, "w1")
    a.commit()
    assert first is not None and first.status == "running"
    assert claim_job(b, "w2") is None
    a.close()
    b.close()


def test_two_workers_racing_on_a_file_db_claim_each_job_once(tmp_path):
    """Real concurrency: three threads, three connections, one SQLite file."""
    from echolens.orchestrator.queue import claim_next
    from echolens.worker import claim_job, enqueue_job
    eng = _engine(f"sqlite:///{tmp_path / 'race.db'}")
    S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as s:
        for i in range(30):
            enqueue_job(s, "run", [i, "quick"])
        for i in range(12):
            a = AnomalyEvent(slug=f"r{i}", type="manual_theme", metric="m", delta=0.0, z=0.0,
                             window="7d", description="d", status="pending", product_id=1)
            s.add(a)
            s.flush()
            s.add(QueuedInvestigation(product_id=1, anomaly_id=a.id, status="queued"))
        s.commit()
    jobs, rows, errors = [], [], []

    def work(name):
        try:
            while True:
                with S() as s:
                    job = claim_job(s, name)
                    s.commit()
                if job is None:
                    break
                jobs.append(job.id)
            while True:
                with S() as s:
                    row = claim_next(s, 1, daily_limit=1000)
                    s.commit()
                if row is None:
                    break
                rows.append(row.id)
        except Exception as err:  # surfaced below, not swallowed
            errors.append(err)

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert sorted(jobs) == list(range(1, 31))             # each exactly once
    assert len(rows) == len(set(rows)) == 12
    eng.dispose()


# ── item 3: cached role lookups ─────────────────────────────────────────

def _user(Session, role="reviewer"):
    with Session() as s:
        u = User(email=f"{role}-{random.random()}@x.test", password_hash="!", role=role)
        s.add(u)
        s.commit()
        return u.id


def test_principal_is_cached_then_invalidated_on_role_change(wired):
    from echolens.auth import principal_for
    uid = _user(wired)
    with _Count(wired.engine) as c:
        assert principal_for(uid, {})["role"] == "reviewer"
    assert c.n >= 1
    with _Count(wired.engine) as c:
        assert principal_for(uid, {})["role"] == "reviewer"
    assert c.n == 0                                        # cache hit: no query
    with wired() as s:                                     # demoted through the ORM
        s.get(User, uid).role = "viewer"
        s.commit()
    assert principal_for(uid, {})["role"] == "viewer"      # immediately


def test_deleted_user_is_refused_immediately(wired):
    from fastapi import HTTPException

    from echolens.auth import principal_for
    uid = _user(wired)
    principal_for(uid, {})
    with wired() as s:
        s.delete(s.get(User, uid))
        s.commit()
    with pytest.raises(HTTPException) as err:
        principal_for(uid, {})
    assert err.value.status_code == 401


def test_out_of_process_changes_land_within_the_ttl(wired, monkeypatch):
    from echolens import auth
    from echolens.memo import TTLCache
    clock = [1000.0]
    monkeypatch.setattr(auth, "_principals",
                        TTLCache(ttl=auth.PRINCIPAL_TTL_S, clock=lambda: clock[0]))
    uid = _user(wired, "admin")
    assert auth.principal_for(uid, {})["role"] == "admin"
    with wired.engine.begin() as conn:                     # SQL by hand: no ORM event
        conn.execute(text("UPDATE users SET role='viewer' WHERE id=:i"), {"i": uid})
    clock[0] += auth.PRINCIPAL_TTL_S - 1
    assert auth.principal_for(uid, {})["role"] == "admin"   # still inside the bound
    clock[0] += 2
    assert auth.principal_for(uid, {})["role"] == "viewer"  # bound respected
    assert auth.PRINCIPAL_TTL_S == 30


def test_rollback_does_not_invalidate_and_cache_is_bounded(wired):
    from echolens.auth import _principal_cache, principal_for
    uid = _user(wired)
    principal_for(uid, {})
    with wired() as s:
        s.get(User, uid).role = "admin"
        s.flush()
        s.rollback()
    assert principal_for(uid, {})["role"] == "reviewer"
    assert _principal_cache().maxsize == 1000


# ── item 4: bounded semantic search ─────────────────────────────────────

def test_semantic_search_reads_only_bounded_embeddings(wired, monkeypatch):
    from sqlalchemy import inspect as sa_inspect

    from echolens.search import semantic
    from echolens.tools.search_reviews import search_reviews
    with wired() as s:
        build_scale_fixture(s, reviews=3500, issues=0, cases=0, embed=True)
        s.commit()
    monkeypatch.setattr(semantic, "SCAN_CAP", 500)        # well under the ~1,500 candidates
    loaded_embeddings = []

    def _seen(_s, obj):
        if isinstance(obj, Review) and "embedding" not in sa_inspect(obj).unloaded:
            loaded_embeddings.append(obj.id)

    statements = []

    def _stmt(conn, cur, stmt, *a):
        statements.append(stmt)

    event.listen(_OrmSession, "loaded_as_persistent", _seen)
    event.listen(wired.engine, "before_cursor_execute", _stmt)
    try:
        with wired() as s:
            out = search_reviews(s, "tab crash", product="Firefox", limit=8)
    finally:
        event.remove(_OrmSession, "loaded_as_persistent", _seen)
        event.remove(wired.engine, "before_cursor_execute", _stmt)
    assert out["returned"] == 8
    assert loaded_embeddings == []                         # never in the ORM rows
    assert semantic.LAST_SCAN == {"candidates": 500, "embeddings": 500}
    scoring = [st for st in statements if "reviews.embedding" in st.split("FROM")[0]]
    assert scoring and all("reviews.text" not in st.split("FROM")[0] for st in scoring)


def test_db_backed_semantic_matches_the_in_memory_path(wired):
    from echolens.search.semantic import augment, embed_corpus
    with wired() as s:
        for i, t in enumerate(["phone runs hot all night", "battery gets warm quickly",
                               "login button broken", "device heats up while charging",
                               "great app love it"]):
            s.add(Review(source="play_store", ext_id=f"x{i}", rating=1, text=t, product="P",
                         created_at=NOW - timedelta(days=i)))
        s.flush()
        embed_corpus(s)
        s.commit()
        rows = s.scalars(select(Review)).all()
        legacy = augment("phone heats up", rows, set(), lambda r: r.text, 3)
        bounded = augment("phone heats up", rows, set(), lambda r: r.text, 3,
                          session=s, model=Review)
        assert legacy and [r.ext_id for r in bounded] == [r.ext_id for r in legacy]


# ── item 5: stored portfolio rows ───────────────────────────────────────

def test_portfolio_serves_stored_rows_and_refreshes_only_what_changed(wired):
    from echolens.portfolio import MAX_REFRESH_PER_REQUEST, stored_portfolio
    with wired() as s:
        build_scale_fixture(s, reviews=600, issues=6, cases=9)
        s.commit()
    with wired() as s:
        first = stored_portfolio(s, now=NOW)
        s.commit()
    assert sorted(first["refreshed"]) == ["Firefox", "Focus", "Klar"]
    assert all(r["updated_min_ago"] == 0 and r["computed_at"] for r in first["products"])
    with wired() as s, _Count(wired.engine) as c:
        again = stored_portfolio(s, now=NOW + timedelta(minutes=4))
    assert again["refreshed"] == [] and c.n <= 4
    assert {r["product"]: r["updated_min_ago"] for r in again["products"]} == {
        "Firefox": 4, "Focus": 4, "Klar": 4}
    assert [r["score"] for r in again["products"]] == [r["score"] for r in first["products"]]
    with wired() as s:                                     # new data for one product
        klar = s.scalars(select(Product).where(Product.name == "Klar")).one()
        s.add(AnomalyEvent(slug="new", type="volume_spike", metric="m", delta=1, z=3,
                           window="7d", description="d", status="pending", product_id=klar.id))
        s.commit()
    with wired() as s:
        changed = stored_portfolio(s, now=NOW + timedelta(minutes=5))
        s.commit()
    assert changed["refreshed"] == ["Klar"]
    with wired() as s:                                     # everything older than 10 min
        later = stored_portfolio(s, now=NOW + timedelta(minutes=30))
        s.commit()
    assert len(later["refreshed"]) == MAX_REFRESH_PER_REQUEST == 2
    assert "Klar" not in later["refreshed"]                # oldest first
    assert later["updated_min_ago"] == 25                  # Klar, computed at +5 min


def test_portfolio_endpoint_and_worker_refresh(wired):
    import echolens.api.app as app_mod
    from echolens.worker import watchdog_pass
    with wired() as s:
        build_scale_fixture(s, reviews=300, issues=3, cases=3)
        s.commit()
    watchdog_pass()                                        # the worker's housekeeping
    with wired() as s:
        assert len(s.scalars(select(Setting).where(
            Setting.key.like("portfolio_row:%"))).all()) == 3
    body = TestClient(app_mod.app).get("/portfolio").json()
    assert body["refreshed"] == [] and body["total_products"] == 3
    assert all("updated_min_ago" in r for r in body["products"])


# ── item 6: statement counts stay flat at Firefox scale ─────────────────

PATHS = ["/today/overview?product_id=1", "/cases?product_id=1", "/investigations/1?product_id=1",
         "/backlog/plan?product_id=1", "/costs/summary?product_id=1", "/costs?product_id=1",
         "/products", "/team", "/sources?product_id=1", "/feed/summary?product_id=1",
         "/portfolio"]
# Steady-state ceilings measured at ~10k reviews / 60 cases, with a little room.
# /investigations/1 +1 for the per-case `guards` field (one query for the
# case's guard trace steps — fixed, not per row).
# /costs/summary +2 for the per-product breakdown in Settings → Costs (two
# GROUP BY queries — spend and cases per product — fixed, not per product).
CEILING = {"/today/overview": 24, "/cases": 28, "/investigations/1": 31, "/backlog/plan": 24,
           "/costs/summary": 14, "/costs": 3, "/products": 3, "/team": 5, "/sources": 7,
           "/feed/summary": 6, "/portfolio": 10, "/chat": 7}


def _measure(monkeypatch, scale: float) -> dict[str, tuple[int, int]]:
    """(statements, review rows loaded) per endpoint, at steady state."""
    from echolens import memo
    memo.clear_all()
    eng = _engine()
    S = sessionmaker(bind=eng, expire_on_commit=False)
    monkeypatch.setattr(db_session, "_engine", eng)
    monkeypatch.setattr(db_session, "_SessionLocal", S)
    monkeypatch.setattr(db_session, "get_engine", lambda db_url=None: eng)
    with S() as s:
        build_scale_fixture(s, reviews=int(10_000 * scale), issues=int(100 * scale),
                            cases=max(6, int(60 * scale)))
        s.commit()
    from echolens.api.app import app
    client = TestClient(app)
    loaded = [0]

    def seen(_s, obj):
        if isinstance(obj, Review):
            loaded[0] += 1

    out = {}
    calls = [("GET", p, None) for p in PATHS] + [
        ("POST", "/chat", {"message": "what are users saying about tabs?", "product_id": 1})]
    for method, path, body in calls:
        client.request(method, path, json=body)            # warm: memo, stored rows
        loaded[0] = 0
        event.listen(_OrmSession, "loaded_as_persistent", seen)
        try:
            with _Count(eng) as c:
                r = client.request(method, path, json=body)
        finally:
            event.remove(_OrmSession, "loaded_as_persistent", seen)
        assert r.status_code == 200, (path, r.text[:200])
        out[path.split("?")[0]] = (c.n, loaded[0])
    return out


def test_statement_counts_do_not_grow_with_the_corpus(monkeypatch):
    small = _measure(monkeypatch, 0.25)
    large = _measure(monkeypatch, 1.0)                     # ~10k reviews, 60 cases
    over = {p: n for p, (n, _) in large.items() if n > CEILING[p]}
    assert not over, f"over the statement ceiling: {over}"
    # Today shows at most 3 recent confirmed-fix cards; each is a bounded few
    # lookups, so it may differ by that much and no more.
    grew = {p: (small[p][0], large[p][0]) for p in large
            if large[p][0] > small[p][0] + (8 if p == "/today/overview" else 0)}
    assert not grew, f"statement count grows with data: {grew}"
    # No list endpoint loads review rows at steady state.
    for path in ("/today/overview", "/cases", "/backlog/plan", "/portfolio", "/chat"):
        assert large[path][1] == 0, (path, large[path])
