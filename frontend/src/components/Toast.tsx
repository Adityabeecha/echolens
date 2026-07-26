import { useEffect, useState } from "react";
import { C, mono, sans } from "../theme";

// Confirmation and failure, for every async action.
//
// Actions used to succeed in silence and fail in silence: "Scan now" reloaded a
// list that might legitimately be empty, so you could not tell a working scan
// from a broken one. Now every action says what happened, and a failure keeps a
// retry within reach instead of asking you to guess what to press again.

export interface ToastItem {
  id: number;
  text: string;
  kind: "ok" | "fail" | "info";
  retry?: () => void;
}

type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
let listeners: Listener[] = [];
let nextId = 1;

function emit() {
  listeners.forEach((l) => l(items));
}

/** Most toasts on screen at once. Failures never auto-dismiss, so without a
 *  cap a backend outage stacked them past the viewport in a fixed, unscrollable
 *  column that covered the app and pushed its own dismiss buttons off-screen. */
const MAX_TOASTS = 4;

function push(text: string, kind: ToastItem["kind"], retry?: () => void): number {
  const id = nextId++;
  // Drop the OLDEST once full: the newest failure is the one describing what
  // the user just tried to do.
  items = [...items, { id, text, kind, retry }].slice(-MAX_TOASTS);
  emit();
  // Failures stay until dismissed — an error you can miss is an error you will.
  if (kind !== "fail") setTimeout(() => dismiss(id), 4200);
  return id;
}

export function dismiss(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

/** Clear everything — called on sign-out so one user's failures never greet
 *  the next. `items` is module-global and survived the React tree unmounting. */
export function clearToasts() {
  items = [];
  emit();
}

export const toast = {
  ok: (text: string) => push(text, "ok"),
  info: (text: string) => push(text, "info"),
  fail: (text: string, retry?: () => void) =>
    push(text.replace(/^Error:\s*/, ""), "fail", retry),
};

/**
 * Run an async action with a confirmation on success and a retryable toast on
 * failure. The single wrapper every screen uses, so no action can be silent.
 */
export async function withToast<T>(
  action: () => Promise<T>,
  opts: { success: string | ((r: T) => string); failure: string },
): Promise<T | null> {
  try {
    const result = await action();
    const msg = typeof opts.success === "function" ? opts.success(result) : opts.success;
    if (msg) toast.ok(msg);
    return result;
  } catch (e) {
    const detail = String(e).replace(/^Error:\s*/, "");
    toast.fail(`${opts.failure} — ${detail}`, () => {
      void withToast(action, opts);
    });
    return null;
  }
}

const KIND: Record<ToastItem["kind"], { color: string; icon: string }> = {
  ok: { color: C.good, icon: "✓" },
  fail: { color: C.bad, icon: "✕" },
  info: { color: C.info, icon: "ⓘ" },
};

export function Toasts() {
  const [list, setList] = useState<ToastItem[]>(items);
  useEffect(() => {
    listeners.push(setList);
    return () => {
      listeners = listeners.filter((l) => l !== setList);
    };
  }, []);

  if (list.length === 0) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed", right: 20, bottom: 20, zIndex: 200,
        display: "flex", flexDirection: "column", gap: 9, maxWidth: 420,
      }}
    >
      {list.map((t) => {
        const k = KIND[t.kind];
        return (
          <div
            key={t.id}
            style={{
              display: "flex", alignItems: "flex-start", gap: 10,
              padding: "12px 14px", borderRadius: 10, background: C.card2,
              border: `1px solid ${k.color}66`, boxShadow: "0 16px 40px rgba(0,0,0,.5)",
              fontFamily: sans, fontSize: 13, color: C.text2, lineHeight: 1.5,
            }}
          >
            <span style={{ color: k.color, fontFamily: mono, fontSize: 12, marginTop: 1 }}>
              {k.icon}
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>{t.text}</span>
            {t.retry && (
              <button
                onClick={() => { dismiss(t.id); t.retry?.(); }}
                className="el-btn"
                style={{
                  background: "transparent", color: C.accent, border: `1px solid ${C.accent}66`,
                  borderRadius: 6, padding: "3px 10px", fontSize: 12, cursor: "pointer",
                  fontFamily: sans, flex: "none",
                }}
              >
                Retry
              </button>
            )}
            <span
              onClick={() => dismiss(t.id)}
              role="button"
              tabIndex={0}
              aria-label="Dismiss"
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") dismiss(t.id); }}
              className="el-btn"
              style={{ color: C.faint, cursor: "pointer", fontSize: 12, flex: "none" }}
            >
              ✕
            </span>
          </div>
        );
      })}
    </div>
  );
}
