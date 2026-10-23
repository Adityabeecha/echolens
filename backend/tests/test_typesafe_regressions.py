"""Behavioral regressions confirmed during the September TypeSafe review."""
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from echolens.db.models import LLMCall
from echolens.feedback import FeedbackItem, dedupe_witnesses
from tests.test_v8_scoping import client  # noqa: F401 - isolated API/database fixture


@pytest.mark.parametrize("today", [date(2026, 1, 15), date(2024, 3, 1)])
def test_monthly_spend_uses_current_utc_month_and_selected_product(client, monkeypatch, today):
    import echolens.api.app as api

    tc, ids, Session = client
    monkeypatch.setattr(api, "_today", lambda: today)
    start = datetime.combine(today.replace(day=1), time(), tzinfo=timezone.utc)
    with Session() as session:
        calls = list(session.scalars(select(LLMCall).order_by(LLMCall.id)))
        old, other_product = calls
        old.created_at = start - timedelta(microseconds=1)
        old.cost = 4.0
        other_product.created_at = start
        other_product.cost = 9.0
        for when, cost in ((start, 0.02), (datetime.combine(today, time(12), tzinfo=timezone.utc), 0.03),
                           (datetime.combine(today + timedelta(days=1), time(), tzinfo=timezone.utc), 7.0)):
            session.add(LLMCall(investigation_id=old.investigation_id, agent="test", model="test",
                                tokens_in=1, tokens_out=1, cost=cost, ms=1, created_at=when))
        session.commit()

    response = tc.get(f"/costs/summary?product_id={ids['Alpha']}")
    assert response.status_code == 200
    data = response.json()
    assert data["month_to_date"] == 0.05
    # Historical case accounting must retain all calls, including prior months.
    assert data["rows"][0]["cost"] == "$11.05"


def _item(ref, channel, text):
    return FeedbackItem(ref=ref, channel=channel, text=text, created_at=None)


@pytest.mark.parametrize("text", ["アプリが開かない", "应用无法打开", "Приложение не открывается",
                                  "التطبيق لا يعمل", "ऐप नहीं खुलता", "😡😡"])
def test_deduplication_retains_non_ascii_feedback(text):
    kept, collapsed = dedupe_witnesses([_item("r1", "play_store", text)])
    assert [item.ref for item in kept] == ["r1"]
    assert collapsed == 0


@pytest.mark.parametrize("first,second", [("アプリが開かない", "通知が届かない"), ("कल", "कला")])
def test_distinct_unicode_complaints_remain_separate(first, second):
    kept, collapsed = dedupe_witnesses([_item("r1", "play_store", first), _item("r2", "support", second)])
    assert len(kept) == 2
    assert collapsed == 0


def test_distinct_emoji_sequences_remain_separate():
    items = [_item(str(index), "play_store", text)
             for index, text in enumerate(["❤️", "⚠️", "☹️", "☺️"])]
    kept, collapsed = dedupe_witnesses(items)
    assert len(kept) == 4
    assert collapsed == 0


@pytest.mark.parametrize("first,second", [("アプリが開かない。", "アプリが開かない"),
                                         ("CAFÉ broken", "cafe\u0301 broken"),
                                         ("Sync\tkeeps\n failing!", "sync keeps failing")])
def test_equivalent_unicode_and_whitespace_variants_collapse(first, second):
    kept, collapsed = dedupe_witnesses([_item("r1", "play_store", first), _item("r2", "support", second)])
    assert len(kept) == 1
    assert collapsed == 1
    assert kept[0].meta["also_seen_in"] == ["support"]
