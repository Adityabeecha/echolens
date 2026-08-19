from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from echolens.db.models import (AnomalyEvent, Base, Investigation, Product,
                                TraceStep)


@pytest.fixture()
def db_file():
    path = os.path.join(tempfile.gettempdir(), f"echolens_iso_{uuid.uuid4().hex}.db")
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()
    try:
        os.remove(path)
    except OSError:
        pass


def _case(Session_):
    with Session_() as s:
        p = Product(name="Lumo")
        s.add(p)
        s.flush()
        a = AnomalyEvent(slug="r1", type="volume_spike", metric="m", delta=1.0, z=3.0,
                         window="7d", description="d", status="investigating",
                         product_id=p.id)
        s.add(a)
        s.flush()
        inv = Investigation(anomaly_id=a.id, status="running", budget_tier="standard",
                            product_id=p.id)
        s.add(inv)
        s.commit()
        return inv.id


def test_a_flushed_step_is_invisible_to_another_session(db_file):
    _engine, Session_ = db_file
    iid = _case(Session_)
    writer, reader = Session_(), Session_()
    try:
        writer.add(TraceStep(investigation_id=iid, seq=1, kind="THINK",
                             content_json={"text": "thinking"}))
        writer.flush()
        assert reader.scalars(select(TraceStep)).all() == []
        writer.commit()
    finally:
        writer.close()
        reader.close()


def test_the_investigator_commits_each_step_as_it_happens(db_file):
    _engine, Session_ = db_file
    iid = _case(Session_)

    writer = Session_()
    try:
        inv = writer.get(Investigation, iid)

        class FakeInvestigator:
            def __init__(self, session, investigation):
                self.session, self.inv = session, investigation
                self._seq, self._recent = 0, []
                self.on_step = lambda kind, content: None

        from echolens.investigator.graph import Investigator
        fake = FakeInvestigator(writer, inv)
        Investigator._trace(fake, "THINK", {"text": "first thought"})

        with Session_() as reader:
            rows = reader.scalars(select(TraceStep)).all()
            assert len(rows) == 1, "the step is still stuck in an open transaction"
            assert rows[0].content_json["text"] == "first thought"

        Investigator._trace(fake, "TOOL", {"text": "second thought"})
        with Session_() as reader:
            assert len(reader.scalars(select(TraceStep)).all()) == 2
    finally:
        writer.close()


def test_a_partial_trace_survives_an_interrupted_run(db_file):
    _engine, Session_ = db_file
    iid = _case(Session_)

    writer = Session_()
    try:
        inv = writer.get(Investigation, iid)

        class FakeInvestigator:
            def __init__(self, session, investigation):
                self.session, self.inv = session, investigation
                self._seq, self._recent = 0, []
                self.on_step = lambda kind, content: None

        from echolens.investigator.graph import Investigator
        fake = FakeInvestigator(writer, inv)
        Investigator._trace(fake, "THINK", {"text": "step one"})
        Investigator._trace(fake, "TOOL", {"text": "step two"})
    finally:
        writer.close()

    with Session_() as s:
        assert len(s.scalars(select(TraceStep)).all()) == 2
        from echolens.investigator.recover import find_interrupted
        assert [i.id for i in find_interrupted(s)] == [iid]
