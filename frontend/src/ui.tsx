import { CSSProperties, ReactNode } from "react";
import { C, mono } from "./theme";

// Small monospace uppercase section label used across the design.
export function Label({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        fontFamily: mono,
        fontSize: 10.5,
        letterSpacing: ".1em",
        color: C.faint,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

// Horizontal progress bar (budget meters, confidence bars).
export function Bar({ pct, color, height = 5 }: { pct: number; color: string; height?: number }) {
  return (
    <div style={{ height, borderRadius: 3, background: C.track, overflow: "hidden" }}>
      <div
        style={{
          height: "100%",
          width: `${Math.max(0, Math.min(100, pct))}%`,
          borderRadius: 3,
          background: color,
          transition: "width 1.2s cubic-bezier(.2,.8,.2,1)",
        }}
      />
    </div>
  );
}

// Sparkline from a small numeric series (0..~16 range like the mock).
export function Spark({ points, color }: { points: number[]; color: string }) {
  const pts = points.map((v, i) => `${4 + i * 11},${20 - v}`).join(" ");
  return (
    <svg width={84} height={22} viewBox="0 0 84 22" style={{ flex: "none" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} />
    </svg>
  );
}

// A pulsing/solid status dot.
export function Dot({ color, pulse }: { color: string; pulse?: boolean }) {
  return (
    <div
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: color,
        flex: "none",
        animation: pulse ? "elPulse 1.4s infinite" : "none",
      }}
    />
  );
}

// Rounded pill chip (triage decisions, case state).
export function Chip({
  label,
  color,
  bg,
  border,
  pulse,
}: {
  label: string;
  color: string;
  bg: string;
  border: string;
  pulse?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 7,
        padding: "5px 11px",
        borderRadius: 20,
        background: bg,
        border: `1px solid ${border}`,
      }}
    >
      {pulse && <Dot color={C.accent} pulse />}
      <span style={{ fontSize: 12, fontWeight: 500, color, whiteSpace: "nowrap" }}>{label}</span>
    </div>
  );
}

export function PrimaryButton({
  children,
  onClick,
  style,
}: {
  children: ReactNode;
  onClick?: () => void;
  style?: CSSProperties;
}) {
  return (
    <button
      onClick={onClick}
      className="el-btn"
      style={{
        background: C.accent,
        color: C.onAccent,
        border: "none",
        borderRadius: 6,
        padding: "8px 14px",
        fontWeight: 600,
        fontSize: 13,
        cursor: "pointer",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

export function GhostButton({
  children,
  onClick,
  style,
}: {
  children: ReactNode;
  onClick?: () => void;
  style?: CSSProperties;
}) {
  return (
    <button
      onClick={onClick}
      className="el-btn"
      style={{
        background: "transparent",
        color: C.accent,
        border: `1px solid rgba(240,166,60,.4)`,
        borderRadius: 6,
        padding: "8px 14px",
        fontWeight: 500,
        fontSize: 13,
        cursor: "pointer",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

// Full-screen centered state (loading / error / empty).
export function Centered({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: C.dim,
        fontSize: 14,
      }}
    >
      {children}
    </div>
  );
}

export function ScreenHeader({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "16px 28px",
        borderBottom: `1px solid ${C.border}`,
        flex: "none",
      }}
    >
      <div style={{ fontSize: 17, fontWeight: 600 }}>{title}</div>
      <div style={{ flex: 1 }} />
      {right}
    </div>
  );
}

// Deterministic sparkline seed from a slug so cards look stable.
export function sparkFor(z: number): number[] {
  if (z >= 3) return [4, 5, 4, 6, 7, 9, 12, 16];
  if (z >= 2) return [8, 7, 9, 8, 10, 9, 13, 14];
  return [9, 11, 8, 10, 9, 11, 10, 9];
}
