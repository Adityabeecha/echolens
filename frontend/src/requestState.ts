// Request bookkeeping shared by api.ts, hooks.ts and ui.tsx.
//
// One global slot rather than module state: api.ts deliberately has no imports
// (test harnesses load it on its own), so both sides reach the same object
// through `globalThis.__echolensRequests` instead of importing each other.

/** Why the last failed read failed: shapes the wording of ErrorState. */
export type FailureKind = "timeout" | "network" | "http";

interface RequestState {
  /** The signal of whoever is asking right now (see withSignal). */
  ambient: AbortSignal | null;
  last: FailureKind | null;
}

export function requestState(): RequestState {
  const g = globalThis as unknown as { __echolensRequests?: RequestState };
  return (g.__echolensRequests ??= { ambient: null, last: null });
}

export function lastFailure(): FailureKind | null {
  return requestState().last;
}

/** True for a fetch cancelled on purpose (screen or product changed). */
export function isAbortError(e: unknown): boolean {
  return !!e && typeof e === "object" && (e as { name?: string }).name === "AbortError";
}

/**
 * Run `fn` with `signal` as the ambient signal. Every read the api layer starts
 * while `fn` runs is cancelled with it — the api methods keep their plain
 * signatures. Reads pick it up synchronously at call time.
 */
export function withSignal<T>(signal: AbortSignal, fn: () => T): T {
  const st = requestState();
  const prev = st.ambient;
  st.ambient = signal;
  try {
    return fn();
  } finally {
    st.ambient = prev;
  }
}
