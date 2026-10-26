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

  const finished = progress.total_sources > 0 && progress.checked_sources >= progress.total_sources;
  // "Stopped after 3 min" only when the run really hit the cutoff. A source
  // that timed out on its own in seconds is an error, not the batch stopping —
  // showing both "0:06 elapsed" and "Stopped after 3 min" contradicted itself.
  const hitCutoff = timedOut && elapsedSeconds >= progress.timeout_seconds;

  return {
    countLabel: `${progress.checked_sources} of ${progress.total_sources} sources checked`,
    // Elapsed keeps counting from the start, so it is only shown while running.
    elapsedLabel: finished ? "" : `${compactDuration(elapsedSeconds)} elapsed`,
    expectedLabel: hitCutoff
      ? `Stopped after ${timeoutMinutes} min`
      : terminalFailure
        ? "Finished with errors"
        : finished
          ? "Finished"
          : `Usually under ${expectedMinutes} min`,
    cutoffLabel: `Unresponsive sources stop after ${timeoutMinutes} min and unlock Retry.`,
    percent,
  };
}

export interface SourceErrorView {
  /** What went wrong, in plain words. */
  message: string;
  /** What to do about it. */
  guidance: string;
  /** False when retrying cannot help (a missing or rejected token). */
  canRetry: boolean;
}

/** A collector's raw error ("RuntimeError: …", "ReadTimeout: …") as words a
 *  person can act on. The raw text stays available as technical detail. */
export function sourceErrorView(error: string | null): SourceErrorView {
  const message = (error || "").toLowerCase();
  if (/needs github_token|no anonymous access|token (is )?(missing|required)/.test(message)) {
    return {
      message: "Needs a GitHub access token",
      guidance: "GitHub only shares this with a token. An admin adds GITHUB_TOKEN to the server settings; everything else keeps working without it.",
      canRetry: false,
    };
  }
  if (/\b401\b|bad credentials|unauthori[sz]ed/.test(message)) {
    return {
      message: "The access token was rejected",
      guidance: "It has probably expired. An admin replaces the token in the server settings, then retries.",
      canRetry: false,
    };
  }
  if (/\b403\b|forbidden|permission/.test(message)) {
    return {
      message: "This source refused access",
      guidance: "It may be private, or the token lacks permission. Check it is public, then retry.",
      canRetry: true,
    };
  }
  if (/\b404\b|not found|does not exist|invalid (id|identifier|package|repo)/.test(message)) {
    return {
      message: "We couldn't find it",
      guidance: "Check the name or ID is right and the page is public, then retry.",
      canRetry: true,
    };
  }
  if (/rate.?limit|too many requests|\b429\b/.test(message)) {
    return {
      message: "Asked to slow down",
      guidance: "The source limits how often it can be read. Wait a few minutes, then retry.",
      canRetry: true,
    };
  }
  if (/timeout|timed out|stopped responding|network|connection/.test(message)) {
    return {
      message: "The source took too long to answer",
      guidance: "It's usually temporary. Retry now; the other sources are unaffected.",
      canRetry: true,
    };
  }
  return {
    message: "This source couldn't be read",
    guidance: "Retry it. If it fails again, check its connection details.",
    canRetry: true,
  };
}

export function sourceProgressLabel(source: SourceProgress): string {
  if (source.status === "error") return sourceErrorView(source.last_error).message;
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
  return sourceErrorView(error).guidance;
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
