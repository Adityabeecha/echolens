import { CaseRow } from "../api";
import { age, impactLine } from "../format";
import { SEVERITY, primaryActionFor, statusMeta } from "../status";
import { C, mono, sans } from "../theme";
import { Spark } from "../ui";

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
  busy,
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
      onKeyDown={(e) => { if (clickable && (e.key === "Enter" || e.key === " ")) open(); }}
      style={{ display: "flex", alignItems: "stretch", overflow: "hidden" }}
    >
      <div style={{ width: 3, flex: "none", background: stripe }} />
      <div
        style={{
          flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 14,
          padding: compact ? "11px 15px" : "15px 18px",
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: compact ? 13.5 : 14.5, fontWeight: 600, color: C.text,
              lineHeight: 1.4, overflow: "hidden", textOverflow: "ellipsis",
              whiteSpace: compact ? "nowrap" : "normal",
            }}
          >
            {row.title}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 7,
                        flexWrap: "wrap" }}>
            <StatusChip status={row.status} />
            {sev && (
              <span style={{ fontFamily: mono, fontSize: 10, letterSpacing: ".04em",
                             padding: "2px 7px", borderRadius: 4, color: sev.color,
                             border: `1px solid ${sev.color}55`, textTransform: "uppercase" }}>
                {sev.label}
              </span>
            )}
            {impact && (
              <span style={{ fontSize: 12, color: C.muted }}>{impact}</span>
            )}
            {row.iterations && (
              <span style={{ fontFamily: mono, fontSize: 10.5, color: C.accent }}>
                iteration {row.iterations.done}/{row.iterations.max}
              </span>
            )}
            {row.position != null && (
              <span style={{ fontFamily: mono, fontSize: 10.5, color: C.dim }}>
                position {row.position}
              </span>
            )}
            <span style={{ fontFamily: mono, fontSize: 10.5, color: C.faint }}>
              {age(row.age_days)}
            </span>
          </div>
          {!compact && row.why && (
            <div style={{ fontSize: 12.5, color: C.dim, marginTop: 6, lineHeight: 1.5 }}>
              {row.why}
            </div>
          )}
        </div>

        {row.spark && (
          <Spark points={row.spark} color={stripe}
                 title={`Weekly complaint volume for this case, last ${row.spark.length} weeks`} />
        )}

        <button
          onClick={(e) => { e.stopPropagation(); (onAction ?? onOpen)?.(row); }}
          disabled={busy}
          className="el-btn"
          style={{
            flex: "none", background: meta.needsYou ? C.accent : "transparent",
            color: meta.needsYou ? C.onAccent : C.accent,
            border: meta.needsYou ? "none" : `1px solid rgba(240,166,60,.4)`,
            borderRadius: 7, padding: "8px 14px", fontSize: 12.5,
            fontWeight: meta.needsYou ? 600 : 500, fontFamily: sans,
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "…" : action}
        </button>
      </div>
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const meta = statusMeta(status);
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 10px",
        borderRadius: 20, background: meta.bg, border: `1px solid ${meta.border}`,
        fontSize: 11.5, fontWeight: 500, color: meta.color, whiteSpace: "nowrap",
      }}
    >
      {meta.pulse && (
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: meta.color,
                       animation: "elPulse 1.4s infinite", flex: "none" }} />
      )}
      {meta.label}
    </span>
  );
}
