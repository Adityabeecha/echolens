import { Evidence, Investigation } from "../../api";
import { plural } from "../../format";
import { C, MEASURE, R, S, T, mono } from "../../theme";
import { EmptyState, Label } from "../../ui";

/** Every citation this case rests on, in one table. */
export function EvidenceTab({ inv, onOpenEvidence }: {
  inv: Investigation; onOpenEvidence: (e: Evidence) => void;
}) {
  const bySource = new Map<string, number>();
  inv.evidence.forEach((e) => bySource.set(e.source, (bySource.get(e.source) ?? 0) + 1));

  if (inv.evidence.length === 0) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: `${S[6]} ${S[6]}` }}>
        <EmptyState
          title="No evidence collected yet"
          body={
            inv.status === "running"
              ? "The investigation cites reviews and issues as it retrieves them — they appear here the moment it does."
              : "This case reached its verdict without retrieving citable evidence. The trace shows what was attempted."
          }
        />
      </div>
    );
  }

  const COLS = "76px 120px 1fr 140px";
  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: MEASURE, padding: `${S[6]} ${S[6]} ${S[12]}` }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: S[3], marginBottom: S[3],
                      flexWrap: "wrap" }}>
          <Label>
            {inv.evidence.length} {plural(inv.evidence.length, "ITEM")} ·{" "}
            {bySource.size} {plural(bySource.size, "SOURCE")}
          </Label>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: S[2], flexWrap: "wrap" }}>
            {[...bySource.entries()].map(([src, n]) => (
              <span key={src} style={{ fontFamily: mono, fontSize: T.micro, padding: `${S[1]} ${S[2]}`,
                                       borderRadius: R.pill, background: C.hover,
                                       border: `1px solid ${C.border3}`, color: C.muted }}>
                {src.replace(/_/g, " ")} · {n}
              </span>
            ))}
          </div>
        </div>

        <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 14px", lineHeight: "var(--el-lh-normal)" }}>
          A cause is only claimed when at least two independent sources agree. Click any row to
          read the full item it was quoted from.
        </p>

        <div style={{ border: `1px solid ${C.border2}`, borderRadius: R.card, overflow: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: COLS, gap: S[3], padding: `${S[2]} ${S[4]}`,
                        background: C.card2, fontFamily: mono, fontSize: T.micro,
                        letterSpacing: ".08em", color: C.faint,
                        borderBottom: `1px solid ${C.border}` }}>
            <span>ID</span><span>SOURCE</span><span>SNIPPET</span><span>SUPPORTS</span>
          </div>
          {inv.evidence.map((e) => (
            <div key={e.id} onClick={() => onOpenEvidence(e)} className="el-row el-row--click"
              role="button" tabIndex={0}
              onKeyDown={(ev) => { if (ev.key === "Enter") onOpenEvidence(e); }}
              style={{ display: "grid", gridTemplateColumns: COLS, gap: S[3], padding: `${S[3]} ${S[4]}`,
                       borderBottom: `1px solid #1c1e27`, cursor: "pointer", background: C.card }}>
              <span style={{ fontFamily: mono, fontSize: T.xs, color: C.accent }}>{e.id}</span>
              <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted,
                             textTransform: "uppercase" }}>{e.source}</span>
              <span style={{ fontSize: T.sm, color: C.text3, lineHeight: "var(--el-lh-snug)" }}>
                “{e.snippet}”
              </span>
              <span style={{ fontSize: T.sm, color: e.contradicts.length ? C.bad : C.good }}>
                {e.supports.join(", ") ||
                  (e.contradicts.length ? `contradicts ${e.contradicts.join(", ")}` : "—")}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
