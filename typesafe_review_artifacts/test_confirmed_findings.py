import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend' / 'tests'))
from test_v8_scoping import client
from sqlalchemy import select
from echolens.db.models import Product, LLMCall
from datetime import datetime, timezone, timedelta


def test_empty_product_sources_do_not_include_other_products(client):
    tc, _, Session = client
    with Session() as s:
        p = Product(name='Empty product')
        s.add(p)
        s.commit()
        pid = p.id
    response = tc.get(f'/sources?product_id={pid}')
    assert response.status_code == 200
    assert response.json()['connected'] == []


def test_month_to_date_excludes_previous_month_spend(client):
    tc, ids, Session = client
    with Session() as s:
        old = s.scalar(select(LLMCall).order_by(LLMCall.id))
        old.created_at = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        old.cost = 4.0
        s.add(LLMCall(investigation_id=old.investigation_id, agent='test', model='test', tokens_in=1, tokens_out=1, cost=0.02, ms=1))
        s.commit()
    response = tc.get(f"/costs/summary?product_id={ids['Alpha']}")
    assert response.status_code == 200
    assert response.json()['month_to_date'] == 0.02


def test_non_latin_feedback_is_not_silently_discarded():
    from echolens.feedback import FeedbackItem, dedupe_witnesses
    item = FeedbackItem(ref='review-ja', channel='play_store', text='\u30a2\u30d7\u30ea\u304c\u958b\u304b\u306a\u3044', created_at=datetime.now(timezone.utc))
    kept, collapsed = dedupe_witnesses([item])
    assert len(kept) == 1
    assert collapsed == 0
