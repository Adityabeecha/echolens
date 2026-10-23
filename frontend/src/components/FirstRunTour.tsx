import { CSSProperties, useEffect, useLayoutEffect, useState } from "react";
import { C, R, S, T, mono } from "../theme";
import { Button } from "../ui";
import { Icon } from "./Icon";

interface Step {
  /** `data-tour` value of the element this step points at; none = free-floating. */
  target?: string;
  title: string;
  body: string;
}

const STEPS: Step[] = [
  { target: "today", title: "Today is home",
    body: "What needs your call lands here first: findings to review, problems getting worse, fixes to check." },
  { target: "cases", title: "Cases and signals",
    body: "Every investigation lives in Cases. Its Signals view lists what EchoLens noticed but hasn't investigated yet, so you can pick what's worth a case." },
  { title: "A case's finding",
    body: "Open any finished case to see its finding: what's broken, how sure EchoLens is, and the reviews and issues behind it. You approve or challenge it there." },
  { target: "ask", title: "Ask anything",
    body: "Ask a question in plain words, like \"why are 1-star reviews up this week?\", and get an answer drawn from your own feedback." },
];

const CARD_W = 300;

/**
 * Four coach marks after the first product is added.
 *
 * Deliberately not a modal: no scrim, no focus trap, nothing it waits on. The
 * app behind it stays fully usable, Esc or "Skip" ends it, and it never comes
 * back (see tourState.ts). Each mark sits beside the nav item it describes when
 * that item is on screen, and in the corner when it isn't.
 */
export function FirstRunTour({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0);
  const [pos, setPos] = useState<CSSProperties>({ right: 20, bottom: 20 });
  const step = STEPS[i];
  const last = i === STEPS.length - 1;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useLayoutEffect(() => {
    const place = () => setPos(positionFor(step.target));
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [step.target]);

  // Mark the target so it reads as "this one" — an outline, not a spotlight.
  useEffect(() => {
    const el = visibleTarget(step.target);
    el?.classList.add("el-tour-target");
    return () => el?.classList.remove("el-tour-target");
  }, [step.target]);

  return (
    <div role="dialog" aria-modal="false" aria-labelledby="el-tour-title"
      style={{ position: "fixed", zIndex: 150, width: CARD_W, maxWidth: "calc(100vw - 32px)",
               padding: `${S[4]} ${S[4]} ${S[3]}`, background: C.card,
               border: `1px solid ${C.border3}`, borderRadius: R.card,
               boxShadow: "var(--el-e3)", animation: "elFadeUp .18s ease-out",
               ...pos }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[2] }}>
        <span style={{ fontFamily: mono, fontSize: T.micro, color: C.accent,
                       letterSpacing: "var(--el-ls-wide)" }}>
          {i + 1} OF {STEPS.length}
        </span>
        <span style={{ flex: 1 }} />
        <button onClick={onClose} className="el-btn" aria-label="Skip the tour"
          style={{ color: C.dim, padding: 2 }}>
          <Icon name="close" size={13} />
        </button>
      </div>
      <div id="el-tour-title" style={{ fontSize: T.md, fontWeight: 600, color: C.text,
                                        marginBottom: S[1] }}>{step.title}</div>
      <p style={{ margin: 0, fontSize: T.sm, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
        {step.body}
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[3] }}>
        <Button variant="quiet" size="sm" onClick={onClose}>Skip tour</Button>
        <span style={{ flex: 1 }} />
        {i > 0 && <Button variant="ghost" size="sm" onClick={() => setI(i - 1)}>Back</Button>}
        <Button variant="primary" size="sm" onClick={() => (last ? onClose() : setI(i + 1))}>
          {last ? "Done" : "Next"}
        </Button>
      </div>
    </div>
  );
}

/** The marked element that is actually rendered — the sidebar and the mobile
 *  bottom bar both carry the same data-tour value, and one is display:none. */
function visibleTarget(target?: string): HTMLElement | null {
  if (!target) return null;
  const all = Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${target}"]`));
  return all.find((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }) ?? null;
}

function positionFor(target?: string): CSSProperties {
  const el = visibleTarget(target);
  const corner: CSSProperties = { right: 20, bottom: 20 };
  if (!el) return corner;
  const r = el.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  // Room to the right (desktop sidebar): sit beside it, vertically aligned.
  if (r.right + 12 + CARD_W <= vw - 8) {
    return { left: r.right + 12, top: Math.max(8, Math.min(r.top - 8, vh - 260)) };
  }
  // Otherwise (mobile bottom bar): sit above it, kept inside the viewport.
  return { left: Math.max(16, Math.min(r.left, vw - CARD_W - 16)), bottom: vh - r.top + 12 };
}
