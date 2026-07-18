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

log = get_logger("semantic")

_TEXT_OF = {
    Review: lambda r: r.text,
    Issue: lambda r: f"{r.title} {r.body_snippet}",
    Post: lambda p: p.text_snippet,
}

# Minimum cosine similarity for a semantic-only hit to count.
SEMANTIC_THRESHOLD = 0.35


def embed_corpus(session: Session, batch: int = 256) -> dict[str, int]:
    """Embed every corpus row missing an embedding. Idempotent."""
    embedder = get_embedder()
    counts = {}
    for model, text_of in _TEXT_OF.items():
        rows = session.scalars(select(model).where(model.embedding.is_(None))).all()
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


def augment(
    query: str,
    rows: list,
    exclude: set,
    text_of: Callable,
    limit: int,
) -> list:
    """Rows semantically close to `query` that are NOT already in `exclude`,
    ranked by cosine similarity. Empty if the rows carry no embeddings."""
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
