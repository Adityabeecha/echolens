import { CaseRow } from "../api";
import { age, impactLine } from "../format";
import { SEVERITY, primaryActionFor, statusMeta } from "../status";
import { C, R, S, T, mono } from "../theme";
import { Button, Spark } from "../ui";

/**
 * The one case card.
 *
 * Every list in the app renders this — Today's action queue, Today's top
 * problems, every tab of Cases. A case that looks different depending on which
 * screen you found it on is a case you have to re-identify each time.
 *
 * Anatomy, in this order: problem-statement title · status · severity · impact
 * · age · sparkline · one primary action matching the status.
 */
export function CaseCard({
  row,
  onOpen,
  onAction,
  compact,
  busy
}: {
  row: CaseRow;
  onOpen?: (row: CaseRow) => void;
  /** Runs the status-specific primary action. Falls back to opening the case. */
  onAction?: (row: CaseRow) => void;
  /** One line, for dense action queues. */
  compact?: boolean;
  busy?: boolean;
}) {
  const meta = statusMeta(row.status);
  const sev = row.severity ? SEVERITY[row.severity] : null;
  const stripe = sev?.color ?? meta.color;
  const clickable = row.id != null && !!onOpen;
  const impact = impactLine(row.impact);
  const action = primaryActionFor(row.status);

  const open = () => { if (clickable) onOpen!(row); };

  return (
    <div
      className={clickable ? "el-card el-card--click" : "el-card"}
      onClick={open}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={(e) => {
        if (clickable && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          open();
        }
      }}
      style={{ display: "flex", alignItems: "stretch", overflow: "hidden" }}
    >
      <span aria-hidden style={{ width: 3, flex: "none", background: stripe }} />
      <div
        style={{
          flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: S[4],
          padding: compact ? `${S[3]} ${S[4]}` : `${S[4]} ${S[5]}`
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            className={compact ? "el-truncate" : undefined}
            style={{
              fontSize: compact ? T.base : T.md, fontWeight: 600, color: C.text,
              lineHeight: "var(--el-lh-snug)"
            }}
          >
            {row.title}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[2],
                        flexWrap: "wrap" }}>
            <StatusChip status={row.status} />
            {sev && (
              <span style={{ fontFamily: mono, fontSize: T.micro,
                             letterSpacing: "var(--el-ls-wide)",
                             padding: `2px ${S[2]}`, borderRadius: R.sm, color: sev.color,
                             border: `1px solid ${sev.color}55`, textTransform: "uppercase" }}>
                {sev.label}
              </span>
            )}
            {impact && (
              <span style={{ fontSize: T.sm, color: C.muted }}>{impact}</span>
            )}
            {row.iterations && (
              <span className="el-num" style={{ fontSize: T.xs, color: C.accent }}>
                iteration {row.iterations.done}/{row.iterations.max}
              </span>
            )}
            {row.position != null && (
              <span className="el-num" style={{ fontSize: T.xs, color: C.dim }}>
                position {row.position}
              </span>
            )}
            <span className="el-mono" style={{ fontSize: T.xs, color: C.faint }}>
              {age(row.age_days)}
            </span>
          </div>
          {!compact && row.why && (
            <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[2],
                          lineHeight: "var(--el-lh-normal)" }}>
              {row.why}
            </div>
          )}
        </div>

        {row.spark && (
          <Spark points={row.spark} color={stripe}
                 title={`Weekly complaint volume for this case, last ${row.spark.length} weeks`} />
        )}

        <Button
          onClick={(e) => { e.stopPropagation(); (onAction ?? onOpen)?.(row); }}
          loading={busy}
          size="sm"
          variant={meta.needsYou ? "primary" : "ghost"}
          style={{ flex: "none" }}
        >
          {action}
        </Button>
      </div>
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const meta = statusMeta(status);
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: S[2],
        padding: `2px ${S[2]}`,
        borderRadius: R.pill, background: meta.bg, border: `1px solid ${meta.border}`,
        fontSize: T.xs, fontWeight: 500, color: meta.color, whiteSpace: "nowrap",
        lineHeight: "var(--el-lh-normal)"
      }}
    >
      {meta.pulse && (
        <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%",
                       background: meta.color,
                       animation: "elPulse 1.6s infinite", flex: "none" }} />
      )}
      {meta.label}
    </span>
  );
}
