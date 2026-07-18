from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from echolens.db.models import Base
from echolens.synthetic.generate import generate


@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite://")  # in-memory, hermetic
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)
    with Session() as s:
        generate(s)
        s.commit()
    return eng


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    yield s
    s.rollback()
    s.close()
