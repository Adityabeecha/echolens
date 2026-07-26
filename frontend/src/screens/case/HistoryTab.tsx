import { Investigation } from "../../api";
import { when } from "../../format";
import { C, MEASURE, R, S, T, mono } from "../../theme";
import { EmptyState } from "../../ui";

const KIND: Record<string, { color: string; icon: string }> = {
  opened: { color: C.muted, icon: "●" },
  finding: { color: C.accent, icon: "◆" },
  approved: { color: C.good, icon: "✓" },
  challenged: { color: C.bad, icon: "✕" },
  reopen: { color: C.info, icon: "↻" },
  issue: { color: C.info, icon: "⌥" },
  fix_shipped: { color: C.accent, icon: "▲" },
  verified: { color: C.good, icon: "✓" },
  regressed: { color: C.bad, icon: "⚠" },
};

/**
 * What happened to this case, and who decided it.
 *
 * Human decisions were previously invisible after the fact: challenging a
 * finding silently spawned a new case and left the old one looking as though
 * nothing had happened to it.
 */
export function HistoryTab({ inv, onOpenCase }: {
  inv: Investigation; onOpenCase: (id: number, status?: string) => void;
}) {
  const events = inv.history ?? [];
  if (events.length === 0) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: `${S[6]} ${S[6]}` }}>
        <EmptyState
          title="Nothing has happened to this case yet"
          body="Reviews, challenges, re-opens, filed issues and verified fixes all appear here as they happen."
        />
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: MEASURE, padding: `${S[6]} ${S[6]} ${S[12]}` }}>
        {events.map((e, i) => {
          const k = KIND[e.kind] ?? { color: C.muted, icon: "●" };
          const last = i === events.length - 1;
          return (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "26px 1fr",
                                  columnGap: S[3] }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                <div style={{ width: 22, height: 22, borderRadius: "50%", flex: "none",
                              border: `1px solid ${k.color}66`, background: C.card,
                              color: k.color, fontSize: T.micro, display: "flex",
                              alignItems: "center", justifyContent: "center" }}>
                  {k.icon}
                </div>
                <div style={{ width: 1, flex: 1, minHeight: 12,
                              background: last ? "transparent" : C.border2 }} />
              </div>
              <div style={{ paddingBottom: 18, minWidth: 0 }}>
                <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint,
                              letterSpacing: ".06em" }}>
                  {when(e.at)}
                </div>
                <div style={{ fontSize: T.base, color: C.text2, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
                  {e.text}
                  {e.case_id != null && (
                    <span onClick={() => onOpenCase(e.case_id!)} className="el-btn" role="button"
                      tabIndex={0}
                      onKeyDown={(ev) => { if (ev.key === "Enter") onOpenCase(e.case_id!); }}
                      style={{ color: C.accent, cursor: "pointer", marginLeft: 8,
                               fontFamily: mono, fontSize: T.sm }}>
                      open case #{e.case_id} →
                    </span>
                  )}
                </div>
                {e.note && (
                  <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[1], padding: `${S[2]} ${S[3]}`,
                                background: C.card, border: `1px solid ${C.border2}`,
                                borderRadius: R.control, lineHeight: "var(--el-lh-normal)", fontStyle: "italic" }}>
                    “{e.note}”
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
