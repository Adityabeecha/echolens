"""Embedding backends (v1.0). $0 by default.

`HashEmbedder` — deterministic hashing-trick bag-of-words → fixed-dim unit
vector. Zero dependencies, works everywhere, captures lexical overlap.
`SentenceTransformerEmbedder` — real semantic embeddings (paraphrase-aware:
"phone gets hot" ≈ "battery drain") when `sentence-transformers` is installed.

Both satisfy the same `Embedder` protocol so search code never branches on
which one is active. Selected via `settings.embedding_backend`.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

from echolens.config import settings

_WORD = re.compile(r"[a-z0-9']+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class HashEmbedder:
    """Feature-hashing bag of words, L2-normalized. Deterministic."""

    def __init__(self, dim: int | None = None):
        self.dim = dim or settings.embedding_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in _tokens(text):
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 8) & 1 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceTransformerEmbedder:  # pragma: no cover - exercised only when installed
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.encode(texts, normalize_embeddings=True)]


_cached: Embedder | None = None


def get_embedder() -> Embedder:
    global _cached
    if _cached is not None:
        return _cached
    backend = settings.embedding_backend
    if backend == "sentence-transformers":
        try:
            _cached = SentenceTransformerEmbedder()
            return _cached
        except Exception:
            pass  # fall back to hashing if the heavy dep is missing
    _cached = HashEmbedder()
    return _cached


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # embeddings are stored normalized, so dot == cosine
    return dot
