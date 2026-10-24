import { useEffect, useRef, useState } from "react";
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
  /** Label for the action button. Defaults to "Retry" (the original use). */
  actionLabel?: string;
  /** Dismissed and playing its exit; removed once that finishes. */
  leaving?: boolean;
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

function push(text: string, kind: ToastItem["kind"], retry?: () => void,
              actionLabel?: string): number {
  const id = nextId++;
  // Drop the OLDEST once full: the newest failure is the one describing what
  // the user just tried to do.
  items = [...items, { id, text, kind, retry, actionLabel }].slice(-MAX_TOASTS);
  emit();
  // Failures stay until dismissed — an error you can miss is an error you will.
  if (kind !== "fail") setTimeout(() => dismiss(id), 4200);
  return id;
}

/** Matches --el-dur in tokens.css, the length of the exit transition. */
const EXIT_MS = 180;

function reducedMotion(): boolean {
  return typeof window !== "undefined" &&
    !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export function dismiss(id: number) {
  const t = items.find((x) => x.id === id);
  if (!t || t.leaving) return;
  if (reducedMotion()) {
    items = items.filter((x) => x.id !== id);
    emit();
    return;
  }
  // Fade out first, then leave the DOM: a toast that vanished mid-sentence
  // read as a glitch, not as "done".
  items = items.map((x) => (x.id === id ? { ...x, leaving: true } : x));
  emit();
  setTimeout(() => {
    items = items.filter((x) => x.id !== id);
    emit();
  }, EXIT_MS);
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
  /** An informational toast that offers one action, e.g. "Watch live". */
  action: (text: string, label: string, onAction: () => void) =>
    push(text, "info", onAction, label)
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

/**
 * The stack sits bottom-right (above the bottom bar on a phone) and publishes
 * its height as --el-toast-reserve, which the screen body adds to its bottom
 * padding. "Case #N is running — Watch live" used to float over whatever was
 * last on the page — often the very Approve button you were reaching for —
 * with no way to scroll it out from under the toast.
 */
export function Toasts() {
  const [list, setList] = useState<ToastItem[]>(items);
  const stackRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    listeners.push(setList);
    return () => {
      listeners = listeners.filter((l) => l !== setList);
    };
  }, []);

  const shown = list.length > 0;
  useEffect(() => {
    const root = document.documentElement.style;
    const node = stackRef.current;
    if (!shown || !node) { root.removeProperty("--el-toast-reserve"); return; }
    const publish = () => root.setProperty("--el-toast-reserve", `${node.offsetHeight + 16}px`);
    publish();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(publish) : null;
    ro?.observe(node);
    return () => { ro?.disconnect(); root.removeProperty("--el-toast-reserve"); };
  }, [shown]);

  if (!shown) return null;
  return (
    <div ref={stackRef} className="el-toasts" role="status" aria-live="polite">
      {list.map((t) => {
        const k = KIND[t.kind];
        return (
          <div
            key={t.id}
            className={`el-toast${t.leaving ? " is-leaving" : ""}`}
            style={{
              display: "flex", alignItems: "flex-start", gap: S[3],
              padding: `${S[3]} ${S[3]}`, borderRadius: R.card, background: C.card,
              border: `1px solid ${k.color}66`, boxShadow: "var(--el-e3)",
              fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-normal)"
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
                {t.actionLabel ?? "Retry"}
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
