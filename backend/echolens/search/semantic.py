"""Semantic search over the corpus (v1.0).

`embed_corpus` fills the nullable `embedding` columns on ingestion/backfill.
`augment` is the keyword→semantic bridge the search tools call: it returns rows
that a keyword query MISSED but that are semantically close, so a search for
"battery drain" also surfaces "phone runs hot". It returns [] when no embeddings
exist (e.g. the synthetic corpus before backfill), so keyword search — and every
existing test — is unchanged until you explicitly embed.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Issue, Post, Review
from echolens.logging import get_logger
from echolens.search.embedder import cosine, get_embedder
from echolens.timeutil import aware_utc

log = get_logger("semantic")

_TEXT_OF = {
    Review: lambda r: r.text,
    Issue: lambda r: f"{r.title} {r.body_snippet}",
    Post: lambda p: p.text_snippet,
}

# Minimum cosine similarity for a semantic-only hit to count.
SEMANTIC_THRESHOLD = 0.35


def embed_corpus(session: Session, batch: int = 256,
                 product: str | None = None) -> dict[str, int]:
    """Embed every corpus row missing an embedding. Idempotent."""
    embedder = get_embedder()
    counts = {}
    for model, text_of in _TEXT_OF.items():
        stmt = select(model).where(model.embedding.is_(None))
        if product is not None:
            stmt = stmt.where(model.product == product)
        rows = session.scalars(stmt).all()
        n = 0
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            vecs = embedder.embed([text_of(r) for r in chunk])
            for r, v in zip(chunk, vecs):
                r.embedding = v
                n += 1
        counts[model.__tablename__] = n
        session.flush()
    log.info("embed_corpus", **counts)
    return counts


# Bounds on the DB-backed path. Scoring every embedded row of a product meant
# deserialising ~7,000 x 256 floats per search call at Firefox scale; the most
# recent SCAN_CAP candidates are what an investigation is about anyway.
SCAN_CAP = 2000
_ID_CHUNK = 500              # ids per IN (...) — well under every driver's limit
LAST_SCAN: dict | None = None   # what the last call scored, for measurement


def semantic_scores(session: Session, model, query: str, candidate_ids: list[int],
                    cap: int | None = None) -> dict[int, float]:
    """{id: similarity} for the candidates (newest first) above the threshold.

    Reads only (id, embedding) — never the text — for at most `cap`
    candidates, in chunks.
    """
    global LAST_SCAN
    ids = list(candidate_ids)[:SCAN_CAP if cap is None else cap]
    if not ids:
        LAST_SCAN = {"candidates": 0, "embeddings": 0}
        return {}
    qvec = get_embedder().embed([query])[0]
    scored: dict[int, float] = {}
    loaded = 0
    for i in range(0, len(ids), _ID_CHUNK):
        chunk = ids[i:i + _ID_CHUNK]
        for row_id, emb in session.execute(
                select(model.id, model.embedding).where(model.id.in_(chunk),
                                                        model.embedding.is_not(None))):
            loaded += 1
            sim = cosine(qvec, emb or [])
            if sim >= SEMANTIC_THRESHOLD:
                scored[row_id] = sim
    LAST_SCAN = {"candidates": len(ids), "embeddings": loaded}
    return scored


def augment(
    query: str,
    rows: list,
    exclude: set,
    text_of: Callable,
    limit: int,
    *,
    session: Session | None = None,
    model=None,
) -> list:
    """Rows semantically close to `query` that are NOT already in `exclude`,
    ranked by cosine similarity. Empty if the rows carry no embeddings.

    With `session` and `model`, the rows are the tool's already-filtered
    candidates loaded WITHOUT their embeddings (deferred), and only the
    embeddings of the newest SCAN_CAP of them are read — see semantic_scores.
    Without, the rows' own loaded embeddings are scored (the original path).
    """
    if session is not None and model is not None:
        skip = {id(r) for r in exclude}
        pool = [r for r in rows if id(r) not in skip]
        dated = sorted((r for r in pool if getattr(r, "created_at", None)),
                       key=lambda r: aware_utc(r.created_at), reverse=True)
        ordered = dated + [r for r in pool if not getattr(r, "created_at", None)]
        by_id = {r.id: r for r in ordered}
        scores = semantic_scores(session, model, query, list(by_id))
        hits = sorted(scores.items(), key=lambda kv: (-kv[1], _stable_key(by_id[kv[0]])))
        return [by_id[i] for i, _ in hits[:limit]]
    embedded = [r for r in rows if r not in exclude and getattr(r, "embedding", None)]
    if not embedded:
        return []
    qvec = get_embedder().embed([query])[0]
    scored = [(cosine(qvec, r.embedding), r) for r in embedded]
    hits = sorted(
        (sr for sr in scored if sr[0] >= SEMANTIC_THRESHOLD),
        key=lambda sr: (-sr[0], _stable_key(sr[1])),
    )
    return [r for _, r in hits[:limit]]


def _stable_key(row) -> str:
    return getattr(row, "ext_id", None) or str(getattr(row, "id", ""))
