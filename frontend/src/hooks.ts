import { useCallback, useEffect, useRef, useState } from "react";
import { api, TraceStep } from "./api";

// Simple async loader with loading/error/reload.
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  // Monotonic request id. `alive` alone only cancels on dep change; two reloads
  // fired close together could still resolve out of order and let the SLOWER,
  // older response overwrite the newer one.
  const seq = useRef(0);

  useEffect(() => {
    let alive = true;
    const mine = ++seq.current;
    const current = () => alive && seq.current === mine;
    setLoading(true);
    fn()
      .then((d) => current() && (setData(d), setError(null)))
      .catch((e) => current() && setError(String(e)))
      .finally(() => current() && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  // Stable identity so passing it as a prop does not defeat memoisation.
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/**
 * Dialog behaviour, in one place: Escape closes, focus moves in on open and
 * returns on close, and Tab cycles inside rather than escaping behind.
 *
 * Every modal previously implemented some subset of this. `NewCaseModal` had
 * none of it, and none of the three moved focus at all — so opening a dialog
 * with the keyboard left you tabbing through the page underneath it, with no
 * visible indication of where you were.
 *
 * Returns a ref to put on the dialog element.
 */
export function useDialog(onClose: () => void, enabled = true) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const root = ref.current;
    const previous = document.activeElement as HTMLElement | null;

    // No `offsetParent` check: it is null for any `position: fixed` element,
    // which is exactly what these dialogs are, so filtering on it discarded
    // every candidate. Hidden controls are excluded explicitly instead.
    const focusable = () =>
      Array.from(
        root?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((el) => !el.hasAttribute("hidden") && el.getAttribute("aria-hidden") !== "true");

    // Focus the first real control, not the dialog itself, so a screen reader
    // lands on something actionable.
    //
    // Deferred a frame: on the effect's first run the dialog's children have
    // been committed but the browser has not laid them out, so `offsetParent`
    // is still null for all of them and the focusable filter returns nothing.
    // Focus then stayed on the button that opened the dialog.
    const raf = requestAnimationFrame(() => {
      const first = focusable()[0];
      (first ?? root)?.focus();
    });

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      // Wrap at both ends so Tab never reaches the page behind the dialog.
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    document.addEventListener("keydown", onKey, true);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKey, true);
      // Send focus back where it came from, so closing a dialog does not dump
      // the caret at the top of the document.
      previous?.focus?.();
    };
  }, [onClose, enabled]);

  return ref;
}

/** Consecutive polling failures before we stop and say so. */
const MAX_POLL_FAILURES = 5;

// Tail an investigation's trace over SSE; falls back to polling if EventSource fails.
export function useTrace(investigationId: number | null): {
  steps: TraceStep[];
  status: string;
  error: string | null;
} {
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [status, setStatus] = useState("running");
  const [error, setError] = useState<string | null>(null);
  const seen = useRef(0);

  useEffect(() => {
    if (investigationId == null) return;
    setSteps([]);
    setStatus("running");
    setError(null);
    seen.current = 0;

    let es: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let failures = 0;
    let stopped = false;

    const stopPolling = () => {
      if (poll) { clearInterval(poll); poll = null; }
    };

    const push = (s: TraceStep) => {
      if (s.seq <= seen.current) return;
      seen.current = s.seq;
      setSteps((prev) => [...prev, s]);
    };

    try {
      es = new EventSource(api.traceStreamUrl(investigationId));
      es.addEventListener("step", (e) => push(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("done", (e) => {
        setStatus(JSON.parse((e as MessageEvent).data).status);
        es?.close();
      });
      es.onerror = () => {
        es?.close();
        startPolling();
      };
    } catch {
      startPolling();
    }

    function startPolling() {
      if (poll || stopped) return;
      const step = async () => {
        try {
          const r = await api.trace(investigationId!, seen.current);
          failures = 0;
          setError(null);
          r.steps.forEach(push);
          setStatus(r.status);
          // Terminate on ANY settled status. This check used to sit inside the
          // try below a bare catch, so when api.trace kept rejecting (backend
          // down, case deleted) the catch swallowed it, the check never ran, and
          // the interval hammered the API forever with the UI stuck on
          // "Waiting for the first reasoning step…" and no error shown.
          if (r.status !== "running") stopPolling();
        } catch (err) {
          failures += 1;
          if (failures >= MAX_POLL_FAILURES) {
            stopped = true;
            stopPolling();
            setError(
              String(err).replace(/^Error:\s*/, "") ||
              "Lost contact with the investigation stream.",
            );
          }
        }
      };
      void step();
      poll = setInterval(step, 1200);
    }

    return () => {
      stopped = true;
      es?.close();
      stopPolling();
    };
  }, [investigationId]);

  return { steps, status, error };
}
