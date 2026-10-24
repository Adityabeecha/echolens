import { useEffect } from "react";
import { useDialog } from "../hooks";
import { formatRoute } from "../nav";
import { AskConversation } from "../screens/Chat";
import { C, S, T } from "../theme";
import { Icon } from "./Icon";

export function isAskShortcut(event: KeyboardEvent, mac = /Mac|iPhone|iPad|iPod/.test(navigator.platform)): boolean {
  const target = event.target as HTMLElement | null;
  const editable = target?.isContentEditable || target?.closest?.('input, textarea, select, [role="textbox"], [contenteditable]:not([contenteditable="false"])');
  return !event.defaultPrevented && !event.repeat && !event.altKey && !event.shiftKey &&
    event.key.toLowerCase() === "k" && (mac ? event.metaKey : event.ctrlKey) && !editable;
}

export function AskDrawer({ productId, productName, onClose, onOpenInvestigation, returnFocus }: {
  returnFocus?: HTMLElement | null;
  productId: number | null;
  productName: string | null;
  onClose: () => void;
  onOpenInvestigation: (id: number) => void;
}) {
  const ref = useDialog(onClose);
  useEffect(() => {
    const bodyOverflow = document.body.style.overflow;
    const rootOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";
    // Consume Escape before document-level dialogs beneath this one see it.
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault(); event.stopPropagation(); onClose();
    };
    window.addEventListener("keydown", onEscape, true);
    // Cmd/Ctrl K should put the caret where the next question will be typed.
    const frame = requestAnimationFrame(() => ref.current?.querySelector<HTMLInputElement>('input[aria-label="Ask a question about your feedback"]')?.focus());
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onEscape, true);
      document.body.style.overflow = bodyOverflow;
      document.documentElement.style.overflow = rootOverflow;
      if (returnFocus?.isConnected) returnFocus.focus();
    };
  }, [ref, onClose, returnFocus]);

  return (
    <>
      <div aria-hidden="true" onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 60 }} />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby="global-ask-title" tabIndex={-1}
        style={{ position: "fixed", inset: "0 0 0 auto", width: "min(580px, 100vw)", height: "100dvh",
                 zIndex: 61, background: C.bg, borderLeft: `1px solid ${C.border3}`,
                 boxShadow: "var(--el-e4)", display: "flex", flexDirection: "column",
                 overscrollBehavior: "contain", overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[3], padding: `${S[3]} ${S[5]}`,
                      borderBottom: `1px solid ${C.border}` }}>
          <h2 id="global-ask-title" style={{ margin: 0, fontSize: T.md, color: C.text }}>Ask</h2>
          <span style={{ color: C.dim, fontSize: T.sm, flex: 1 }}>{productName ?? "Workspace"}</span>
          {/* The sidebar's Ask opens this drawer; the full page is still a real
              route, reachable from here and by its URL. A plain link, so the
              router handles it like any other navigation. */}
          <a href={formatRoute({ screen: "ask", productId })} onClick={onClose}
            className="el-btn el-btn--quiet el-btn--sm">
            Open full page
          </a>
          <button className="el-btn el-btn--ghost" onClick={onClose} aria-label="Close Ask" title="Close Ask (Esc)">
            <Icon name="close" size={16} />
          </button>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          <AskConversation key={productId ?? "none"} productId={productId} productName={productName}
                           onOpenInvestigation={onOpenInvestigation} />
        </div>
      </div>
    </>
  );
}
