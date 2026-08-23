import test from "node:test";
import assert from "node:assert/strict";

import {
  backfillProgressView,
  emptyBackfillMessage,
  progressActivityLabel,
  sourceProgressLabel,
  sourceRecoveryGuidance,
} from "../src/onboardingProgress.ts";

test("backfill progress reports checked sources, elapsed time, and expected window", () => {
  const view = backfillProgressView({
    checked_sources: 1,
    failed_sources: 0,
    total_sources: 3,
    expected_seconds: 120,
    timeout_seconds: 180,
    started_at: "2026-08-20T10:00:00+00:00",
  }, Date.parse("2026-08-20T10:01:05+00:00"));

  assert.equal(view.countLabel, "1 of 3 sources checked");
  assert.equal(view.elapsedLabel, "1:05 elapsed");
  assert.equal(view.expectedLabel, "Usually under 2 min");
  assert.equal(view.cutoffLabel, "Unresponsive sources stop after 3 min and unlock Retry.");
  assert.equal(view.percent, 33);
});

test("failed sources use actionable language instead of appearing to sync", () => {
  assert.equal(sourceProgressLabel({
    status: "error",
    items_last_run: 0,
    last_error: "GitHub returned 404",
    never_collected: false,
  }), "GitHub returned 404");
});

test("terminal failures replace the normal estimate with the timeout ceiling", () => {
  const view = backfillProgressView({
    checked_sources: 1,
    failed_sources: 1,
    timed_out_sources: 1,
    total_sources: 1,
    expected_seconds: 120,
    timeout_seconds: 180,
    started_at: "2026-08-20T10:00:00+00:00",
  }, Date.parse("2026-08-20T10:04:00+00:00"));

  assert.equal(view.expectedLabel, "Stopped after 3 min");
});

test("ordinary source errors are not mislabeled as timeouts", () => {
  const view = backfillProgressView({
    checked_sources: 1,
    failed_sources: 1,
    timed_out_sources: 0,
    total_sources: 1,
    expected_seconds: 120,
    timeout_seconds: 180,
    started_at: "2026-08-20T10:00:00+00:00",
  }, Date.parse("2026-08-20T10:00:05+00:00"));

  assert.equal(view.expectedLabel, "Finished with errors");
});

test("an empty failed run explains the failure instead of claiming collection finished", () => {
  assert.equal(emptyBackfillMessage({
    backfilling: false,
    failedSources: 1,
    githubItems: 0,
  }), "1 source couldn't finish. Retry it above; no public reviews have been collected yet.");
});

test("live activity says whether the first source or another source is pending", () => {
  assert.equal(progressActivityLabel({
    checked_sources: 0, failed_sources: 0, total_sources: 3,
    expected_seconds: 120, timeout_seconds: 180, started_at: null,
  }, 18), "Waiting for the first source response · updated 18s ago");
  assert.equal(progressActivityLabel({
    checked_sources: 2, failed_sources: 0, total_sources: 3,
    expected_seconds: 120, timeout_seconds: 180, started_at: null,
  }, 4), "2 sources finished · updated just now");
});

test("every source error gives recovery guidance", () => {
  assert.equal(sourceRecoveryGuidance("request timed out"),
    "The source did not respond. Retry it now; the other sources are unaffected.");
  assert.equal(sourceRecoveryGuidance("GitHub returned 401 Unauthorized"),
    "Check this source's access credentials, then retry it.");
  assert.equal(sourceRecoveryGuidance("repository returned 404"),
    "Check the source identifier and visibility, then retry it.");
  assert.equal(sourceRecoveryGuidance("rate limit exceeded"),
    "Wait a few minutes for the limit to reset, then retry it.");
  assert.equal(sourceRecoveryGuidance("unexpected parser failure"),
    "Retry this source. If it fails again, review its connection details.");
});
