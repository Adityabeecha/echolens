"""Synthetic "Lumo" demo dataset (PRD §10). Deterministic — fixed RNG seed.

The story (X = v3.2 release day, 2026-07-08):
- ~6 months of reviews with baseline themes (UI praise, occasional crashes,
  ~3% battery mentions among negatives).
- v3.2 ships "automatic background photo sync (default ON)" on X.
- Battery-complaint share of negative reviews jumps starting X+3 — but only
  for users on 3.2.x. v3.1 users on Android 15 stay flat (this kills the decoy).
- Android 15 OS rollout began X-1 (the decoy).
- 4 GitHub issues about sync/battery filed X+4..X+8; one blames the OS update
  (red herring that forces hypothesis competition).
- A second, unrelated mini-anomaly: print-shipping-cost complaints after a
  pricing announcement — deliberately thin evidence (no version correlation,
  no corroborating GitHub issues) so the honest outcome is
  `insufficient_evidence`.

Expected outcomes (documented so the demo is verifiable):
- demo1: H_sync supported (~0.85), H_os rejected.
- demo2: no hypothesis passes the bar; best < 0.5.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from echolens.db.models import AnomalyEvent, Issue, Post, Release, Review

SEED = 42
X = datetime(2026, 7, 8, tzinfo=timezone.utc)          # v3.2 release day
START = X - timedelta(days=171)                         # ~6 months of history
END = datetime(2026, 7, 17, tzinfo=timezone.utc)        # "today"
ANDROID15_DAY = X - timedelta(days=1)                   # decoy OS rollout
BATTERY_SPIKE_DAY = X + timedelta(days=3)
PRICING_POST_DAY = datetime(2026, 7, 4, tzinfo=timezone.utc)

POSITIVE = [
    "Beautiful app, the gallery layout is gorgeous. Editing tools are great too.",
    "Love the new album sharing. Clean UI, fast, exactly what I wanted.",
    "Best photo app I've used. The timeline view is really well designed.",
    "Great update, love the interface. Five stars.",
    "Smooth and simple. The print ordering worked perfectly.",
]
NEUTRAL = [
    "Decent app but search could be better. Sometimes tags don't stick.",
    "Good overall, wish it had a desktop version.",
    "Fine for basics. Would like more editing filters.",
]
CRASH = [
    "App crashed while exporting an album. Had to restart twice.",
    "Keeps crashing when I open large videos. Please fix.",
    "Crash on startup after clearing cache. Reinstall fixed it.",
]
BATTERY_BASELINE = [
    "Battery use seems a bit high when editing for a long time.",
    "Noticed some battery drain during big uploads, otherwise fine.",
]
BATTERY_SPIKE = [
    "Phone dies by 2pm since the last update. Never had battery problems before. Uninstalling.",
    "Massive battery drain after updating. Phone gets hot even when I'm not using the app.",
    "Battery destroyed since the update. Background activity is constant, drain is unreal.",
    "Since v3.2 my battery drains overnight. Something runs in the background nonstop.",
    "Update killed my battery. 8% an hour doing nothing. The background sync thing has to go.",
    "Phone hot in my pocket, battery gone by lunch. Started right after the latest update.",
]
SHIPPING = [
    "Print quality is fine but shipping cost is ridiculous now. Almost doubled.",
    "Why does shipping cost more than the prints? Canceling my order.",
    "The new print prices plus shipping fees are way too high. Disappointed.",
    "Shipping charges went up again. Prints used to be a great deal.",
]

BASELINE_ISSUES = [
    ("Export fails for HEIC files on some devices", "Exporting HEIC images fails silently on a subset of devices."),
    ("Album sort order resets after app restart", "Custom sort order in albums reverts to date-added after restart."),
    ("Search does not match diacritics", "Searching 'cafe' does not match photos tagged 'café'."),
    ("Video thumbnails occasionally blank", "Grid shows blank thumbnails for some 4K videos until scroll."),
    ("Dark mode contrast low on OLED", "Some text is hard to read with OLED dimming enabled."),
    ("[pre-3.2] sync toggle missing from settings", "There is no way to control sync behavior from settings."),
]
SYNC_ISSUES = [
    ("BackgroundSyncWorker wakelock never released when queue empty",
     "BackgroundSyncWorker acquires a partial wakelock on start but only releases it after a successful upload. "
     "With an empty queue it spins holding the lock indefinitely. Repro on 3.2.0. Battery drain ~8%/hr since 3.2 when sync enabled.",
     4, 14),
    ("Battery drain after 3.2 update",
     "Since updating to 3.2.0 battery usage attributed to Lumo tripled. Suspect the new background sync. "
     "Edit: could also be the Android 15 update that rolled out the same week — my friend on Android 15 says his battery is worse too.",
     5, 9),
    ("Sync runs on metered connection",
     "Background photo sync uploads over mobile data even when 'Wi-Fi only' is expected. Drains data and battery on 3.2.0.",
     6, 5),
    ("Sync worker restarts in a loop when storage is full",
     "When device storage is full the sync worker retries in a tight loop on 3.2.0, spiking CPU and battery.",
     8, 3),
]


# Corpus anchoring. The story is built around fixed dates (END = "today").
# generate(session, anchor=None) keeps those exact dates (eval/golden tests rely
# on them); anchor="today" or a datetime/date re-bases every date so the corpus
# ENDS on that day, preserving every relative offset in the story.
ANCHOR_TODAY = "today"


def _shift_for(anchor) -> timedelta:
    if anchor is None:
        return timedelta(0)
    if anchor == ANCHOR_TODAY:
        n = datetime.now(timezone.utc)
        target = datetime(n.year, n.month, n.day, tzinfo=timezone.utc)
    elif isinstance(anchor, datetime):
        target = anchor if anchor.tzinfo else anchor.replace(tzinfo=timezone.utc)
        target = target.replace(hour=0, minute=0, second=0, microsecond=0)
    elif hasattr(anchor, "year") and hasattr(anchor, "month") and hasattr(anchor, "day"):
        target = datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc)
    else:
        raise ValueError(f"anchor must be None, 'today', a date or a datetime, got {anchor!r}")
    return target - END


def _version_for(rng: random.Random, day: datetime, shift: timedelta = timedelta(0)) -> str:
    """App-version adoption: 3.0 → 3.1 (Apr 20) → 3.2 (Jul 8), gradual uptake."""
    v31 = datetime(2026, 4, 20, tzinfo=timezone.utc) + shift
    x = X + shift
    if day < v31:
        return "3.0.2" if rng.random() < 0.8 else "2.9.1"
    if day < x:
        return "3.1." + str(rng.choice([0, 1])) if rng.random() < 0.85 else "3.0.2"
    # after v3.2 ships, adoption ramps ~15%/day up to 90%
    adoption = min(0.9, 0.15 * ((day - x).days + 1))
    return "3.2.0" if rng.random() < adoption else "3.1.1"


def _os_for(rng: random.Random, day: datetime, shift: timedelta = timedelta(0)) -> str:
    a15 = ANDROID15_DAY + shift
    if day < a15:
        return "Android 14"
    adoption = min(0.6, 0.1 * ((day - a15).days + 1))
    return "Android 15" if rng.random() < adoption else "Android 14"


def generate(session: Session, anchor=None) -> dict[str, int]:
    """Seed the full Lumo story. Returns row counts.

    `anchor=None` keeps the legacy fixed dates (story ends 2026-07-17). Pass
    anchor="today" (seed / bootstrap path) so the demo is always current."""
    shift = _shift_for(anchor)
    X = globals()["X"] + shift
    START = globals()["START"] + shift
    END = globals()["END"] + shift
    BATTERY_SPIKE_DAY = globals()["BATTERY_SPIKE_DAY"] + shift
    PRICING_POST_DAY = globals()["PRICING_POST_DAY"] + shift
    rng = random.Random(SEED)
    counts = {"reviews": 0, "issues": 0, "posts": 0, "releases": 0, "anomalies": 0}

    # releases -----------------------------------------------------------
    releases = [
        Release(version="3.0.0", released_at=datetime(2026, 2, 3, tzinfo=timezone.utc) + shift,
                notes="Lumo v3.0.0 — New: redesigned gallery and timeline. New: dark theme tokens. Fixed: startup crash on tablets."),
        Release(version="3.1.0", released_at=datetime(2026, 4, 20, tzinfo=timezone.utc) + shift,
                notes="Lumo v3.1.0 — New: print ordering. Improved: search speed. Fixed: HEIC export failures."),
        Release(version="3.2.0", released_at=X,
                notes="Lumo v3.2.0 — New: automatic background photo sync, enabled by default for all users. Improved: album sharing. Fixed: crash on RTL locales."),
    ]
    session.add_all(releases)
    counts["releases"] = len(releases)

    # reviews ------------------------------------------------------------
    n = 0
    day = START
    while day <= END:
        per_day = rng.randint(14, 19)
        post_spike = day >= BATTERY_SPIKE_DAY
        # the anomaly itself: extra 1-star volume once the spike starts
        if post_spike:
            per_day += rng.randint(6, 9)
        for _ in range(per_day):
            n += 1
            version = _version_for(rng, day, shift)
            os_v = _os_for(rng, day, shift)
            r = rng.random()
            on_32 = version.startswith("3.2")

            if post_spike and on_32 and r < 0.42:
                # the story beat: battery complaints from 3.2.x users only
                rating, text = 1 if rng.random() < 0.8 else 2, rng.choice(BATTERY_SPIKE)
            elif day >= PRICING_POST_DAY and r < 0.06:
                # mini-anomaly: shipping-cost complaints, version-agnostic
                rating, text = rng.choice([1, 2, 3]), rng.choice(SHIPPING)
            elif r < 0.09:
                rating, text = rng.choice([1, 2]), rng.choice(CRASH)
            elif r < 0.11:
                # baseline battery grumbles (~2-3% of negatives), all versions
                rating, text = rng.choice([2, 3]), rng.choice(BATTERY_BASELINE)
            elif r < 0.30:
                rating, text = 3, rng.choice(NEUTRAL)
            else:
                rating, text = rng.choice([4, 5, 5]), rng.choice(POSITIVE)

            ts = day + timedelta(minutes=rng.randint(0, 1439))
            session.add(Review(
                source="play_store", ext_id=f"ps_{n:05d}", rating=rating, text=text,
                version=version, os_version=os_v, created_at=ts,
            ))
        day += timedelta(days=1)
    counts["reviews"] = n

    # github issues ------------------------------------------------------
    num = 2700
    for title, body in BASELINE_ISSUES:
        num += rng.randint(3, 25)
        offset = rng.randint(5, 165)
        session.add(Issue(
            ext_id=f"#{num}", title=title, body_snippet=body,
            state=rng.choice(["open", "closed"]), reactions=rng.randint(0, 6),
            created_at=START + timedelta(days=offset),
        ))
    for title, body, day_offset, reactions in SYNC_ISSUES:
        num += rng.randint(1, 6)
        session.add(Issue(
            ext_id=f"#{num}", title=title, body_snippet=body,
            state="open", reactions=reactions,
            created_at=X + timedelta(days=day_offset),
        ))
    counts["issues"] = len(BASELINE_ISSUES) + len(SYNC_ISSUES)

    # reddit posts -------------------------------------------------------
    posts = [
        Post(ext_id="rd_001", subreddit="LumoApp", created_at=PRICING_POST_DAY,
             text_snippet="Announcement: updated print pricing and shipping rates start this week."),
        Post(ext_id="rd_002", subreddit="LumoApp", created_at=X + timedelta(days=4),
             text_snippet="Anyone else's battery wrecked since the Lumo update? Phone is hot all day."),
        Post(ext_id="rd_003", subreddit="LumoApp", created_at=X + timedelta(days=6),
             text_snippet="PSA: turning off background sync in 3.2 fixed my battery drain."),
        Post(ext_id="rd_004", subreddit="androidapps", created_at=X - timedelta(days=30),
             text_snippet="Lumo feels slow on older phones lately, anyone else?"),
    ]
    session.add_all(posts)
    counts["posts"] = len(posts)

    # anomaly events (M1: pre-seeded; M2 detector will emit these) --------
    anomalies = [
        AnomalyEvent(
            slug="demo1", type="negative_review_spike",
            metric="daily 1-star review volume", delta=0.23, z=3.8, window="7d",
            description=f"1-star reviews +23% week-over-week on Play Store; spike began {BATTERY_SPIKE_DAY.date()}.",
        ),
        AnomalyEvent(
            slug="demo2", type="theme_volume_surge",
            metric="shipping-cost complaint share of negatives", delta=0.12, z=2.1, window="7d",
            description=f"Print-shipping cost complaints +12% since {PRICING_POST_DAY.date()}.",
        ),
    ]
    session.add_all(anomalies)
    counts["anomalies"] = len(anomalies)

    return counts
