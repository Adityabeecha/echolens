"""The unified feedback graph — one problem, many witnesses.

Theme discovery clusters complaints inside one channel. This clusters them
ACROSS channels, so a 1-star review, a GitHub issue, a support ticket and a
forum post about the same failure become one node with four witnesses rather
than four separate problems inflating each other's numbers.

The node is the unit a PM should reason about, and it carries three things the
per-channel view could never give them:

* **corroboration** — how independent the witnesses are, not how many there are;
* **channel of origin** — who is reporting it and, more usefully, who is not;
* **a deduplicated impact number** — the same person escalating in two places
  counts once, which matters most precisely when things are going wrong.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from echolens.feedback import (
    FeedbackItem, channel_meta, channel_of_origin, collect_items,
    configured_channels, corroboration, dedupe_witnesses)
from echolens.logging import get_logger
from echolens.search.embedder import cosine, get_embedder
from echolens.themes.discover import (
    MIN_CLUSTER_SIZE, _truncate, adaptive_threshold, banned_terms, group_and_label,
    is_usable_statement, product_terms, semantic_embeddings_available)

log = get_logger("feedback.graph")

WINDOW_DAYS = 90
# A node spanning this many channels is corroborated rather than merely loud.
CORROBORATED_CHANNELS = 3


def _cluster_across_channels(items: list[FeedbackItem]) -> list[list[int]]:
    """Group item indices by meaning, ignoring which channel they came from.

    Same engine choice as theme discovery: real embeddings cluster
    deterministically; without them the vectors provably cannot separate
    paraphrases, so grouping is left to the labelling call instead of being
    faked here.
    """
    texts = [i.text for i in items]
    if len(texts) < MIN_CLUSTER_SIZE:
        return []
    vectors = get_embedder().embed(texts)
    n = len(vectors)
    flat = [cosine(vectors[a], vectors[b]) for a in range(n) for b in range(a + 1, n)]
    threshold = adaptive_threshold(flat)

    sims = [[0.0] * n for _ in range(n)]
    for a in range(n):
        for b in range(a + 1, n):
            sims[a][b] = sims[b][a] = cosine(vectors[a], vectors[b])

    density = sorted(((sum(1 for b in range(n) if b != a and sims[a][b] >= threshold), -a)
                      for a in range(n)), reverse=True)
    labels = [-1] * n
    groups: list[list[int]] = []
    for _, neg_a in density:
        a = -neg_a
        if labels[a] != -1:
            continue
        members = [a] + [b for b in range(n)
                         if b != a and labels[b] == -1 and sims[a][b] >= threshold]
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        for m in members:
            labels[m] = len(groups)
        groups.append(members)
    return groups


def build_graph(session: Session, product: str | None = None, *, llm=None,
                days: int = WINDOW_DAYS, as_of: datetime | None = None,
                limit: int = 10) -> dict:
    """Every cross-channel problem node for this product."""
    from echolens.detector.detect import reference_now

    now = as_of or reference_now(session, product)
    since = now - timedelta(days=days)
    items = collect_items(session, product, since=since, until=now)
    configured = configured_channels(session, product)

    if len(items) < MIN_CLUSTER_SIZE:
        return {"product": product, "nodes": [], "items_considered": len(items),
                "channels": configured, "days": days, "engine": "none"}

    banned = banned_terms(product)
    own = product_terms(product)

    if semantic_embeddings_available():
        groups = _cluster_across_channels(items)
        raw = {}
        engine = "embeddings"
        if groups and llm is not None:
            prepared = [{"count": len(g), "verbatims": [items[m].text for m in g[:3]]}
                        for g in groups]
            from echolens.themes.discover import label_clusters
            raw = {int(l.get("index", -1)): l for l in label_clusters(prepared, llm, product)}
    else:
        groups, raw = [], {}
        engine = "llm_grouping"
        for i, g in enumerate(group_and_label([it.text for it in items], llm, product, limit)):
            members = [int(x) for x in (g.get("review_ids") or [])
                       if isinstance(x, int) and 0 <= int(x) < len(items)]
            members = list(dict.fromkeys(members))
            if len(members) < MIN_CLUSTER_SIZE:
                continue
            groups.append(members)
            raw[len(groups) - 1] = g

    nodes = []
    for idx, members in enumerate(groups):
        group_items = [items[m] for m in members]
        corr = corroboration(group_items)
        kept, _ = dedupe_witnesses(list(group_items))

        label = raw.get(idx) or {}
        statement = " ".join(str(label.get("statement", "")).split())
        confidence = float(label.get("label_confidence") or 0.0)
        if not statement or confidence < 0.5 or not is_usable_statement(statement, banned, own):
            statement = _truncate(kept[0].text if kept else group_items[0].text)
            source = "verbatim"
        else:
            statement = _truncate(statement)
            source = "model"

        nodes.append({
            "id": f"node-{idx + 1}",
            "statement": statement,
            "label_source": source,
            "corroboration": corr,
            "origin": channel_of_origin(corr, configured),
            # THE number: witnesses after cross-channel dedupe, never the raw sum
            "impact_witnesses": len(kept),
            "raw_mentions": len(group_items),
            "witnesses": [
                {"ref": w.ref, "channel": w.channel,
                 "label": channel_meta(w.channel)["label"],
                 "audience": w.audience, "text": _truncate(w.text, 220),
                 "also_seen_in": w.meta.get("also_seen_in") or []}
                for w in kept[:6]
            ],
        })

    # Breadth first: a problem four channels agree on outranks a louder one that
    # only a single channel has noticed.
    nodes.sort(key=lambda n: (-n["corroboration"]["distinct_channels"],
                              -n["corroboration"]["score"],
                              -n["impact_witnesses"]))
    return {"product": product, "nodes": nodes[:limit], "items_considered": len(items),
            "channels": configured, "days": days, "engine": engine,
            "corroborated": len([n for n in nodes
                                 if n["corroboration"]["distinct_channels"] >= CORROBORATED_CHANNELS])}


def evidence_breadth(session: Session, refs: list[str], product: str | None = None,
                     days: int = WINDOW_DAYS, as_of: datetime | None = None) -> dict:
    """How broadly a FINDING's cited evidence is corroborated.

    The two-source rule already demands two distinct sources. This reports the
    actual spread so a finding can say "proven across reviews, GitHub and
    support" instead of just claiming enough boxes were ticked.
    """
    from echolens.detector.detect import reference_now

    now = as_of or reference_now(session, product)
    wanted = set(refs or [])
    if not wanted:
        return {"score": 0.0, "distinct_channels": 0, "channels": [],
                "witnesses": 0, "collapsed_duplicates": 0, "band": "single-source"}
    items = [i for i in collect_items(session, product, since=now - timedelta(days=days),
                                      until=now, negatives_only=False)
             if i.ref in wanted]
    return corroboration(items)
