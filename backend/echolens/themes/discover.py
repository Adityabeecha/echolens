"""Theme discovery — cluster complaints by meaning, then label the clusters.

Counting n-grams was the bug. Frequency finds the words that are COMMON, not the
problems that are DISTINCT, so on real data it surfaced "i'm", "it's", the app's
own name, and half-phrases like "lines between". None of those are things a PM
can investigate.

The pipeline instead:
  reviews -> embed -> cluster by meaning -> ONE batched LLM call to label ->
  guards -> problem statements with the verbatims that produced them.

Two properties matter more than cluster quality:

* **It degrades, never breaks.** HDBSCAN if installed, else sklearn's
  agglomerative, else a pure-Python greedy cosine pass. Same for labelling: with
  no LLM the top verbatim becomes the title. A deploy container without the
  heavy extras still discovers themes.
* **It never invents a theme.** Every label is checked against the words that
  actually appear in its cluster, and a label the model is unsure about is
  replaced by a real customer sentence rather than a guess.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review, Setting
from echolens.logging import get_logger
from echolens.search.embedder import cosine, get_embedder
from echolens.textkit import STOPWORDS, tokenize
from echolens.timeutil import aware_utc

log = get_logger("themes.discover")

WINDOW_DAYS = 90
MIN_CLUSTER_SIZE = 2
# The similarity cut-off is derived per corpus (see adaptive_threshold) because
# the real embedding model and the hashing fallback are on different scales.
# These only bound it: never merge near-strangers, never demand near-identity.
SIM_FLOOR = 0.25
SIM_CEILING = 0.75
# Below this many 1-2 star reviews the negatives alone are too thin to cluster,
# so 3-star (the "it's ok but…" reviews) join them.
LOW_VOLUME_NEGATIVES = 30
MIN_LABEL_CONFIDENCE = 0.5
MAX_STATEMENT_CHARS = 90

# Words that can never be a theme on their own. Contractions and pronouns are
# what the n-gram version kept surfacing.
_CONTRACTIONS = {
    "i'm", "it's", "don't", "doesn't", "didn't", "can't", "won't", "isn't",
    "wasn't", "aren't", "couldn't", "wouldn't", "shouldn't", "i've", "i'd",
    "i'll", "you're", "they're", "that's", "there's", "here's", "let's", "im",
    "its", "dont", "doesnt", "cant", "wont",
}
_GENERIC = {
    "app", "apps", "application", "phone", "android", "ios", "device", "version",
    "star", "stars", "rating", "review", "reviews", "please", "thanks", "thank",
    "good", "bad", "great", "nice", "ok", "okay", "problem", "issue", "bug",
    "thing", "stuff", "time", "way", "lot", "bit", "user", "users", "everything",
    "nothing", "something", "anything",
}
_JUNK = _CONTRACTIONS | _GENERIC | STOPWORDS


@dataclass
class Cluster:
    """A group of reviews that complain about the same thing."""
    members: list[int] = field(default_factory=list)     # indices into the text list
    centroid: list[float] = field(default_factory=list)


# ── candidate selection ─────────────────────────────────────────────────


def _candidates(session: Session, product: str | None, days: int,
                as_of: datetime) -> list[Review]:
    """The reviews worth clustering: negatives, widened to 3-star when a product
    is too quiet for 1-2 star alone to say anything."""
    start = as_of - timedelta(days=days)

    def fetch(max_rating: int) -> list[Review]:
        stmt = select(Review).where(Review.rating <= max_rating,
                                    Review.created_at >= start,
                                    Review.created_at <= as_of)
        if product:
            stmt = stmt.where(Review.product == product)
        return [r for r in session.scalars(stmt).all() if (r.text or "").strip()]

    negatives = fetch(2)
    if len(negatives) < LOW_VOLUME_NEGATIVES:
        return fetch(3)
    return negatives


# ── clustering ──────────────────────────────────────────────────────────


def _cluster_hdbscan(vectors: list[list[float]], min_size: int) -> list[int] | None:
    try:  # pragma: no cover - only when the optional dep is installed
        import hdbscan  # type: ignore
        import numpy as np
    except Exception:
        return None
    try:  # pragma: no cover
        arr = np.array(vectors, dtype="float64")
        labels = hdbscan.HDBSCAN(min_cluster_size=min_size, metric="euclidean").fit_predict(arr)
        return [int(x) for x in labels]
    except Exception as err:  # pragma: no cover
        log.warning("hdbscan_failed", error=str(err))
        return None


def _cluster_agglomerative(vectors: list[list[float]], min_size: int,
                           threshold: float = SIM_FLOOR) -> list[int] | None:
    try:  # pragma: no cover - only when sklearn is installed
        import numpy as np
        from sklearn.cluster import AgglomerativeClustering  # type: ignore
    except Exception:
        return None
    try:  # pragma: no cover
        if len(vectors) < min_size:
            return None
        model = AgglomerativeClustering(
            n_clusters=None, metric="cosine", linkage="average",
            distance_threshold=1.0 - threshold)
        labels = model.fit_predict(np.array(vectors, dtype="float64"))
        return [int(x) for x in labels]
    except Exception as err:  # pragma: no cover
        log.warning("agglomerative_failed", error=str(err))
        return None


def adaptive_threshold(sims: list[float]) -> float:
    """Find the similarity cut-off from the data instead of hardcoding one.

    A fixed constant cannot work here: the real sentence-transformer model and
    the hashing fallback live on completely different scales, so a threshold
    tuned for one silently clusters everything (or nothing) on the other.

    Related and unrelated pairs form two humps, so a 1-D 2-means split separates
    them. When the humps nearly touch, the corpus is really about ONE topic —
    splitting it there would manufacture distinctions that don't exist, so we
    drop to the floor and let it be a single cluster.
    """
    vals = sorted(s for s in sims if s > 0)
    if len(vals) < 4:
        return SIM_FLOOR
    lo, hi = vals[0], vals[-1]
    for _ in range(25):  # deterministic: fixed init, fixed iteration count
        mid = (lo + hi) / 2
        low = [v for v in vals if v <= mid] or [lo]
        high = [v for v in vals if v > mid] or [hi]
        new_lo, new_hi = sum(low) / len(low), sum(high) / len(high)
        if abs(new_lo - lo) < 1e-6 and abs(new_hi - hi) < 1e-6:
            break
        lo, hi = new_lo, new_hi
    if hi - lo < 0.12:      # one topic, not two groups
        return SIM_FLOOR
    return min(max((lo + hi) / 2, SIM_FLOOR), SIM_CEILING)


def _cluster_greedy(vectors: list[list[float]], threshold: float | None = None) -> list[int]:
    """Dependency-free fallback. Seeds from the densest points so a real problem
    anchors its own cluster instead of being absorbed by whatever came first.

    Deterministic: ties break on index, so the same corpus always clusters the
    same way and a cached result stays valid.
    """
    n = len(vectors)
    if n == 0:
        return []
    sims = [[0.0] * n for _ in range(n)]
    flat: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            s = cosine(vectors[i], vectors[j])
            sims[i][j] = sims[j][i] = s
            flat.append(s)
    if threshold is None:
        threshold = adaptive_threshold(flat)
    density = [(sum(1 for j in range(n) if j != i and sims[i][j] >= threshold), -i)
               for i in range(n)]
    order = [(-d, -negi) for d, negi in sorted(density, reverse=True)]

    labels = [-1] * n
    next_label = 0
    for _, i in order:
        if labels[i] != -1:
            continue
        members = [i]
        for j in range(n):
            if j != i and labels[j] == -1 and sims[i][j] >= threshold:
                members.append(j)
        if len(members) < MIN_CLUSTER_SIZE:
            continue  # a lone review is not a theme — it stays in "other"
        for m in members:
            labels[m] = next_label
        next_label += 1
    return labels


def cluster_reviews(vectors: list[list[float]], min_size: int = MIN_CLUSTER_SIZE) -> list[Cluster]:
    """Group review vectors. -1 labels (noise) are dropped: unclustered reviews
    go to an 'other' bucket and are never shown as themes."""
    flat = [cosine(vectors[i], vectors[j])
            for i in range(len(vectors)) for j in range(i + 1, len(vectors))]
    threshold = adaptive_threshold(flat)
    labels = (_cluster_hdbscan(vectors, min_size)
              or _cluster_agglomerative(vectors, min_size, threshold)
              or _cluster_greedy(vectors, threshold))
    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        if lab < 0:
            continue
        groups.setdefault(lab, []).append(idx)

    out: list[Cluster] = []
    for _lab, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(members) < min_size:
            continue
        dim = len(vectors[members[0]])
        centroid = [sum(vectors[m][d] for m in members) / len(members) for d in range(dim)]
        out.append(Cluster(members=members, centroid=centroid))
    return out


def representatives(cluster: Cluster, vectors: list[list[float]], texts: list[str],
                    k: int = 3) -> list[str]:
    """The verbatims closest to the centroid — the sentences that most typify the
    complaint, shown under the statement so the label can be checked."""
    ranked = sorted(cluster.members, key=lambda m: -cosine(vectors[m], cluster.centroid))
    seen: list[str] = []
    for m in ranked:
        t = " ".join((texts[m] or "").split())
        if not t:
            continue
        if any(t[:60].lower() == s[:60].lower() for s in seen):
            continue  # near-duplicate reviews shouldn't fill all three slots
        seen.append(t)
        if len(seen) >= k:
            break
    return seen


# ── guards ──────────────────────────────────────────────────────────────


def product_terms(product_name: str | None, package_name: str | None = None) -> set[str]:
    """Tokens that name the product itself, from its display name and package."""
    out: set[str] = set()
    for source in (product_name, package_name):
        for tok in tokenize(source or ""):
            out.add(tok)
        for part in re.split(r"[.\-_\s]+", (source or "").lower()):
            if len(part) > 2:
                out.add(part)
    return out


def banned_terms(product_name: str | None, package_name: str | None = None) -> set[str]:
    """Words that must never become a theme for THIS product: junk words plus the
    product's own name. 'Joplin' appearing in Joplin's reviews is not a finding."""
    return set(_JUNK) | product_terms(product_name, package_name)


def is_usable_statement(statement: str, banned: set[str],
                        own_name: set[str] | None = None) -> bool:
    """A theme must be a specific problem, not a word.

    Rejects one-word labels, stopwords/contractions, anything made only of banned
    terms, and anything naming the product itself. That last one is strict on
    purpose: every review is about this product, so "Joplin is broken" carries no
    information, and the model was told explicitly not to do it — doing it anyway
    is a signal the label is weak.
    """
    s = (statement or "").strip()
    if len(s) < 12:
        return False
    words = [w for w in re.findall(r"[a-z']+", s.lower()) if w]
    if len(words) < 3:
        return False
    # len > 2 matters: without it two-letter glue ("is", "to") counts as content
    # and rescues a statement whose every real word is banned.
    content = [w for w in words if len(w) > 2 and w not in STOPWORDS and w not in _CONTRACTIONS]
    if not content:
        return False
    # every meaningful word is banned (product name, generics) -> says nothing
    if all(w in banned for w in content):
        return False
    if own_name and any(w in own_name for w in words):
        return False
    return True


def _truncate(text: str, limit: int = MAX_STATEMENT_CHARS) -> str:
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return (cut or t[:limit]).rstrip(",.;:") + "…"


def _slugify(text: str, banned: set[str]) -> str:
    words = [w for w in tokenize(text) if w not in banned][:3]
    return "-".join(words) or hashlib.sha1(text.encode()).hexdigest()[:8]


def semantic_embeddings_available() -> bool:
    """True when the real sentence-transformer model is loaded.

    This decides the whole strategy, so it is checked rather than assumed. The
    hashing fallback compares WORDS, and paraphrases of one complaint ("sync
    fails silently" / "sync just stops working") share almost none — measured on
    real review text, within-problem similarity overlaps between-problem
    similarity, so no threshold can separate them. Clustering on those vectors
    would produce confident nonsense.
    """
    from echolens.search.embedder import SentenceTransformerEmbedder
    return isinstance(get_embedder(), SentenceTransformerEmbedder)


# ── labelling (one batched call for every cluster) ──────────────────────

_LABEL_SYSTEM = (
    "You name product problems from customer reviews. For each cluster you are "
    "given real review snippets that were grouped together because they mean the "
    "same thing.\n\n"
    "For each cluster write ONE problem statement in the customer's voice, as a "
    "sentence a product manager could act on. Max 90 characters.\n"
    "GOOD: 'Editor inserts extra blank lines after the latest update'\n"
    "BAD: 'lines', 'editor issues', 'users unhappy', the app's own name\n\n"
    "Set label_confidence to how confident you are that the snippets share ONE "
    "specific problem. If the cluster is vague or mixed, say so with a low score "
    "— a low score is used, not punished."
)

_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "statement": {"type": "string"},
                    "slug": {"type": "string"},
                    "label_confidence": {"type": "number"},
                },
                "required": ["index", "statement", "slug", "label_confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


def label_clusters(clusters: list[dict], llm=None, product_name: str | None = None) -> list[dict]:
    """One batched LLM call for every cluster. Returns the raw model output keyed
    by index; the caller applies the guards."""
    if not clusters or llm is None:
        return []
    payload = [{"index": i, "review_count": c["count"], "snippets": c["verbatims"][:3]}
               for i, c in enumerate(clusters)]
    user = (f"PRODUCT: {product_name or 'this app'}\n"
            "Never use the product's own name in a statement.\n\n"
            f"CLUSTERS:\n{json.dumps(payload, indent=1)[:6000]}")
    try:
        res = llm.complete_json(_LABEL_SYSTEM, user, _LABEL_SCHEMA, "themes.label")
        data = res.parsed if hasattr(res, "parsed") else res
        return list((data or {}).get("clusters", []))
    except Exception as err:
        log.warning("theme_labelling_failed", error=str(err))
        return []


_GROUP_SYSTEM = (
    "You group customer reviews that describe the SAME underlying problem, then "
    "name each group.\n\n"
    "Rules:\n"
    "- A group needs at least 2 reviews. Reviews that match nothing go in no group.\n"
    "- Do not group by sentiment or by topic area - group by the specific problem.\n"
    "- Write each statement in the customer's voice, max 90 characters, as "
    "something a product manager could act on.\n"
    "GOOD: 'Editor inserts extra blank lines after the latest update'\n"
    "BAD: 'editor issues', 'users unhappy', the app's own name\n"
    "- label_confidence is how sure you are the group is ONE specific problem. "
    "A low score is used, not punished."
)


_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "review_ids": {"type": "array", "items": {"type": "integer"}},
                    "statement": {"type": "string"},
                    "slug": {"type": "string"},
                    "label_confidence": {"type": "number"},
                },
                "required": ["review_ids", "statement", "slug", "label_confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clusters"],
    "additionalProperties": False,
}


def group_and_label(texts: list[str], llm, product_name: str | None = None,
                    limit: int = 8) -> list[dict]:
    """Group AND label in ONE call, for when embeddings can't carry meaning.

    Still a single LLM call — the same budget as labelling pre-made clusters —
    but the model does the grouping it is actually good at instead of trusting
    vectors that cannot tell these complaints apart.
    """
    if not texts or llm is None:
        return []
    listing = [{"id": i, "text": t[:300]} for i, t in enumerate(texts[:120])]
    user = (f"PRODUCT: {product_name or 'this app'}\n"
            "Never use the product's own name in a statement.\n"
            f"Return at most {limit} groups, largest problems first.\n\n"
            f"REVIEWS:\n{json.dumps(listing, indent=1)[:12000]}")
    try:
        res = llm.complete_json(_GROUP_SYSTEM, user, _GROUP_SCHEMA, "themes.group")
        data = res.parsed if hasattr(res, "parsed") else res
        return list((data or {}).get("clusters", []))
    except Exception as err:
        log.warning("theme_grouping_failed", error=str(err))
        return []


# ── the pipeline ────────────────────────────────────────────────────────


def discover_themes(session: Session, product: str | None = None, *, llm=None,
                    days: int = WINDOW_DAYS, as_of: datetime | None = None,
                    limit: int = 8, package_name: str | None = None) -> dict:
    """Cluster this product's complaints and label each cluster."""
    from echolens.detector.detect import reference_now

    now = as_of or reference_now(session, product)
    rows = _candidates(session, product, days, now)
    if len(rows) < MIN_CLUSTER_SIZE:
        return {"themes": [], "product": product, "reviews_considered": len(rows),
                "clustered": 0, "other": len(rows), "days": days, "engine": "none"}

    texts = [r.text or "" for r in rows]
    banned = banned_terms(product, package_name)
    own = product_terms(product, package_name)
    dates_of = lambda members: [d for d in (aware_utc(rows[m].created_at) for m in members) if d]

    if semantic_embeddings_available():
        # Real embeddings: cluster deterministically, then ONE call to label.
        vectors = get_embedder().embed(texts)
        prepared = []
        for c in cluster_reviews(vectors):
            verbatims = representatives(c, vectors, texts)
            if not verbatims:
                continue
            d = dates_of(c.members)
            prepared.append({"count": len(c.members), "verbatims": verbatims,
                             "members": c.members,
                             "first_seen": min(d).date().isoformat() if d else None,
                             "last_seen": max(d).date().isoformat() if d else None,
                             "trend": _trend(d, now)})
        prepared.sort(key=lambda c: -c["count"])
        prepared = prepared[:limit]
        raw_by_index = {int(l.get("index", -1)): l for l in label_clusters(prepared, llm, product)}
        engine = "embeddings"
    else:
        # No semantic model: one call that groups AND labels. Same budget, and
        # the model does the grouping that weak vectors demonstrably cannot.
        prepared, raw_by_index = [], {}
        for i, g in enumerate(group_and_label(texts, llm, product, limit)):
            members = [int(x) for x in (g.get("review_ids") or [])
                       if isinstance(x, int) and 0 <= int(x) < len(texts)]
            members = list(dict.fromkeys(members))
            if len(members) < MIN_CLUSTER_SIZE:
                continue  # a group of one is not a theme
            d = dates_of(members)
            prepared.append({"count": len(members),
                             "verbatims": [" ".join(texts[m].split()) for m in members[:3]],
                             "members": members,
                             "first_seen": min(d).date().isoformat() if d else None,
                             "last_seen": max(d).date().isoformat() if d else None,
                             "trend": _trend(d, now)})
            raw_by_index[len(prepared) - 1] = g
        prepared.sort(key=lambda c: -c["count"])
        engine = "llm_grouping"

    themes = []
    for i, c in enumerate(prepared):
        raw = raw_by_index.get(i) or {}
        statement = " ".join(str(raw.get("statement", "")).split())
        confidence = float(raw.get("label_confidence") or 0.0)
        # Two ways a label is rejected, and both fall back to a REAL sentence a
        # customer wrote rather than a synthesized guess.
        fallback = not statement or confidence < MIN_LABEL_CONFIDENCE             or not is_usable_statement(statement, banned, own)
        if fallback:
            statement = _truncate(c["verbatims"][0])
            source = "verbatim"
        else:
            statement = _truncate(statement)
            source = "model"
        # A rejected label's slug is rejected too — otherwise the product name we
        # just refused as a title comes straight back as the identifier.
        slug = "" if fallback else str(raw.get("slug") or "").strip().lower()
        if not slug or not set(tokenize(slug.replace("-", " "))) - banned:
            slug = _slugify(statement, banned)
        themes.append({
            "slug": re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")[:48] or f"theme-{i+1}",
            "statement": statement,
            "label_source": source,
            "label_confidence": round(confidence, 2),
            "count": c["count"],
            "verbatims": c["verbatims"],
            "first_seen": c["first_seen"],
            "last_seen": c["last_seen"],
            "trend": c["trend"],
        })

    clustered = sum(t["count"] for t in themes)
    return {"themes": themes, "product": product, "reviews_considered": len(rows),
            "clustered": clustered, "other": len(rows) - clustered, "days": days,
            "engine": engine}


def _trend(dates: list[datetime], now: datetime) -> str:
    """'up' / 'down' / 'flat' from the split of this cluster's reviews across the
    recent half of the window. Only claimed when there's enough to compare."""
    if len(dates) < 4:
        return "flat"
    span = (now - min(dates)).days or 1
    midpoint = now - timedelta(days=span / 2)
    recent = sum(1 for d in dates if d >= midpoint)
    older = len(dates) - recent
    if older == 0:
        return "up" if recent else "flat"
    ratio = recent / older
    return "up" if ratio >= 1.5 else "down" if ratio <= 0.67 else "flat"


# ── caching (per product + window, invalidated by new data) ─────────────


def _fingerprint(session: Session, product: str | None, days: int, as_of: datetime) -> str:
    """Cheap corpus signature: re-running discovery is expensive (embeddings + an
    LLM call), so it must happen on NEW DATA, not on every page load."""
    rows = _candidates(session, product, days, as_of)
    newest = max((aware_utc(r.created_at) for r in rows if r.created_at), default=None)
    return f"{len(rows)}:{newest.isoformat() if newest else 'none'}"


def cached_themes(session: Session, product: str | None, *, llm=None, days: int = WINDOW_DAYS,
                  as_of: datetime | None = None, limit: int = 8,
                  package_name: str | None = None, force: bool = False) -> dict:
    """discover_themes with a per-(product, window) cache in the settings table."""
    from echolens.detector.detect import reference_now

    now = as_of or reference_now(session, product)
    key = f"themes:{product or '_'}:{days}"
    fp = _fingerprint(session, product, days, now)

    if not force:
        row = session.get(Setting, key)
        if row and isinstance(row.value, dict) and row.value.get("fingerprint") == fp:
            cached = dict(row.value.get("result") or {})
            cached["cached"] = True
            return cached

    result = discover_themes(session, product, llm=llm, days=days, as_of=now,
                             limit=limit, package_name=package_name)
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value={"fingerprint": fp, "result": result}))
    else:
        row.value = {"fingerprint": fp, "result": result}
    session.flush()
    result["cached"] = False
    return result
