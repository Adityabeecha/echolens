"""Semantic search: embedding backfill, cosine, and keyword-preserving augment."""
from __future__ import annotations

from echolens.search.embedder import HashEmbedder, cosine
from echolens.search.semantic import augment, embed_corpus
from echolens.tools.search_reviews import search_reviews


def test_hash_embedder_is_deterministic_and_normalized():
    e = HashEmbedder(dim=128)
    a1 = e.embed(["battery drain overnight"])[0]
    a2 = e.embed(["battery drain overnight"])[0]
    assert a1 == a2
    assert abs(sum(x * x for x in a1) - 1.0) < 1e-6  # unit vector
    # identical text → cosine 1; disjoint text → lower
    b = e.embed(["completely different words here"])[0]
    assert cosine(a1, a2) > 0.99
    assert cosine(a1, b) < cosine(a1, a2)


def test_augment_is_noop_without_embeddings(session):
    # synthetic corpus has no embeddings yet → augment returns nothing
    from echolens.db.models import Review
    rows = session.query(Review).limit(50).all()
    assert augment("battery", rows, set(), lambda r: r.text, 5) == []


def test_keyword_search_unchanged_before_embedding(session):
    r = search_reviews(session, "battery drain background", date_from="2026-07-11", rating_max=2)
    assert r["total_matches"] > 20  # same as the M1 keyword contract


def test_embed_corpus_then_augment_activates(session):
    counts = embed_corpus(session)
    assert counts["reviews"] > 0
    from echolens.db.models import Review
    rows = session.query(Review).filter(Review.created_at >= "2026-07-11").all()
    hits = augment("battery drain", rows, set(), lambda r: r.text, 5)
    assert hits  # embeddings present → semantic hits returned
    assert all(getattr(h, "embedding", None) for h in hits)
