import { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import { Icon, IconName } from "./components/Icon";
import { C, MEASURE, R, S, T, mono } from "./theme";

// Small monospace uppercase section label used across the design.
//
// The colour was `faint` at 10.5px, which measured 3.56:1 against a card —
// below the 4.5:1 floor. Every section heading in the app was simultaneously
// the smallest and the least readable text on screen. `faint` is now 6.0:1 and
// the size comes from the scale.
export function Label({ children, style, as }: {
  children: ReactNode;
  style?: CSSProperties;
  /**
   * Render as a real heading when this labels a SECTION.
   *
   * Label is used for two different jobs — section headings and inline captions
   * — and rendered a <div> for both, so most screens presented one <h1> and
   * then a flat run of headings that are visually obvious and semantically
   * invisible. A screen reader's heading list was empty below the title.
   * Opt-in, because a caption promoted to a heading is just as wrong.
   */
  as?: "h2" | "h3";
}) {
  const Tag = (as ?? "div") as "div" | "h2" | "h3";
  return (
    <Tag
      style={{
        margin: 0,
        fontFamily: mono,
        fontSize: T.micro,
        fontWeight: 500,
        letterSpacing: "var(--el-ls-wide)",
        textTransform: "uppercase",
        color: C.faint,
        ...style
      }}
    >
      {children}
    </Tag>
  );
}

// Horizontal progress bar (budget meters, confidence bars).
export function Bar({ pct, color, height = 5 }: { pct: number; color: string; height?: number }) {
  const v = Math.max(0, Math.min(100, pct));
  return (
    <div
      style={{ height, borderRadius: R.pill, background: C.track, overflow: "hidden" }}
      role="progressbar"
      aria-valuenow={Math.round(v)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        style={{
          height: "100%",
          width: `${v}%`,
          borderRadius: R.pill,
          background: color,
          transition: "width var(--el-dur-slow) var(--el-ease)"
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
  title
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
  const xy = (v: number, i: number) =>
    `${3 + i * stepX},${height - 3 - ((v - min) / span) * (height - 6)}`;
  const pts = points.map(xy).join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      style={{ flex: "none", overflow: "visible" }}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
    >
      {title && <title>{title}</title>}
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* The latest reading, marked. Without it the eye has to guess which end
          of the line is now. */}
      <circle
        cx={3 + (points.length - 1) * stepX}
        cy={height - 3 - ((points[points.length - 1] - min) / span) * (height - 6)}
        r={2}
        fill={color}
      />
    </svg>
  );
}

/** One day's complaint count, as the fix-verification chart reports it. */
export interface FixChartPoint {
  date: string;
  count: number;
}

/** The before/after series a FixWatch stores once its window closes. */
export interface FixChartData {
  before: FixChartPoint[];
  after: FixChartPoint[];
  before_rate: number | null;
  after_rate: number | null;
  terms: string[];
  fix_date?: string;
  window_days?: number;
  metric?: string;
}

// Did the fix work? Complaint volume either side of the ship date.
//
// The shape is declared here rather than imported from api.ts so a UI primitive
// does not depend on the API client; the server's chart object is structurally
// compatible.
export function BeforeAfterChart({
  chart,
  compact
}: {
  chart: FixChartData;
  compact?: boolean;
}) {
  if (!chart || (chart.before.length === 0 && chart.after.length === 0)) return null;
  const height = compact ? 34 : 60;
  const max = Math.max(1, ...chart.before.map((p) => p.count), ...chart.after.map((p) => p.count));
  const rate = (r: number | null) => (r == null ? "—" : `${r.toFixed(1)}/day`);

  // One sentence carrying what the bars mean, for anyone who cannot see them.
  // The div-based bars are decorative on their own — a screen reader met a run
  // of empty divs and learned nothing.
  const summary =
    `Complaints for ${chart.terms.join(", ") || "this problem"}: ` +
    `${rate(chart.before_rate)} before the fix, ${rate(chart.after_rate)} after.`;

  const Bars = ({ points, color }: { points: FixChartPoint[]; color: string }) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height }} aria-hidden>
        {points.map((p) => (
          <div
            key={p.date}
            title={`${p.date}: ${p.count}`}
            style={{
              flex: 1,
              height: `${Math.max(2, (p.count / max) * 100)}%`,
              background: color,
              borderRadius: "2px 2px 0 0",
              opacity: 0.85
            }}
          />
        ))}
      </div>
    </div>
  );

  return (
    <figure style={{ margin: `${S[3]} 0 0` }} role="img" aria-label={summary}>
      {!compact && (
        <figcaption style={{ fontSize: T.sm, color: C.muted, marginBottom: S[2] }}>
          Complaint volume for “{chart.terms.join(", ")}” around the fix.
        </figcaption>
      )}
      <div style={{ display: "flex", gap: S[4], alignItems: "stretch" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginBottom: S[1] }}>
            BEFORE · {rate(chart.before_rate)}
          </div>
          <Bars points={chart.before} color={C.bad} />
        </div>
        <div style={{ width: 1, background: C.border3, alignSelf: "stretch" }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginBottom: S[1] }}>
            AFTER · {rate(chart.after_rate)}
          </div>
          <Bars points={chart.after} color={C.good} />
        </div>
      </div>
    </figure>
  );
}

// A pulsing/solid status dot.
export function Dot({ color, pulse }: { color: string; pulse?: boolean }) {
  return (
    <span
      aria-hidden
      style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: color,
        flex: "none",
        display: "block",
        animation: pulse ? "elPulse 1.6s infinite" : "none"
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
  pulse
}: {
  label: string;
  color: string;
  bg: string;
  border: string;
  pulse?: boolean;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: S[2],
        padding: `3px ${S[3]}`,
        borderRadius: R.pill,
        background: bg,
        border: `1px solid ${border}`,
        fontSize: T.sm,
        fontWeight: 500,
        lineHeight: "var(--el-lh-snug)",
        color,
        whiteSpace: "nowrap"
      }}
    >
      {pulse && <Dot color={color} pulse />}
      {label}
    </span>
  );
}

/**
 * The button.
 *
 * Everything clickable used to be one of two things: a `<button>` with an inline
 * style object, or a `<button className="el-btn">` with a hand-written onKeyDown. There
 * were 33 of the latter, and because the focus rule targeted `button` and `a`
 * only, none of them showed a focus ring — a third of the interactive surface
 * was invisible to keyboard users. There was also no `:active` state anywhere in
 * the app, so nothing responded to being pressed.
 *
 * One component, real semantics, full state cycle from CSS.
 */
type Variant = "primary" | "ghost" | "quiet" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: IconName | string;
  children?: ReactNode;
}

export function Button({
  variant = "quiet",
  size = "md",
  loading = false,
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonProps) {
  const cls = [
    "el-btn",
    `el-btn--${variant}`,
    size === "sm" ? "el-btn--sm" : "",
    loading ? "el-btn--loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      {...rest}
      className={cls}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {icon && <Icon name={icon} size={size === "sm" ? 13 : 15} />}
      {children}
    </button>
  );
}

/**
 * A control that needs an account.
 *
 * Guests can read every screen, but the server refuses anything above `viewer`.
 * Rendering the button as normal and letting it 403 is the worst option: the
 * user clicks, waits, and gets an error that reads like a bug. Hiding it is
 * only marginally better — the demo then looks like it has no features.
 *
 * So the control stays visible and visibly disabled, and says what would
 * unlock it.
 */
export function SignedInOnly({
  can,
  reason = "Sign in to do this",
  children,
}: {
  /** The permission the caller already computed (e.g. canReview()). */
  can: boolean;
  reason?: string;
  children: ReactNode;
}) {
  if (can) return <>{children}</>;
  return (
    <span
      title={reason}
      // The wrapper takes the pointer events so the disabled control inside
      // still surfaces a tooltip; a disabled <button> fires no hover events.
      style={{ display: "inline-flex", cursor: "not-allowed" }}
    >
      <span aria-hidden style={{ pointerEvents: "none", opacity: 0.45, display: "inline-flex" }}>
        {children}
      </span>
      <span className="el-sr-only">{reason}</span>
    </span>
  );
}

/** A quiet banner telling a guest what they are looking at. */
export function GuestBanner({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap",
        maxWidth: MEASURE, marginBottom: S[5],
        padding: `${S[2]} ${S[4]}`,
        background: C.bgRaised, border: `1px solid ${C.border2}`,
        borderRadius: R.card, fontSize: T.sm, color: C.muted,
      }}
    >
      <Icon name="info" size={14} style={{ color: C.info }} />
      <span style={{ flex: 1, minWidth: 200 }}>
        You're browsing as a guest — everything here is real data, but running
        investigations and changing settings needs an account.
      </span>
      <Button variant="ghost" size="sm" onClick={onSignIn}>
        Sign in
      </Button>
    </div>
  );
}

/** Kept for the existing call sites; both are now the same component. */
export function PrimaryButton({ children, onClick, style }: {
  children: ReactNode; onClick?: () => void; style?: CSSProperties;
}) {
  return (
    <Button variant="primary" onClick={onClick} style={style}>
      {children}
    </Button>
  );
}

export function GhostButton({ children, onClick, style }: {
  children: ReactNode; onClick?: () => void; style?: CSSProperties;
}) {
  return (
    <Button variant="ghost" onClick={onClick} style={style}>
      {children}
    </Button>
  );
}

/**
 * Full-screen LOADING state.
 *
 * The docstring used to say "loading / error / empty", which made it read as a
 * second, plainer EmptyState — two unrelated treatments for one situation. Every
 * one of its eleven call sites is in fact a `loading && !data` branch, so the
 * comment was the only thing that was wrong. Empty belongs to EmptyState, and
 * failure to ErrorState; this is the wait.
 */
export function Centered({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: C.dim,
        fontSize: T.base,
        padding: S[6]
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
  back
}: {
  title: string;
  product?: string | null;
  subtitle?: ReactNode;
  right?: ReactNode;
  /** For screens reached from inside another screen rather than from the nav. */
  back?: { label: string; onClick: () => void };
}) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        gap: S[4],
        padding: `${S[4]} var(--el-gutter)`,
        borderBottom: `1px solid ${C.border}`,
        background: C.bg,
        flex: "none",
        flexWrap: "wrap"
      }}
    >
      {back && (
        <Button variant="quiet" size="sm" icon="chevronLeft" onClick={back.onClick}>
          {back.label}
        </Button>
      )}
      <div style={{ minWidth: 0 }}>
        <h1
          style={{
            margin: 0,
            fontSize: T.lg,
            fontWeight: 600,
            letterSpacing: "var(--el-ls-tight)",
            lineHeight: "var(--el-lh-tight)",
            color: C.text
          }}
        >
          {title}
          {product ? <span style={{ color: C.dim, fontWeight: 400 }}> · {product}</span> : null}
        </h1>
        {subtitle && (
          <div
            style={{
              fontFamily: mono,
              fontSize: T.micro,
              color: C.faint,
              letterSpacing: "var(--el-ls-wide)",
              textTransform: "uppercase",
              marginTop: S[1]
            }}
          >
            {subtitle}
          </div>
        )}
      </div>
      <div style={{ flex: 1, minWidth: S[4] }} />
      {right}
    </header>
  );
}

/** The scrolling body of a screen. One measure, one gutter, everywhere. */
export function ScreenBody({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div
      style={{
        flex: 1,
        overflow: "auto",
        padding: `${S[6]} var(--el-gutter) ${S[12]}`,
        ...style
      }}
    >
      <div style={{ maxWidth: MEASURE }}>{children}</div>
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
  icon = "search"
}: {
  title: string;
  body: ReactNode;
  action?: string;
  onAction?: () => void;
  icon?: IconName | string;
}) {
  return (
    <div
      style={{
        maxWidth: "min(640px, 100%)",
        padding: `${S[8]} ${S[6]}`,
        border: `1px dashed ${C.border3}`,
        borderRadius: R.card,
        textAlign: "center",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: S[2]
      }}
    >
      <span
        style={{
          display: "grid",
          placeItems: "center",
          width: 36,
          height: 36,
          borderRadius: R.pill,
          background: C.bgRaised,
          border: `1px solid ${C.border2}`,
          color: C.dim,
          marginBottom: S[1]
        }}
      >
        <Icon name={icon} size={17} />
      </span>
      <div style={{ fontSize: T.md, fontWeight: 600, color: C.text2 }}>{title}</div>
      <div style={{ fontSize: T.base, color: C.dim, lineHeight: "var(--el-lh-normal)", maxWidth: "min(460px, 100%)" }}>
        {body}
      </div>
      {action && onAction && (
        <Button variant="ghost" onClick={onAction} style={{ marginTop: S[3] }}>
          {action}
        </Button>
      )}
    </div>
  );
}

/** A failure the reader can act on, rather than a dead end. */
export function ErrorState({
  title = "Can't reach EchoLens",
  detail,
  onRetry
}: {
  title?: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      style={{
        maxWidth: "min(640px, 100%)",
        padding: `${S[5]} ${S[5]}`,
        border: `1px solid ${C.badLine}`,
        borderRadius: R.card,
        background: C.card,
        display: "flex",
        gap: S[3],
        alignItems: "flex-start"
      }}
    >
      <span style={{ color: C.bad, marginTop: 0 }}>
        <Icon name="warning" size={17} />
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: T.md, fontWeight: 600, color: C.text2 }}>{title}</div>
        <div style={{ fontSize: T.base, color: C.dim, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
          {detail ||
            "The backend may be waking up (the free tier sleeps after a while). Give it ~30 seconds, then retry."}
        </div>
        {onRetry && (
          <Button variant="ghost" size="sm" icon="retry" onClick={onRetry} style={{ marginTop: S[3] }}>
            Retry
          </Button>
        )}
      </div>
    </div>
  );
}

/** Placeholder rows while a list loads, sized like the rows they become. */
export function Skeleton({ rows = 3, height = 74 }: { rows?: number; height?: number }) {
  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}
      aria-busy="true"
      aria-live="polite"
    >
      <span className="el-sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height,
            borderRadius: R.card,
            background: C.card,
            border: `1px solid ${C.border2}`,
            animation: "elSkeleton 1.6s infinite",
            animationDelay: `${i * 0.12}s`
          }}
        />
      ))}
    </div>
  );
}
