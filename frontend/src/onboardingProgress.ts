export interface BackfillProgress {
  checked_sources: number;
  failed_sources: number;
  timed_out_sources?: number;
  total_sources: number;
  expected_seconds: number;
  timeout_seconds: number;
  started_at: string | null;
}

export interface SourceProgress {
  status: string;
  items_last_run: number;
  last_error: string | null;
  never_collected: boolean;
}

function compactDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function backfillProgressView(progress: BackfillProgress, now = Date.now()) {
  const started = progress.started_at ? Date.parse(progress.started_at) : now;
  const elapsedSeconds = Math.max(0, Math.floor((now - started) / 1000));
  const expectedMinutes = Math.max(1, Math.ceil(progress.expected_seconds / 60));
  const timeoutMinutes = Math.max(1, Math.ceil(progress.timeout_seconds / 60));
  const terminalFailure = progress.failed_sources > 0
    && progress.checked_sources === progress.total_sources;
  const timedOut = (progress.timed_out_sources ?? 0) > 0;
  const percent = progress.total_sources > 0
    ? Math.round((progress.checked_sources / progress.total_sources) * 100)
    : 0;

  return {
    countLabel: `${progress.checked_sources} of ${progress.total_sources} sources checked`,
    elapsedLabel: `${compactDuration(elapsedSeconds)} elapsed`,
    expectedLabel: timedOut
      ? `Stopped after ${timeoutMinutes} min`
      : terminalFailure
        ? "Finished with errors"
        : `Usually under ${expectedMinutes} min`,
    cutoffLabel: `Unresponsive sources stop after ${timeoutMinutes} min and unlock Retry.`,
    percent,
  };
}

export function sourceProgressLabel(source: SourceProgress): string {
  if (source.status === "error") return source.last_error || "Source check failed";
  if (source.status === "healthy") {
    return `${source.items_last_run.toLocaleString()} items pulled`;
  }
  return source.never_collected ? "Waiting to start" : "Checking now";
}

export function progressActivityLabel(
  progress: BackfillProgress,
  secondsSinceUpdate: number,
): string {
  if (progress.checked_sources >= progress.total_sources) return "All sources responded";
  const freshness = secondsSinceUpdate <= 5
    ? "updated just now"
    : `updated ${compactDuration(secondsSinceUpdate).replace(/^0:/, "")}s ago`;
  if (progress.checked_sources === 0) {
    return `Waiting for the first source response · ${freshness}`;
  }
  const noun = progress.checked_sources === 1 ? "source" : "sources";
  return `${progress.checked_sources} ${noun} finished · ${freshness}`;
}

export function sourceRecoveryGuidance(error: string | null): string {
  const message = (error || "").toLowerCase();
  if (/401|403|unauthori[sz]ed|forbidden|credential|token|permission/.test(message)) {
    return "Check this source's access credentials, then retry it.";
  }
  if (/404|not found|does not exist|invalid (id|identifier|package|repo)/.test(message)) {
    return "Check the source identifier and visibility, then retry it.";
  }
  if (/rate.?limit|too many requests|\b429\b/.test(message)) {
    return "Wait a few minutes for the limit to reset, then retry it.";
  }
  if (/timeout|timed out|stopped responding|network|connection/.test(message)) {
    return "The source did not respond. Retry it now; the other sources are unaffected.";
  }
  return "Retry this source. If it fails again, review its connection details.";
}

export function emptyBackfillMessage({
  backfilling,
  failedSources,
  githubItems,
}: {
  backfilling: boolean;
  failedSources: number;
  githubItems: number;
}): string {
  if (backfilling) return "Pulling your first reviews…";
  if (failedSources > 0) {
    const noun = failedSources === 1 ? "source" : "sources";
    const pronoun = failedSources === 1 ? "it" : "them";
    return `${failedSources} ${noun} couldn't finish. Retry ${pronoun} above; no public reviews have been collected yet.`;
  }
  if (githubItems > 0) {
    return `No public Play Store reviews were available. GitHub collection finished with ${githubItems.toLocaleString()} items.`;
  }
  return "Collection finished, but no public reviews were available for this app.";
}
