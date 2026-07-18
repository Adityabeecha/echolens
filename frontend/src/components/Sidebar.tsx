import { C, mono } from "../theme";
import { Screen } from "../nav";

interface Props {
  screen: Screen;
  go: (s: Screen) => void;
  running: { label: string; detail: string; color: string; dot: string; pulse: boolean } | null;
  onOpenCase: () => void;
}

const NAV: { key: Screen; icon: string; label: string; iconColor?: string }[] = [
  { key: "feed", icon: "◉", label: "Case Feed", iconColor: C.accent },
  { key: "archive", icon: "▤", label: "Archive" },
  { key: "sources", icon: "⇄", label: "Sources" },
  { key: "costs", icon: "$", label: "Costs" },
];

// The feed / case / finding screens all keep "Case Feed" highlighted.
const FEED_GROUP: Screen[] = ["feed", "case", "finding"];

export function Sidebar({ screen, go, running, onOpenCase }: Props) {
  return (
    <div
      style={{
        width: 216,
        flex: "none",
        display: "flex",
        flexDirection: "column",
        borderRight: `1px solid ${C.border}`,
        background: C.bgRaised,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "18px 18px 16px" }}>
        <div
          style={{
            width: 26,
            height: 26,
            borderRadius: "50%",
            border: `2px solid ${C.accent}`,
            position: "relative",
            flex: "none",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 5,
              borderRadius: "50%",
              background: "radial-gradient(circle at 35% 35%, #f7bd6a, #b06f1a)",
            }}
          />
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: ".02em" }}>EchoLens</div>
          <div style={{ fontFamily: mono, fontSize: 9.5, color: C.faint, letterSpacing: ".08em" }}>
            FEEDBACK FORENSICS
          </div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "8px 10px" }}>
        {NAV.map((n) => {
          const active =
            n.key === "feed" ? FEED_GROUP.includes(screen) : screen === n.key;
          return (
            <div
              key={n.key}
              onClick={() => go(n.key)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 10px",
                borderRadius: 6,
                cursor: "pointer",
                background: active ? C.active : "transparent",
                color: active ? C.text : C.muted,
              }}
            >
              <span style={{ fontFamily: mono, fontSize: 10, width: 16, color: n.iconColor ?? C.faint }}>
                {n.icon}
              </span>
              {n.label}
            </div>
          );
        })}
      </div>

      <div style={{ flex: 1 }} />

      {running && (
        <div
          style={{
            margin: 10,
            padding: "10px 12px",
            border: `1px solid ${C.border2}`,
            borderRadius: 8,
            background: C.card2,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: running.dot,
                animation: running.pulse ? "elPulse 1.6s infinite" : "none",
                flex: "none",
              }}
            />
            <div style={{ fontSize: 12, color: C.text3 }}>{running.label}</div>
          </div>
          <div
            onClick={() => go("case")}
            style={{
              fontFamily: mono,
              fontSize: 11,
              color: running.color,
              marginTop: 4,
              marginLeft: 15,
              cursor: "pointer",
            }}
          >
            {running.detail}
          </div>
        </div>
      )}
    </div>
  );
}
