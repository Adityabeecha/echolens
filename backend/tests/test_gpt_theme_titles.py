"""UI-facing recurring theme labels retain evidence and identity separately."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from echolens.db.models import Base, Product, Review, Setting
from echolens.themes import discover

NOW = datetime(2026, 10, 22, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(db, texts):
    for i, text in enumerate(texts):
        db.add(Review(source="test", ext_id=str(i), product="Video", rating=1,
                      text=text, created_at=NOW))
    db.flush()


def cached_result(db, themes, considered=4):
    result = {"themes": themes, "reviews_considered": considered, "clustered": considered,
              "other": 0, "product": "Video", "days": 90, "engine": "embeddings"}
    db.add(Setting(key="themes:Video:90:8:_", value={
        "fingerprint": discover._fingerprint(db, "Video", 90, NOW), "result": result}))
    db.flush()
    return result


def theme(statement, slug="legacy-crashing-videos", count=2):
    return {"statement": statement, "slug": slug, "count": count,
            "verbatims": [statement], "label_source": "verbatim", "label_confidence": 0,
            "first_seen": "2026-10-01", "last_seen": "2026-10-22", "trend": "flat"}


@pytest.mark.parametrize("sentence,label", [
    ("I keep crashing whenever I open large videos", "Crash when opening large videos"),
    ("I crash on startup after clearing the cache", "Crash on startup after clearing cache"),
    ("My app keeps crashing on startup", "Crash on startup"),
    ("I'm crashing when I open my videos!", "Crash when opening videos"),
    ("ME and my VIDEOS keep crashing", "Videos crash"),
    ("I keep freezing whenever I load large videos", "Freeze when loading large videos"),
    ("I have to restart the app every time", "Repeated app restart required"),
    ("I do not like the new update", "Dislike of new update"),
    ("I lost all my saved videos", "Loss of saved videos"),
    ("My videos are not playing", "Video playback failure"),
    ("My videos won't play", "Video playback failure"),
    ("I cannot open my videos", "Failure to open videos"),
])
def test_existing_cache_displays_short_impersonal_labels_without_llm(db, sentence, label):
    original = cached_result(db, [theme(sentence)])
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert result["cached"] is True
    assert result["themes"][0]["statement"] == label
    assert result["themes"][0]["slug"] == "legacy-crashing-videos"
    assert result["themes"][0]["verbatims"] == [sentence]
    assert original["themes"][0]["statement"] == sentence
    assert discover.cached_themes(db, "Video", as_of=NOW) == result


def test_long_labels_fit_sixty_characters_without_cutting_a_word(db):
    sentence = "I keep crashing whenever I open large videos imported from external network storage folders"
    cached_result(db, [theme(sentence)])
    label = discover.cached_themes(db, "Video", as_of=NOW)["themes"][0]["statement"]
    assert len(label) <= 60
    assert label.startswith("Crash when opening large videos")
    assert label == "Crash when opening large videos imported from external\u2026"


def test_jaccard_threshold_merges_wording_variants_and_preserves_survivor_identity(db):
    first = theme("I keep crashing whenever I open large videos", "legacy-a")
    second = theme("Crash when opening large imported videos", "legacy-b")
    third = theme("Audio disappears after Bluetooth pairing", "audio-pairing")
    cached_result(db, [first, second, third], considered=6)
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert [t["slug"] for t in result["themes"]] == ["legacy-a", "audio-pairing"]
    assert result["themes"][0]["count"] == 4
    assert result["themes"][0]["verbatims"] == first["verbatims"] + second["verbatims"]
    assert result["clustered"] == 6 and result["other"] == 0


@pytest.mark.parametrize("other,merged", [
    ("Crash large imported recordings", True),          # 3/5 = 0.6
    ("Crash imported recordings", False),               # 2/5 = 0.4
    ("Freeze opening small recordings", False),
])
def test_jaccard_content_words_boundary(db, other, merged):
    cached_result(db, [theme("Crash opening large recordings", "first"), theme(other, "second")])
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert len(result["themes"]) == (1 if merged else 2)


def test_new_discovery_keeps_legacy_slug_and_raw_evidence_on_display(db, monkeypatch):
    sentence = "I keep crashing whenever I open large videos"
    seed(db, [sentence, "Opening large videos crashes every time"])
    monkeypatch.setattr(discover, "semantic_embeddings_available", lambda: True)
    class Embeddings:
        def embed(self, texts):
            return [[1.0, 0.0] for _ in texts]
    monkeypatch.setattr(discover, "get_embedder", lambda: Embeddings())
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert result["themes"][0]["statement"] == "Crash when opening large videos"
    assert result["themes"][0]["slug"] == "keep-crashing-whenever"
    assert result["themes"][0]["verbatims"][0] == sentence
    assert result["cached"] is False


def test_merging_new_overlapping_groups_counts_each_review_once(db, monkeypatch):
    seed(db, ["I keep crashing whenever I open large videos",
              "Crash when opening large videos",
              "Crash when opening large imported videos"])
    monkeypatch.setattr(discover, "semantic_embeddings_available", lambda: False)
    monkeypatch.setattr(discover, "group_and_label", lambda *args: [
        {"review_ids": [0, 1], "statement": "Crash when opening large videos",
         "slug": "original-a", "label_confidence": 0.9},
        {"review_ids": [1, 2], "statement": "Crash when opening large imported videos",
         "slug": "original-b", "label_confidence": 0.9},
    ])
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert len(result["themes"]) == 1
    assert result["themes"][0]["slug"] == "original-a"
    assert result["themes"][0]["merged_slugs"] == ["original-b"]
    assert result["themes"][0]["count"] == 3
    assert result["clustered"] == 3 and result["other"] == 0


def test_similarity_uses_full_title_before_display_truncation(db):
    prefix = "Crash when opening large videos imported from shared network storage "
    cached_result(db, [theme(prefix + " ".join(["alpha"] * 15), "first"),
                       theme(prefix + "beta gamma delta epsilon zeta eta theta iota kappa", "second")])
    # Short labels coincide, but content Jaccard is 10/20 = 0.5.
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert len(result["themes"]) == 2


def test_pronoun_only_cache_entries_do_not_merge_on_empty_content(db):
    cached_result(db, [theme("I my me", "first"), theme("Me my I", "second")])
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert [t["slug"] for t in result["themes"]] == ["first", "second"]
    assert all(t["statement"] == "Recurring complaint" for t in result["themes"])


def test_merging_retains_already_queued_member_slug(db):
    from echolens.orchestrator.queue import enqueue_theme, find_existing
    product = Product(name="Video")
    db.add(product)
    db.flush()
    stored_slug = f"theme-p{product.id}-legacy-b"
    enqueue_theme(db, product_id=product.id, slug=stored_slug,
                  statement="I crash when opening large imported videos")
    cached_result(db, [theme("Crash when opening large videos", "legacy-a"),
                       theme("Crash when opening large imported videos", "legacy-b")])
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert len(result["themes"]) == 1
    assert result["themes"][0]["slug"] == "legacy-b"
    assert result["themes"][0]["merged_slugs"] == ["legacy-a"]
    assert find_existing(db, product.id, f"theme-p{product.id}-{result['themes'][0]['slug']}")["reason"] == "queued"


@pytest.mark.parametrize("trend", ["up", "down"])
def test_merging_preserves_agreeing_trends(db, trend):
    first = {**theme("Crash when opening large videos", "legacy-a"), "trend": trend}
    second = {**theme("Crash when opening large imported videos", "legacy-b"), "trend": trend}
    cached_result(db, [first, second])
    result = discover.cached_themes(db, "Video", as_of=NOW)
    assert len(result["themes"]) == 1
    assert result["themes"][0]["trend"] == trend
