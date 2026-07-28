"""v2.0 Excel (.xlsx) upload.

Workbooks are built in memory, so nothing here reads a fixture file.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.db import session as db_session
from echolens.db.models import Base, Review
from echolens.importers.csv_reviews import import_reviews_csv
from echolens.importers.spreadsheet import looks_like_xlsx, xlsx_to_csv
from echolens.synthetic.generate import generate

NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    return TestClient(app)


def _book(rows, leading_blanks: int = 0) -> bytes:
    wb = Workbook()
    ws = wb.active
    for _ in range(leading_blanks):
        ws.append([])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_is_detected_by_content_not_extension():
    """latin-1 never raises, so an .xlsx that reached the text decode path would
    silently become binary garbage parsed as one junk row."""
    data = _book([["text"], ["it crashes"]])
    assert looks_like_xlsx(data, "export.txt") is True
    assert looks_like_xlsx(b"text,rating\nhi,1\n", "export.csv") is False


def test_xlsx_and_csv_of_the_same_data_import_identically(session):
    rows = [["text", "rating", "date"],
            ["Battery drains overnight", 1, "2026-07-18"],
            ["Sync keeps failing", 2, "2026-07-19"]]
    csv_text = "text,rating,date\nBattery drains overnight,1,2026-07-18\nSync keeps failing,2,2026-07-19\n"

    from_xlsx = xlsx_to_csv(_book(rows))
    a = import_reviews_csv(session, from_xlsx, product="A", source="xlsx")
    b = import_reviews_csv(session, csv_text, product="B", source="csv")
    assert a["imported"] == b["imported"] == 2
    assert a["skipped"] == b["skipped"]


def test_excel_numbers_do_not_arrive_as_floats(session):
    """Excel stores every number as a float, so a 3-star rating arrives as 3.0
    and int('3.0') raises — the rating would be dropped as unparseable."""
    text = xlsx_to_csv(_book([["text", "rating", "date"],
                              ["Crashes on launch", 3, "2026-07-18"]]))
    assert "3.0" not in text
    r = import_reviews_csv(session, text, product="Lumo", source="xlsx")
    assert r["imported"] == 1
    rev = session.scalars(select(Review).where(Review.source == "xlsx")).first()
    assert rev.rating == 3


def test_real_datetimes_survive_the_conversion(session):
    """A date-formatted cell arrives as a datetime object, not a string.

    Naive, because Excel cannot store a timezone at all — openpyxl raises on a
    tz-aware value, so this is the only form a real workbook can produce.
    """
    text = xlsx_to_csv(_book([["text", "rating", "date"],
                              ["Battery dies fast", 1, NOW.replace(tzinfo=None)]]))
    import_reviews_csv(session, text, product="Lumo", source="xlsx_dt")
    rev = session.scalars(select(Review).where(Review.source == "xlsx_dt")).first()
    assert rev is not None and rev.created_at.date() == NOW.date()


def test_decorative_blank_rows_before_the_header_are_skipped(session):
    """Exports often start with a title row. Treating a blank row as the header
    keys every column to '' and matches no alias, importing nothing."""
    text = xlsx_to_csv(_book([["text", "rating"], ["Total failure to sync", 1]],
                             leading_blanks=2))
    assert text.splitlines()[0].startswith("text")
    r = import_reviews_csv(session, text, product="Lumo", source="xlsx_blank")
    assert r["imported"] == 1


def test_a_non_excel_file_gives_a_usable_error():
    with pytest.raises(ValueError, match="could not read this file as Excel"):
        xlsx_to_csv(b"PK\x03\x04 this is a zip but not a workbook")


def test_empty_cells_become_empty_not_the_string_none(session):
    """str(None) is 'None', which would import as the literal review text."""
    text = xlsx_to_csv(_book([["text", "rating", "version"],
                              ["App freezes constantly", 1, None]]))
    assert "None" not in text
    import_reviews_csv(session, text, product="Lumo", source="xlsx_none")
    rev = session.scalars(select(Review).where(Review.source == "xlsx_none")).first()
    assert rev is not None and not rev.version


# ── over HTTP ───────────────────────────────────────────────────────────

def _rows():
    return [["text", "rating", "date"],
            ["Battery drains overnight since 3.2", 1, "2026-07-18"],
            ["Sync fails every morning", 2, "2026-07-19"]]


def test_uploading_an_xlsx_imports_reviews(client):
    r = client.post("/import/reviews?product=Lumo&source=xlsx",
                    files={"file": ("reviews.xlsx", _book(_rows()), XLSX_MIME)})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2


def test_a_misnamed_xlsx_still_imports(client):
    """Exports are routinely saved with the wrong extension. Detection is by
    content, so an .xlsx labelled .csv must not decode as latin-1 garbage."""
    r = client.post("/import/reviews?product=Lumo2&source=xlsx",
                    files={"file": ("reviews.csv", _book(_rows()), "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2


def test_csv_upload_is_unaffected(client):
    csv_bytes = b"text,rating,date\nStill broken after update,1,2026-07-18\n"
    r = client.post("/import/reviews?product=Lumo3&source=csv",
                    files={"file": ("reviews.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1


def test_a_corrupt_workbook_is_422_not_500(client):
    r = client.post("/import/reviews?product=Lumo4&source=xlsx",
                    files={"file": ("x.xlsx", b"PK\x03\x04nope", XLSX_MIME)})
    assert r.status_code == 422
    assert "Excel" in r.json()["detail"]


def test_feedback_import_also_accepts_xlsx(client):
    book = _book([["text", "created_at", "priority"],
                  ["Cannot log in at all", "2026-07-18", "p1"]])
    r = client.post("/import/feedback?channel=support&product=Lumo",
                    files={"file": ("tickets.xlsx", book, XLSX_MIME)})
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 1
