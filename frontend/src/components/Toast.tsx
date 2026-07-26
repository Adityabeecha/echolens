import { useEffect, useState } from "react";
import { C, R, S, T } from "../theme";
import { Button } from "../ui";
import { Icon } from "./Icon";

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
    push(text.replace(/^Error:\s*/, ""), "fail", retry)
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
  ok: { color: C.good, icon: "check" },
  fail: { color: C.bad, icon: "warning" },
  info: { color: C.info, icon: "info" }
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
        position: "fixed", right: S[5], bottom: S[5], zIndex: 200,
        display: "flex", flexDirection: "column", gap: S[2],
        maxWidth: "min(420px, calc(100vw - 2 * var(--el-s5)))"
      }}
    >
      {list.map((t) => {
        const k = KIND[t.kind];
        return (
          <div
            key={t.id}
            style={{
              display: "flex", alignItems: "flex-start", gap: S[3],
              padding: `${S[3]} ${S[3]}`, borderRadius: R.card, background: C.card,
              border: `1px solid ${k.color}66`, boxShadow: "var(--el-e3)",
              fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-normal)",
              animation: "elFadeUp var(--el-dur-slow) var(--el-ease)"
            }}
          >
            <span style={{ color: k.color, marginTop: 2, flex: "none" }}>
              <Icon name={k.icon} size={15} />
            </span>
            <span style={{ flex: 1, minWidth: 0 }}>{t.text}</span>
            {t.retry && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { dismiss(t.id); t.retry?.(); }}
                style={{ flex: "none" }}
              >
                Retry
              </Button>
            )}
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss"
              className="el-btn el-btn--sm"
              style={{ color: C.dim, flex: "none", padding: 2 }}
            >
              <Icon name="close" size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
