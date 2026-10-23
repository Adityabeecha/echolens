# API follow-up triage

Reviewed the unfinished changes in `backend/echolens/api/app.py` and `google_auth.py`, their follow-up tests, and the runtime paths in `review.py`, `exporting.py`, `notify.py`, `auth.py`, configuration, and `backend/Dockerfile`.

## Confirmed fixes

- Guest snapshot: an explicit product name previously bypassed `_scope`. Demo-only guests now receive 404 for names outside `_visible_products`; omitted names continue through `_scope`, including its no-demo guard. Product names are unique in the model.
- Manual GitHub issue creation now supplies the selected product to repository selection. Review found an additional reachable defect: a product without a GitHub binding inherited another product's sole connected repository. Fixed `_github_repo` so a scoped miss uses only the operator's explicit `GITHUB_DEFAULT_REPO`, or no repository (422). Unscoped inference remains compatible.
- Google ID token decoding now accepts both configured Google issuer forms while preserving RS256 signature and audience verification plus the explicit issuer allowlist. Local signed-token tests exercise actual decoding for both forms.
- Initial anonymous signup is blocked wherever authentication is required, including staging; bootstrap environment credentials remain the supported first-admin mechanism.
- Cost summary month-to-date now excludes previous months and future dates and normalizes timestamps to UTC.

## Validation

The new missing-binding GitHub regression failed before the fix in both cases: no fallback still posted to Alpha, and an explicit fallback was incorrectly overridden by Alpha. After the fix, `test_typesafe_api_followup.py`, `test_review.py`, and `test_auth.py` passed together: **16 passed** (rerun with Settings(_env_file=None, **defaults) before test imports; local/mocked integration boundaries). The broader v8 screen test run was interrupted after the seven follow-up tests passed because it stalled; no success claim is made for that run. Parent task owns full-suite validation.

## Remaining assessment

No additional concrete actionable defect was established in the reviewed files. Generic optional-value/type classifications are not sufficient evidence of runtime bugs: review challenge operates on persisted finding/investigation/anomaly relationships, and export/notification paths consume finding JSON produced by the investigation pipeline. Docker's trust of all forwarded proxy headers is explicitly deployment-dependent: its stated proxy-only ingress assumption must hold, but this review did not establish a direct public container port. Authentication's existing token-role lifetime and configured notification destinations are design choices rather than new regressions from these patches.

No production data, environment-file contents, or external service responses were inspected. No external mutation was performed; GitHub issue tests used a local stub.
