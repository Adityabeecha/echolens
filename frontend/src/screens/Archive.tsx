import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";
import { C, confColor, mono } from "../theme";
import { Centered } from "../ui";

const BADGE: Record<string, { bg: string; c: string; b: string }> = {
  Resolved: { bg: "rgba(76,192,119,.1)", c: C.good, b: "rgba(76,192,119,.35)" },
  "Insufficient evidence": { bg: C.hover, c: C.text3, b: C.border4 },
  "Needs human": { bg: "rgba(240,166,60,.1)", c: C.accent, b: "rgba(240,166,60,.35)" },
  "Budget exhausted": { bg: "rgba(224,88,79,.1)", c: C.bad, b: "rgba(224,88,79,.35)" },
};

const COLS = "64px 1.6fr 150px 70px 110px 70px 70px";

export function Archive({ onOpenInvestigation }: { onOpenInvestigation: (id: number) => void }) {
  const { data, loading, error } = useAsync(() => api.archive(), []);
  const [q, setQ] = useState("");

  if (loading) return <Centered>Loading archive…</Centered>;
  if (error) return <Centered>Backend unavailable.</Centered>;

  const rows = (data?.rows ?? []).filter((r) =>
    q ? (r.cause + r.id + r.status).toLowerCase().includes(q.toLowerCase()) : true
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "16px 28px", borderBottom: `1px solid ${C.border}`, flex: "none" }}>
        <div style={{ fontSize: 17, fontWeight: 600 }}>Case Archive</div>
        <div style={{ flex: 1 }} />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search cases…"
          style={{ width: 260, background: C.card, border: `1px solid ${C.border3}`, borderRadius: 7, color: C.text, fontFamily: "inherit", fontSize: 13, padding: "8px 12px" }}
        />
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        <div style={{ border: `1px solid ${C.border2}`, borderRadius: 10, overflowX: "auto", maxWidth: 1060 }}>
          <div style={{ minWidth: 820 }}>
            <div style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "10px 16px", background: C.card2, fontFamily: mono, fontSize: 10, letterSpacing: ".08em", color: C.faint, borderBottom: `1px solid ${C.border}` }}>
              <span>CASE</span>
              <span>ROOT CAUSE</span>
              <span>STATUS</span>
              <span>CONF</span>
              <span>HUMAN</span>
              <span>COST</span>
              <span>TIME</span>
            </div>
            {rows.length === 0 && (
              <div style={{ padding: "36px 20px", textAlign: "center", background: C.card }}>
                <div style={{ fontSize: 13.5, color: C.text3 }}>No cases match “{q}”</div>
              </div>
            )}
            {rows.map((r) => {
              const idNum = parseInt(r.id.replace("#", ""), 10);
              const badge = BADGE[r.status] ?? BADGE["Insufficient evidence"];
              return (
                <div
                  key={r.id}
                  onClick={() => onOpenInvestigation(idNum)}
                  style={{ display: "grid", gridTemplateColumns: COLS, gap: 12, padding: "13px 16px", borderBottom: `1px solid #1c1e27`, alignItems: "center", background: C.card, cursor: "pointer" }}
                >
                  <span style={{ fontFamily: mono, fontSize: 11.5, color: C.accent }}>{r.id}</span>
                  <span style={{ fontSize: 13, color: C.text2, lineHeight: 1.4 }}>{r.cause}</span>
                  <span>
                    <span style={{ fontFamily: mono, fontSize: 9.5, letterSpacing: ".04em", padding: "3px 8px", borderRadius: 4, background: badge.bg, color: badge.c, border: `1px solid ${badge.b}` }}>
                      {r.status.toUpperCase()}
                    </span>
                  </span>
                  <span style={{ fontFamily: mono, fontSize: 11.5, color: confColor(r.conf) }}>{r.conf.toFixed(2)}</span>
                  <span style={{ fontSize: 12, color: r.human === "Approved" ? C.good : r.human === "Challenged" ? C.accent : C.ghost }}>{r.human}</span>
                  <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{r.cost}</span>
                  <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>{r.time}</span>
                </div>
              );
            })}
          </div>
        </div>
        <div style={{ fontSize: 12, color: C.faint, marginTop: 12 }}>
          {data?.count ?? 0} cases · {data?.resolved_pct ?? 0}% resolved with human approval
        </div>
      </div>
    </div>
  );
}
