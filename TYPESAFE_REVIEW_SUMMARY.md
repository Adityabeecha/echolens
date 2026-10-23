# EchoLens TypeSafe review and fixes

Updated 22 September 2026.

The TypeSafe scan completed 259 planned requests across 184 eligible files using `jev-latest`. Follow-up investigation reproduced and fixed defects across API access, ingestion, reporting, planning, and frontend asynchronous updates. The original raw scan describes the pre-fix source. A separate post-fix review completed all 55 planned requests across 31 changed files; its artifacts are in `typesafe_review_artifacts/postfix/`.

## Confirmed fixes

- **Access and product isolation:** guest snapshots respect visible products; finding issue creation uses the finding's product repository; missing repository configuration cannot borrow another product's source; authentication-required staging blocks anonymous first signup; Google tokens accept either supported issuer form. Unscoped learning no longer includes other products' investigations, and finding migration inherits its investigation's product before fallback.
- **Collection and import:** partial ingestion failures report failure and retain the pre-run checkpoint for replay, including equal timestamps and descending batches. GitHub releases survive the issue limit and cannot advance the issue checkpoint. PR IDs include their repository. Malformed Chrome responses fail visibly. Invalid CSV ratings remain unrated.
- **Reporting and feedback:** monthly costs use the current UTC month through today; Unicode and symbol-only feedback survives deduplication; distinct long complaints no longer collide on a truncated prefix. Date-only upper bounds include the entire day. Resolution rates count distinct cases. Follow-up answers avoid unsupported cohort exclusivity claims.
- **Planning and reliability:** quarter-plan edits preserve explicit user overrides without pinning automatic selections; empty notes can clear saved notes. Duplicate migration is idempotent. Model outages defer anomalies for retry, and model retries plus JSON repair share the remaining timeout budget.
- **Frontend:** stale product/case replies are discarded, fallback trace polling does not overlap, and terminal responses stop polling.

## Verification

- Final full backend suite: **639 passed, 1 skipped** in 68.29 seconds (fresh pre-commit run), with isolated test settings and no live service credentials. The skip is the existing development-mode authentication test. One existing Starlette/httpx deprecation warning remains.
- Live read-only GitHub collector check: public `fastapi/fastapi` API returned 2 issues and 30 releases successfully, using no credentials and making no database writes. This checks live response compatibility, not full backfill.
- Frontend production build: **passed** (TypeScript and Vite 8.2.1).
- Frontend regression harness: **6 passed**; responsive, sidebar, and theme checks also passed. The harness is deterministic and is not browser end-to-end coverage.
- Confirmed defects have regression coverage in `backend/tests/test_typesafe_*.py` and `frontend/scripts/verify-typesafe-regressions.mjs`.
- API, collector, and frontend patch reviews completed. The final additional independent core review was unavailable because its agent reached a usage limit; the core diff was checked locally and included in the passing full suite.

## Post-fix TypeSafe assessment

All 55 requests returned reviewed status. TypeSafe still flags 46 contexts: 44 runtime, 35 correctness, 3 security, and 35 maintainability classifications, with overlap. These cannot be compared directly with the original full scan because the follow-up covers changed files only. The three security classifications refer to broad API excerpts (lines 399–807, 1197–1591, and 1995–2384), without a specific exploit or defect explanation. They remain unconfirmed; a passing regression suite does not dismiss them. Existing API triage and regression evidence explain the confirmed fixes. No clean security assessment is claimed.

## Remaining limits

TypeSafe flagged 135 request contexts (overlapping classifications: 123 runtime, 82 correctness, 9 security, 91 maintainability). These are probabilities, **not 135 verified bugs**. The fixes above address reproduced defects; remaining classifications are not certified clean.

Collector fetch windows still do not guarantee complete historical backfill. Existing legacy PR identifiers are not migrated, so refetching can create legacy/new duplicates. Chrome's undocumented endpoint, live OAuth/application-LLM integrations, PostgreSQL, and browser end-to-end behavior were not exercised. The browser overflow check lacked its required local CDP endpoint.

Credential screening omitted 131 lines across 32 files. No `.env` files, local databases, API keys, or runtime datasets were submitted. Empty package files, `frontend/src/tokens.css`, and `frontend/src/vite-env.d.ts` were excluded by the reused scanner. Completion means all planned screened requests finished, not exhaustive application coverage.

## Detailed artifacts

- `typesafe_review_artifacts/api_triage.md`
- `typesafe_review_artifacts/collector_triage.md`
- `typesafe_review_artifacts/frontend_triage.md`
- `typesafe_review_artifacts/core_triage.md`
- `typesafe_review_report.md` / `.json`: original classifications and reviewed ranges.
- `typesafe_review_plan.md` / `.json`: request manifest.
- `typesafe_redactions.json`: omitted filenames and line numbers.
