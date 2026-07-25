import { Evidence, Investigation } from "../../api";
import { plural } from "../../format";
import { C, mono } from "../../theme";
import { EmptyState, Label } from "../../ui";

/** Every citation this case rests on, in one table. */
export function EvidenceTab({ inv, onOpenEvidence }: {
  inv: Investigation; onOpenEvidence: (e: Evidence) => void;
}) {
  const bySource = new Map<string, number>();
  inv.evidence.forEach((e) => bySource.set(e.source, (bySource.get(e.source) ?? 0) + 1));

  if (inv.evidence.length === 0) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: "24px 28px" }}>
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
      <div style={{ maxWidth: 900, padding: "24px 28px 60px" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12,
                      flexWrap: "wrap" }}>
          <Label>
            {inv.evidence.length} {plural(inv.evidence.length, "ITEM")} ·{" "}
            {bySource.size} {plural(bySource.size, "SOURCE")}
          </Label>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[...bySource.entries()].map(([src, n]) => (
              <span key={src} style={{ fontFamily: mono, fontSize: 10, padding: "3px 9px",
                                       borderRadius: 20, background: C.hover,
                                       border: `1px solid ${C.border3}`, color: C.muted }}>
                {src.replace(/_/g, " ")} · {n}
              </span>
            ))}
          </div>
        </div>

        <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 14px", lineHeight: 1.55 }}>
          A cause is only claimed when at least two independent sources agree. Click any row to
          read the full item it was quoted from.
        </p>

        <div style={{ border: `1px solid ${C.border2}`, borderRadius: 10, overflow: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "9px 16px",
                        background: C.card2, fontFamily: mono, fontSize: 10,
                        letterSpacing: ".08em", color: C.faint,
                        borderBottom: `1px solid ${C.border}` }}>
            <span>ID</span><span>SOURCE</span><span>SNIPPET</span><span>SUPPORTS</span>
          </div>
          {inv.evidence.map((e) => (
            <div key={e.id} onClick={() => onOpenEvidence(e)} className="el-row el-row--click"
              role="button" tabIndex={0}
              onKeyDown={(ev) => { if (ev.key === "Enter") onOpenEvidence(e); }}
              style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "12px 16px",
                       borderBottom: `1px solid #1c1e27`, cursor: "pointer", background: C.card }}>
              <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>{e.id}</span>
              <span style={{ fontFamily: mono, fontSize: 11, color: C.muted,
                             textTransform: "uppercase" }}>{e.source}</span>
              <span style={{ fontSize: 12.5, color: C.text3, lineHeight: 1.45 }}>
                “{e.snippet}”
              </span>
              <span style={{ fontSize: 12, color: e.contradicts.length ? C.bad : C.good }}>
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
