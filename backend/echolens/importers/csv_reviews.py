"""Universal CSV review import (v7.1).

Widens the evidence base beyond the two live scrapers: a PM can drop in an App
Store export, a Zendesk export, in-app feedback, or any spreadsheet of reviews.
Header mapping is forgiving (rating/score/stars, text/content/review/body,
date/created_at/at). Dedup by a content hash so re-importing is idempotent.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import Review

_TEXT_KEYS = ("text", "content", "review", "body", "comment", "feedback")
_RATING_KEYS = ("rating", "score", "stars", "star")
_DATE_KEYS = ("date", "created_at", "at", "time", "timestamp", "created")
_VERSION_KEYS = ("version", "app_version", "reviewcreatedversion")
_OS_KEYS = ("os", "os_version", "device", "platform")
_SOURCE_KEYS = ("source", "store", "channel")
_AUTHOR_KEYS = ("author", "user", "username", "user_name", "reviewer", "name")

# The fields a person can match a column to, in the order the import screen
# shows them. Only `text` is required.
FIELDS = ("text", "rating", "version", "date", "source", "author")
_ALIASES = {"text": _TEXT_KEYS, "rating": _RATING_KEYS, "version": _VERSION_KEYS,
            "date": _DATE_KEYS, "source": _SOURCE_KEYS, "author": _AUTHOR_KEYS}
# A per-row "Source" value, normalised to the source keys the app knows.
_SOURCE_VALUES = {"google play": "play_store", "play store": "play_store", "play_store": "play_store",
                  "android": "play_store", "app store": "app_store", "app_store": "app_store",
                  "apple": "app_store", "ios": "app_store"}
SKIP_REASONS = {"no_text": "no review text", "no_rating": "no rating from 1 to 5",
                "duplicate": "already imported, or repeated in the file"}
MAX_IMPORT_ROWS = 10_000
UNDATED_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _pick(row: dict, keys) -> str | None:
    for k in keys:
        if row.get(k):
            return row[k]
    return None


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("iso", "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")) if fmt == "iso" else datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _int(raw: str | None) -> int | None:
    """A star rating, or None when the column is missing/unparseable.

    This used to return 0 on failure, which was catastrophic rather than
    merely lossy: every negativity filter in the codebase is `rating <= 2`,
    so an absent rating column made 0 the MOST negative value possible. A
    Zendesk export with no ratings imported as a corpus of 1-star complaints,
    the detector fired on it, and the investigator gathered "evidence" from
    what was often praise. None means unknown, and unknown rows are skipped.
    """
    try:
        value = float(str(raw).strip())
        return int(value) if value.is_integer() and 1 <= value <= 5 else None
    except (TypeError, ValueError):
        return None


def guess_mapping(columns: list[str]) -> dict[str, str | None]:
    """{field: column or None}, by the same loose aliases the importer has always
    used. A column is used for at most one field."""
    lowered = {c.lower().strip(): c for c in columns if c}
    out: dict[str, str | None] = {}
    used: set[str] = set()
    for field in FIELDS:
        hit = next((lowered[k] for k in _ALIASES[field] if k in lowered and lowered[k] not in used), None)
        out[field] = hit
        if hit:
            used.add(hit)
    return out


def _check_mapping(mapping: dict | None, columns: list[str]) -> dict[str, str | None] | None:
    if mapping is None:
        return None
    known = {c.lower().strip() for c in columns}
    clean: dict[str, str | None] = {}
    for field in FIELDS:
        col = mapping.get(field)
        if col and col.lower().strip() not in known:
            raise ValueError(f"the file has no column named \u201c{col}\u201d")
        clean[field] = col.lower().strip() if col else None
    if not clean["text"]:
        raise ValueError("choose the column that holds the review text")
    return clean


def _field(row: dict, field: str, mapping: dict | None) -> str | None:
    if mapping is None:
        # Without a mapping the importer reads exactly what it always read.
        return None if field in ("source", "author") else _pick(row, _ALIASES[field])
    col = mapping.get(field)
    return (row.get(col) or None) if col else None


def _rows(text: str):
    reader = csv.DictReader(io.StringIO(text))
    columns = [c for c in (reader.fieldnames or []) if c is not None]
    return columns, reader


def _parse_rows(text: str, product: str | None, source: str, mapping: dict | None) -> dict:
    """Shared by import and preview: the rows that would be imported, and why
    each other row would be skipped."""
    columns, reader = _rows(text)
    mapping = _check_mapping(mapping, columns)
    total = unrated = undated = 0
    reasons = {k: 0 for k in SKIP_REASONS}
    problems: list[dict] = []
    candidates: list[dict] = []
    seen: set[str] = set()

    def skip(line: int, why: str) -> None:
        reasons[why] += 1
        if len(problems) < 20:
            problems.append({"row": line, "reason": SKIP_REASONS[why]})

    for raw_row in reader:
        total += 1
        if total > MAX_IMPORT_ROWS:
            raise ValueError(f"CSV has more than {MAX_IMPORT_ROWS:,} data rows")
        line = total + 1   # the header is line 1
        row = {(k or "").lower().strip(): (v or "") for k, v in raw_row.items()}
        body = _field(row, "text", mapping)
        if not body or not body.strip():
            skip(line, "no_text")
            continue
        body = body.strip()
        rating = _int(_field(row, "rating", mapping))
        if rating is None:
            # No rating means we cannot say whether this is a complaint. Guessing
            # would make it a 1-star; the honest move is to skip it and report it.
            unrated += 1
            skip(line, "no_rating")
            continue
        created = _parse_date(_field(row, "date", mapping))
        if created is None:
            # The column is non-nullable and date-less exports are still useful
            # for qualitative search. Put them deliberately outside every live
            # detector window instead of inventing today's date, which turned an
            # old export into a fresh spike and moved product reference_now.
            created = UNDATED_SENTINEL
            undated += 1
        # The hash is unchanged by the new mapping (no author in it), so a file
        # imported before mappings existed still de-duplicates against itself.
        # Reviews keep no author, so a mapped Author column is not stored.
        ext_id = "csv_" + hashlib.sha1(
            f"{source}|{product}|{body}|{created.date()}".encode("utf-8")).hexdigest()[:20]
        if ext_id in seen:
            skip(line, "duplicate")
            continue
        seen.add(ext_id)
        row_source = (_field(row, "source", mapping) or "").strip().lower()
        candidates.append({
            "source": _SOURCE_VALUES.get(row_source, source), "ext_id": ext_id, "rating": rating,
            "text": body[:4000], "version": _field(row, "version", mapping),
            "os_version": _pick(row, _OS_KEYS), "created_at": created,
            "product": product, "_line": line,
        })
    return {"columns": columns, "candidates": candidates, "reasons": reasons, "problems": problems,
            "total": total, "unrated": unrated, "undated": undated}


def _existing(session: Session, product: str | None, ids: list[str]) -> set[str]:
    existing: set[str] = set()
    # Chunk below SQLite's bind-variable ceiling while keeping query count
    # bounded by file size, not one SELECT per CSV row.
    for start in range(0, len(ids), 500):
        existing.update(session.scalars(select(Review.ext_id).where(
            Review.product == product, Review.ext_id.in_(ids[start:start + 500]))).all())
    return existing


def preview_reviews_csv(session: Session, text: str, product: str | None = None, source: str = "csv",
                        mapping: dict | None = None, sample: int = 8) -> dict:
    """What an import would do, without writing: the columns, the first rows,
    the matching (guessed unless given), and every row that would be skipped."""
    columns, reader = _rows(text)
    first = []
    for raw_row in reader:
        first.append({k: (v or "") for k, v in raw_row.items() if k is not None})
        if len(first) >= sample:
            break
    guessed = guess_mapping(columns)
    use = mapping if mapping is not None else (guessed if guessed["text"] else None)
    if use is None:
        return {"columns": columns, "rows": first, "mapping": guessed, "total": None,
                "would_import": 0, "skipped": 0, "reasons": {}, "problems": [], "undated": 0,
                "error": "No column looks like review text — choose it below."}
    parsed = _parse_rows(text, product, source, use)
    existing = _existing(session, product, [c["ext_id"] for c in parsed["candidates"]])
    problems = list(parsed["problems"])
    for c in parsed["candidates"]:
        if c["ext_id"] in existing:
            parsed["reasons"]["duplicate"] += 1
            if len(problems) < 20:
                problems.append({"row": c["_line"], "reason": SKIP_REASONS["duplicate"]})
    would = len(parsed["candidates"]) - len(existing)
    return {"columns": columns, "rows": first, "mapping": use, "total": parsed["total"],
            "would_import": would, "skipped": parsed["total"] - would,
            "reasons": {SKIP_REASONS[k]: v for k, v in parsed["reasons"].items() if v},
            "problems": sorted(problems, key=lambda p: p["row"]), "undated": parsed["undated"],
            "error": None}


def import_reviews_csv(session: Session, text: str, product: str | None = None,
                       source: str = "csv", mapping: dict | None = None) -> dict:
    """Ingest a CSV of reviews.

    `mapping` ({field: column}, fields in FIELDS, `text` required) says which
    column is which; without it the loose aliases decide, as they always have.
    Returns {imported, skipped, unrated, undated, total, reasons}. `unrated` is
    reported separately because "your export had no rating column" is a
    fixable problem the user needs told, not a silent no-op; `reasons` says
    why every skipped row was skipped, in plain words.
    """
    parsed = _parse_rows(text, product, source, mapping)
    reasons = parsed["reasons"]
    candidates = parsed["candidates"]
    existing = _existing(session, product, [row["ext_id"] for row in candidates])
    imported = 0
    for row in candidates:
        row.pop("_line", None)
        if row["ext_id"] in existing:
            reasons["duplicate"] += 1
            continue
        session.add(Review(**row))
        imported += 1
    session.flush()
    total = parsed["total"]
    return {"imported": imported, "skipped": total - imported,
            "unrated": parsed["unrated"], "undated": parsed["undated"], "total": total,
            "reasons": {SKIP_REASONS[k]: v for k, v in reasons.items() if v}}
