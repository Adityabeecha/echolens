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
