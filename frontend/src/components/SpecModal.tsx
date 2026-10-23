import { useState } from "react";
import { TrackerId, api, canReview } from "../api";
import { useAsync, useDialog } from "../hooks";
import { plural } from "../format";
import { C, R, S, T, mono } from "../theme";
import { Button, ErrorState } from "../ui";
import { Icon } from "./Icon";
import { withToast } from "./Toast";

/**
 * The spec (PRD) EchoLens writes from a feature request: Markdown a PM can
 * copy into a doc or file straight into a tracker. What is filed is exactly
 * what is shown — the server reuses the spec it just built for this view.
 */
export function SpecModal({ slug, title, onClose }: { slug: string; title: string; onClose: () => void }) {
  const spec = useAsync(() => api.requestSpec(slug), [slug]);
  const trackers = useAsync(() => api.trackers(), []);
  const [busy, setBusy] = useState<TrackerId | null>(null);
  const ref = useDialog(onClose, true, busy == null);
  const reviewer = canReview();
  const ready = (trackers.data?.trackers ?? []).filter((t) => t.configured);

  const copy = () => spec.data && withToast(() => navigator.clipboard.writeText(spec.data!.markdown), {
    success: "Spec copied to your clipboard.",
    failure: "Your browser blocked the clipboard",
  });
  const file = async (tracker: TrackerId, label: string) => {
    setBusy(tracker);
    await withToast(() => api.createRequestTicket(slug, tracker), {
      success: (res) => `Filed in ${label}${res.number != null ? ` as ${tracker === "github" ? "#" : ""}${res.number}` : ""}.`,
      failure: `Couldn't file the ${label} issue`,
    });
    setBusy(null);
  };

  return (
    <>
      <div className="el-overlay-scrim" onClick={() => busy == null && onClose()} aria-hidden="true"
           style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 30 }} />
      <div
        className="el-overlay-panel"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={`Spec: ${title}`}
        style={{
          position: "fixed", top: "50%", left: "50%", transform: "translate(-50%,-50%)",
          width: 720, maxWidth: "min(720px, calc(100vw - 32px))", maxHeight: "86vh",
          display: "flex", flexDirection: "column",
          background: C.card, border: `1px solid ${C.border3}`, borderRadius: R.overlay,
          zIndex: 31, padding: S[5], boxShadow: "var(--el-e4)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[3] }}>
          <div style={{ fontSize: T.lg, fontWeight: 600, minWidth: 0, overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>Spec · {title}</div>
          <button onClick={onClose} aria-label="Close" disabled={busy != null}
                  className="el-btn el-btn--sm" style={{ marginLeft: "auto", color: C.muted }}>
            <Icon name="close" size={15} />
          </button>
        </div>

        {spec.error ? (
          <ErrorState title="Couldn't write the spec" detail={spec.error} onRetry={spec.reload} />
        ) : !spec.data ? (
          <div style={{ fontSize: T.sm, color: C.muted, padding: `${S[5]} 0` }}>Writing the spec…</div>
        ) : (
          <>
            <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginBottom: S[2] }}>
              {spec.data.engine === "model"
                ? "STORIES + CRITERIA REWRITTEN BY THE MODEL, CHECKED AGAINST THE EVIDENCE"
                : spec.data.rejected
                  ? `TEMPLATE · MODEL REWRITE REFUSED (${spec.data.rejected.toUpperCase()})`
                  : "TEMPLATE"}
              {" · "}{spec.data.evidence_count} {plural(spec.data.evidence_count, "quoted review")}
            </div>
            <pre style={{ flex: 1, minHeight: 0, overflow: "auto", margin: 0, padding: S[4],
                          background: C.bgRaised, border: `1px solid ${C.border2}`,
                          borderRadius: R.control, fontFamily: mono, fontSize: T.sm,
                          color: C.text2, whiteSpace: "pre-wrap", wordBreak: "break-word",
                          lineHeight: "var(--el-lh-normal)" }}>
              {spec.data.markdown}
            </pre>
            <div style={{ display: "flex", gap: S[2], flexWrap: "wrap", alignItems: "center", marginTop: S[3] }}>
              <Button variant="ghost" size="sm" icon="check" onClick={copy}>Copy Markdown</Button>
              {reviewer && ready.map((t) => (
                <Button key={t.id} variant="ghost" size="sm" icon="external"
                  loading={busy === t.id} disabled={busy != null && busy !== t.id}
                  onClick={() => file(t.id, t.label)}>
                  {busy === t.id ? "Filing…" : `File as ticket in ${t.label}`}
                </Button>
              ))}
              {reviewer && trackers.data && ready.length === 0 && (
                <span style={{ fontSize: T.sm, color: C.dim }}>
                  No issue tracker is set up. Settings lists what to configure.
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}
