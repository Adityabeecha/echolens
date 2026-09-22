# Collector and CSV triage

Reviewed the current patches and their ingestion flow using injected offline fixtures and in-memory SQLite. No live services or .env files were accessed.

| File | Confirmed change | Remaining limits / uncertainty |
| --- | --- | --- |
| collectors/base.py | Partial item failures now make CollectResult.ok false, consistent with persisted error status. Any failed item retains the entire pre-run watermark, while successful upserts persist safely for replay. Regressions cover equal timestamps and descending prefetched input, including repair and successful replay. | A permanently malformed row intentionally stalls cursor advancement and reports error until repaired. |
| collectors/play_store.py | Selected reviews now ingest oldest-first, retaining an older failed review for retry rather than moving the cursor past it. | Bounded newest-first remote fetch does not guarantee complete historical backfill. Sorting a selected batch does not solve omitted rows outside that batch. |
| collectors/github.py | Releases no longer disappear behind a full issue limit and never advance the issue-only watermark. Added oldest-first issue ingestion after selection; reproduced a descending issue page advancing past a failed older issue before this fix. | Release collection is a separate bounded window (30 remotely), so total fetched can exceed the issue limit. Existing newest-first pagination plus watermark can omit older backlog beyond the bounded issue page; fixing complete backfill requires separate pagination/cursor design. |
| collectors/github_extra.py | Repository-qualified PR identifiers prevent two repositories' PR number 1 colliding within one product. | Existing persisted legacy PR identifiers are not migrated; re-fetching them can create duplicate legacy/new records. Commit IDs remain SHA-based. |
| collectors/chrome_web_store.py | Malformed nested envelopes and non-positional rows fail loudly instead of becoming healthy empty results. | Endpoint is undocumented and not live-validated. Positional lists with unusable fields can still be skipped by existing normalisation. |
| importers/csv_reviews.py | Only integral 1–5 ratings are accepted; fractional, out-of-range, infinity, and NaN values count as unrated rather than invented ratings. | This deliberately changes prior clamping behavior; no migration of existing imported rows. |

## Verification

- New descending GitHub issue regression failed before the sort fix: watermark incorrectly became 2026-01-03 after the 2026-01-02 issue failed.
- Equal-timestamp and descending-prefetched replay regressions both failed before the conservative cursor fix.
- After the fixes: `test_typesafe_collectors.py`, `test_collectors.py`, and `test_audit_2026_07_27.py`: **71 passed**, one existing Starlette/httpx deprecation warning.
- Updated the older audit assertion to expect the pre-run cursor instead of a partial checkpoint; partial checkpoints cannot safely represent equal-timestamp failures.
- Used `backend/.venv/Scripts/python.exe`, disabled pytest cache, and forced Settings initialization with `_env_file=None` before importing application modules.
- Parent task owns broad suite validation and unrelated patches.
