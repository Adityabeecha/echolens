import { CaseRow, TrustSummary, getActiveProduct } from "../api";
import { age, impactLine, plural, sourceLabel } from "../format";
import { formatRoute } from "../nav";
import { SEVERITY, primaryActionFor, statusMeta } from "../status";
import { C, R, S, T, mono } from "../theme";
import { Button, Spark } from "../ui";
import { DecisionChip } from "../screens/case/CaseActions";
import { Icon } from "./Icon";

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
  /** Denser spacing for action queues. */
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
      className="el-card el-case-card"
      style={{ display: "flex", alignItems: "stretch", overflow: "hidden" }}
    >
      <span className="el-case-status-mark" aria-hidden style={{ background: stripe }} />
      <div
        style={{
          flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: S[4],
          padding: compact ? `${S[3]} ${S[4]}` : `${S[4]} ${S[5]}`
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          {clickable ? (
            <button type="button" onClick={open}
              // Space must activate the card without also scrolling the page.
              onKeyDown={(e) => { if (e.key === " ") { e.preventDefault(); open(); } }}
              className="el-case-title el-ui-forms-case-title" title={row.title}>
              {row.title}
            </button>
          ) : (
            <div
              className="el-ui-forms-case-title" title={row.title}
              style={{
                fontSize: compact ? T.base : T.md, fontWeight: 600, color: C.text,
                lineHeight: "var(--el-lh-snug)"
              }}
            >
              {row.title}
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[2],
                        flexWrap: "wrap" }}>
            <span className="el-case-id">
              {row.id != null ? `Case #${row.id}` : "Queued"}
            </span>
            <StatusChip status={row.status} />
            <DecisionChip decision={row.decision} />
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
            {row.trust && row.id != null && (
              <TrustBadge trust={row.trust} onClick={() => openCaseEvidence(row.id!)} />
            )}
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

/** Straight to a case's Evidence tab — what a trust badge is a summary of. */
function openCaseEvidence(id: number) {
  window.location.hash = formatRoute({ screen: "case", id, tab: "evidence", productId: getActiveProduct() });
}

/**
 * How much to trust a finding, in one line: the confidence band, what the
 * evidence is, and whether two independent sources back the cause. The label
 * is the server's, and it says "verified" only when the finding is approved
 * AND a fix is confirmed — the same rule the Inspector uses for "proven".
 */
export function TrustBadge({ trust, onClick }: { trust: TrustSummary; onClick?: () => void }) {
  const tone = !trust.two_source_ok
    ? { color: C.muted, bg: "transparent", line: C.border3, icon: "warning" }
    : trust.verified
      ? { color: C.good, bg: C.goodBg, line: C.goodLine, icon: "check" }
      : { color: C.info, bg: C.infoBg, line: C.infoLine, icon: "info" };
  const breakdown = trust.sources
    .map((s) => `${sourceLabel(s.source)}: ${s.count} ${plural(s.count, "item")}`).join(" · ");
  const title = (breakdown || "No evidence rows")
    + (trust.two_source_ok ? "" : " — the cause is not yet backed by two independent sources")
    + (onClick ? ". Click to open the evidence." : "");
  const style = {
    display: "inline-flex", alignItems: "center", gap: S[1], padding: `2px ${S[2]}`,
    borderRadius: R.pill, background: tone.bg, border: `1px solid ${tone.line}`,
    fontSize: T.xs, color: tone.color, whiteSpace: "nowrap" as const, maxWidth: "100%",
    overflow: "hidden", textOverflow: "ellipsis", lineHeight: "var(--el-lh-normal)",
  };
  const body = (
    <>
      <Icon name={tone.icon} size={11} />
      <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{trust.label}</span>
    </>
  );
  if (!onClick) return <span title={title} style={style}>{body}</span>;
  return (
    <button type="button" className="el-btn" title={title}
      aria-label={`${trust.label}. Open the evidence`}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      style={{ ...style, cursor: "pointer", fontFamily: "inherit" }}>
      {body}
    </button>
  );
}
