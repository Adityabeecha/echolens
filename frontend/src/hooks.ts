import { useEffect, useRef, useState } from "react";
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

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

// Tail an investigation's trace over SSE; falls back to polling if EventSource fails.
export function useTrace(investigationId: number | null): {
  steps: TraceStep[];
  status: string;
} {
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [status, setStatus] = useState("running");
  const seen = useRef(0);

  useEffect(() => {
    if (investigationId == null) return;
    setSteps([]);
    setStatus("running");
    seen.current = 0;

    let es: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;

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
      if (poll) return;
      const step = async () => {
        try {
          const r = await api.trace(investigationId!, seen.current);
          r.steps.forEach(push);
          setStatus(r.status);
          if (r.status !== "running" && poll) clearInterval(poll);
        } catch {
          /* keep trying */
        }
      };
      step();
      poll = setInterval(step, 1200);
    }

    return () => {
      es?.close();
      if (poll) clearInterval(poll);
    };
  }, [investigationId]);

  return { steps, status };
}
