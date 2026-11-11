// Error tracking for the browser. Off unless VITE_SENTRY_DSN is set at build.
//
// Several background refreshes swallow their errors on purpose (a failed
// product-list refresh must not break the screen), which is exactly how the
// "Choose product" bug stayed invisible. They now report here instead of
// vanishing. The Sentry SDK is its own chunk, fetched only when a DSN exists,
// so a deployment without one ships nothing extra.

type Sentry = typeof import("./sentry");

const DSN = import.meta.env.VITE_SENTRY_DSN;
const MAX_PENDING = 20;

let sentry: Sentry | null = null;
const pending: { error: unknown; context?: Record<string, unknown> }[] = [];

export function initMonitoring(): void {
  if (!DSN) return;
  import("./sentry")
    .then((S) => {
      S.init({
        dsn: DSN,
        environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
        tracesSampleRate: 0,
        // SDK 11 collects all of these by default. Request bodies carry review
        // text and cookies carry the session, so none of it leaves the browser.
        dataCollection: {
          userInfo: false,
          cookies: false,
          httpHeaders: false,
          httpBodies: [],
          urlQueryParams: false,
        },
      });
      sentry = S;
      for (const { error, context } of pending.splice(0)) send(error, context);
    })
    .catch(() => { /* monitoring must never break the app */ });
}

function send(error: unknown, context?: Record<string, unknown>) {
  sentry?.captureException(error, context ? { extra: context } : undefined);
}

function isCancellation(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Record an error that the UI deliberately carries on past. */
export function reportError(error: unknown, context?: Record<string, unknown>): void {
  if (isCancellation(error)) return;  // a deliberate cancel, not a failure
  if (import.meta.env.DEV) console.warn("[reported]", context?.where ?? "", error);
  if (!DSN) return;
  if (sentry) send(error, context);
  else if (pending.length < MAX_PENDING) pending.push({ error, context });
}

/** A `.catch` handler for fire-and-forget calls: report, then carry on. */
export const reportAs = (where: string) => (error: unknown) => reportError(error, { where });
