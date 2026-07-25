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

// Sparkline from a real measured series. Self-scaling, because the series now
// comes from the corpus (weekly complaint counts) rather than from a lookup
// table keyed on a z-score — a shape that was decorative, not measured.
export function Spark({
  points,
  color,
  width = 84,
  height = 22,
  title,
}: {
  points: number[];
  color: string;
  width?: number;
  height?: number;
  title?: string;
}) {
  if (!points || points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const stepX = (width - 6) / (points.length - 1);
  const pts = points
    .map((v, i) => `${3 + i * stepX},${height - 3 - ((v - min) / span) * (height - 6)}`)
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ flex: "none" }}>
      {title && <title>{title}</title>}
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5}
                strokeLinejoin="round" strokeLinecap="round" />
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

/**
 * Every screen header reads "Screen · Product".
 *
 * Without the product you cannot tell, from the screen alone, which app you are
 * looking at — and switching products changed the data underneath an unchanged
 * heading. The product is not decoration here; it is the scope of everything
 * below it.
 */
export function ScreenHeader({
  title,
  product,
  subtitle,
  right,
  back,
}: {
  title: string;
  product?: string | null;
  subtitle?: ReactNode;
  right?: ReactNode;
  /** For screens reached from inside another screen rather than from the nav. */
  back?: { label: string; onClick: () => void };
}) {
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
      {back && (
        <span onClick={back.onClick} className="el-btn" role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") back.onClick(); }}
          style={{ color: C.dim, cursor: "pointer", fontSize: 13, whiteSpace: "nowrap" }}>
          ← Back to {back.label}
        </span>
      )}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 17, fontWeight: 600, letterSpacing: "-0.01em" }}>
          {title}
          {product ? (
            <span style={{ color: C.dim, fontWeight: 500 }}> · {product}</span>
          ) : null}
        </div>
        {subtitle && (
          <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint,
                        letterSpacing: ".04em", marginTop: 3 }}>
            {subtitle}
          </div>
        )}
      </div>
      <div style={{ flex: 1 }} />
      {right}
    </div>
  );
}

/**
 * An empty state that names the product and the next action.
 *
 * "No data" tells you nothing you did not already know. Every list here says
 * which product is empty and what to press.
 */
export function EmptyState({
  title,
  body,
  action,
  onAction,
}: {
  title: string;
  body: ReactNode;
  action?: string;
  onAction?: () => void;
}) {
  return (
    <div
      style={{
        maxWidth: 720, padding: "34px 26px", border: `1px dashed ${C.border4}`,
        borderRadius: 12, textAlign: "center",
      }}
    >
      <div style={{ fontSize: 15, fontWeight: 600, color: C.text3 }}>{title}</div>
      <div style={{ fontSize: 13, color: C.dim, marginTop: 7, lineHeight: 1.6,
                    maxWidth: 480, margin: "7px auto 0" }}>
        {body}
      </div>
      {action && onAction && (
        <button onClick={onAction} className="el-btn"
          style={{ marginTop: 16, background: "transparent", color: C.accent,
                   border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7,
                   padding: "9px 18px", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
          {action}
        </button>
      )}
    </div>
  );
}

/** A failure the reader can act on, rather than a dead end. */
export function ErrorState({
  title = "Can't reach EchoLens",
  detail,
  onRetry,
}: {
  title?: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div style={{ maxWidth: 720, padding: "26px 22px", border: `1px solid ${C.border3}`,
                  borderRadius: 12, background: C.card }}>
      <div style={{ fontSize: 14.5, fontWeight: 600, color: C.text3 }}>{title}</div>
      <div style={{ fontSize: 13, color: C.dim, marginTop: 6, lineHeight: 1.55 }}>
        {detail ||
          "The backend may be waking up (the free tier sleeps after a while). Give it ~30 seconds, then retry."}
      </div>
      {onRetry && (
        <button onClick={onRetry} className="el-btn"
          style={{ marginTop: 14, background: "transparent", color: C.accent,
                   border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7,
                   padding: "8px 16px", fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
          Retry
        </button>
      )}
    </div>
  );
}

/** Placeholder rows while a list loads, sized like the rows they become. */
export function Skeleton({ rows = 3, height = 74 }: { rows?: number; height?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, maxWidth: 940 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ height, borderRadius: 10, background: C.card,
                              border: `1px solid ${C.border2}`,
                              animation: "elSkeleton 1.4s infinite",
                              animationDelay: `${i * 0.15}s` }} />
      ))}
    </div>
  );
}
