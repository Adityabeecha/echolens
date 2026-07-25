import { ReactNode, useState } from "react";
import { CaseRow, PortfolioProduct, api } from "../api";
import { CaseCard } from "../components/CaseCard";
import { withToast } from "../components/Toast";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { statusMeta } from "../status";
import { C, mono } from "../theme";
import { EmptyState, ErrorState, Label, ScreenHeader, Skeleton, Spark } from "../ui";

interface Props {
  productName: string | null;
  onOpenCase: (id: number, status?: string) => void;
  onGoCases: (tab?: string) => void;
  onGoSources: () => void;
  onGoPlan: () => void;
  reloadKey: number;
  bumpReload: () => void;
}

/**
 * Today — the answer to "what needs me right now".
 *
 * Every other screen answered a question about EchoLens's internals: which
 * anomalies were detected, which investigations ran, what they cost. None
 * answered the question a PM actually opens the app with. This one does, top to
 * bottom: how are we doing, what needs me, what is running, what is biggest,
 * what changed this week.
 *
 * Deliberately absent: raw anomalies. Today is for decisions; signals live at
 * the bottom of Cases where they can be triaged in a batch.
 */
export function Today({
  productName, onOpenCase, onGoCases, onGoSources, onGoPlan, reloadKey, bumpReload,
}: Props) {
  const cases = useAsync(() => api.cases(), [reloadKey]);
  const portfolio = useAsync(() => api.portfolio(), [reloadKey]);
  const snapshot = useAsync(() => api.snapshot(), [reloadKey]);
  const sources = useAsync(() => api.sources(), [reloadKey]);
  const brief = useAsync(() => api.brief(), [reloadKey]);
  const [cancelling, setCancelling] = useState<number | null>(null);

  const rows = cases.data?.cases ?? [];
  const product = productName ?? cases.data?.product ?? null;
  const me = (portfolio.data?.products ?? []).find((p) => p.product === product) ?? null;

  const staleSources = (sources.data?.connected ?? []).filter((s) => s.stale || s.error);
  const needsYou = rows.filter((r) => statusMeta(r.status).needsYou);
  const running = rows.filter((r) => r.status === "running");
  const queued = rows.filter((r) => r.status === "queued");

  // "Open" = a real problem with no verified fix. Ranked by how bad it is, and
  // deduped against the action queue so Today never shows one case twice.
  const surfaced = new Set(needsYou.map((r) => r.id));
  const openProblems = rows
    .filter((r) => ["resolved", "needs_review", "needs_human", "regressed"].includes(r.status))
    .filter((r) => !surfaced.has(r.id))
    .sort((a, b) =>
      (b.severity_score ?? 0) - (a.severity_score ?? 0) ||
      (b.impact?.affected_pct ?? 0) - (a.impact?.affected_pct ?? 0))
    .slice(0, 5);

  const cancelQueued = async (row: CaseRow) => {
    if (row.queue_id == null) return;
    setCancelling(row.queue_id);
    await withToast(() => api.cancelQueued(row.queue_id!), {
      success: "Removed from the queue.",
      failure: "Couldn't cancel that queued item",
    });
    setCancelling(null);
    bumpReload();
  };

  const loading = cases.loading && !cases.data;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Today"
        product={product}
        subtitle="WHAT NEEDS YOU RIGHT NOW"
        right={
          <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>
            {running.length > 0
              ? `${running.length} ${plural(running.length, "investigation")} running`
              : "nothing running"}
          </span>
        }
      />

      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px 60px" }}>
        {cases.error ? (
          <ErrorState onRetry={cases.reload} />
        ) : (
          <>
            <ScoreStrip
              me={me}
              weekly={snapshot.data?.weekly ?? []}
              onOpenCase={onOpenCase}
              loading={portfolio.loading && !portfolio.data}
            />

            {/* ── a. what needs you ─────────────────────────────────── */}
            <Section
              title="NEEDS YOU"
              count={needsYou.length + staleSources.length}
              color={C.accent}
            >
              {loading ? (
                <Skeleton rows={2} height={62} />
              ) : needsYou.length === 0 && staleSources.length === 0 ? (
                <Reassurance running={running.length} queued={queued.length} product={product} />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 9, maxWidth: 940 }}>
                  {staleSources.map((s) => (
                    <ActionRow
                      key={`src-${s.name}-${s.detail}`}
                      title={
                        s.error
                          ? `${s.name} stopped collecting — findings may be based on old data`
                          : `${s.name} has gone stale${s.staleSince ? ` since ${s.staleSince}` : ""}`
                      }
                      detail={s.why || s.error || s.lastPull}
                      action="Fix source"
                      onAction={onGoSources}
                    />
                  ))}
                  {needsYou.map((r) => (
                    <CaseCard
                      key={`case-${r.id}`}
                      row={r}
                      compact
                      onOpen={(row) => row.id != null && onOpenCase(row.id, row.status)}
                    />
                  ))}
                </div>
              )}
            </Section>

            {/* ── b. what the machine is doing ──────────────────────── */}
            <Section title="RUNNING & QUEUED" count={running.length + queued.length}>
              {running.length + queued.length === 0 ? (
                <EmptyState
                  title="Nothing in flight"
                  body={
                    <>
                      No investigation is running or queued for{" "}
                      <strong style={{ color: C.text3 }}>{product ?? "this product"}</strong>. Pick
                      something from Signals at the bottom of Cases to start one.
                    </>
                  }
                  action="Go to Cases"
                  onAction={() => onGoCases("all")}
                />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 9, maxWidth: 940 }}>
                  {running.map((r) => (
                    <CaseCard key={`run-${r.id}`} row={r} compact
                              onOpen={(row) => row.id != null && onOpenCase(row.id, row.status)} />
                  ))}
                  {queued.map((r) => (
                    <CaseCard
                      key={`q-${r.queue_id}`}
                      row={r}
                      compact
                      busy={r.queue_id != null && cancelling === r.queue_id}
                      onAction={cancelQueued}
                    />
                  ))}
                </div>
              )}
            </Section>

            {/* ── c. what is biggest ────────────────────────────────── */}
            <Section
              title="TOP OPEN PROBLEMS"
              count={openProblems.length}
              action={{ label: "Plan the quarter →", onClick: onGoPlan }}
            >
              {openProblems.length === 0 ? (
                <EmptyState
                  title={
                    needsYou.length > 0
                      ? "Everything open is in Needs you above"
                      : `No open problems for ${product ?? "this product"}`
                  }
                  body={
                    needsYou.length > 0
                      ? "Nothing else is waiting behind the action queue."
                      : "Every case that resolved is either fixed or in verification. Nothing is sitting unaddressed."
                  }
                />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 9, maxWidth: 940 }}>
                  {openProblems.map((r) => (
                    <CaseCard key={`open-${r.id}`} row={r}
                              onOpen={(row) => row.id != null && onOpenCase(row.id, row.status)} />
                  ))}
                </div>
              )}
            </Section>

            {/* ── d. what changed ───────────────────────────────────── */}
            <Section title="THIS WEEK">
              {brief.data && brief.data.lines.length > 0 ? (
                <div style={{ maxWidth: 940, padding: "16px 20px", background: C.card,
                              border: `1px solid ${C.border2}`, borderRadius: 12,
                              display: "flex", flexDirection: "column", gap: 7 }}>
                  <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint,
                                marginBottom: 3 }}>
                    {brief.data.generated}
                  </div>
                  {brief.data.lines.map((line, i) => (
                    <div key={i} style={{ fontSize: 13.5, lineHeight: 1.55,
                                          color: i === 0 ? C.text2 : C.text3 }}>
                      <Cited text={line} onOpen={(id) => onOpenCase(id, "resolved")} />
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No week to report yet"
                  body={`Once cases start resolving for ${product ?? "this product"}, the week's new problems, verified fixes and regressions land here.`}
                />
              )}
            </Section>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * The header strip: how this product is doing, in one number and one sentence.
 *
 * The score is the same attention score the Portfolio ranks by — one definition,
 * so a product cannot be "on fire" on one screen and fine on another. The arrow
 * and the sparkline are labelled with what they actually measure rather than
 * being left to imply that the score itself has a history we do not keep.
 */
function ScoreStrip({
  me, weekly, onOpenCase, loading,
}: {
  me: PortfolioProduct | null;
  weekly: { week_start: string; count: number; avg_rating: number | null }[];
  onOpenCase: (id: number, status?: string) => void;
  loading: boolean;
}) {
  const BAND: Record<string, { color: string; label: string }> = {
    on_fire: { color: C.bad, label: "Needs you today" },
    attention: { color: C.accent, label: "Worth a look" },
    watch: { color: C.info, label: "Trending, not urgent" },
    healthy: { color: C.good, label: "Nothing demanding attention" },
  };

  if (loading) {
    return <div style={{ maxWidth: 940, height: 108, borderRadius: 12, background: C.card,
                         border: `1px solid ${C.border2}`, marginBottom: 26,
                         animation: "elSkeleton 1.4s infinite" }} />;
  }
  if (!me) return null;

  const band = BAND[me.band] ?? BAND.healthy;
  const delta = me.negative_rate_delta_pct;
  const ratings = weekly.map((w) => w.avg_rating).filter((r): r is number => r != null);

  return (
    <div
      style={{
        maxWidth: 940, marginBottom: 26, padding: "18px 22px", background: C.card,
        border: `1px solid ${band.color}44`, borderRadius: 12,
        display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap",
      }}
    >
      <div style={{ width: 3, alignSelf: "stretch", minHeight: 52, borderRadius: 2,
                    background: band.color, flex: "none" }} />

      <div style={{ flex: "none" }}>
        <Label style={{ letterSpacing: ".12em" }}>ECHOLENS SCORE</Label>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginTop: 6 }}>
          <span style={{ fontFamily: mono, fontSize: 38, fontWeight: 700, color: band.color,
                         lineHeight: 1 }}>
            {Math.round(me.score)}
          </span>
          {me.has_data && delta !== 0 && (
            <span
              title="Share of reviews that are negative, last 7 days vs the prior month"
              style={{ fontFamily: mono, fontSize: 12.5,
                       color: delta > 0 ? C.bad : C.good, whiteSpace: "nowrap" }}
            >
              {delta > 0 ? "▲" : "▼"} {Math.round(Math.abs(delta))} pts
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: C.muted, marginTop: 5 }}>{band.label}</div>
      </div>

      {ratings.length > 1 && (
        <div style={{ flex: "none" }}>
          <Spark points={ratings} color={C.accent} width={110} height={34}
                 title="Average star rating by week" />
          <div style={{ fontFamily: mono, fontSize: 9, color: C.faint, letterSpacing: ".06em",
                        marginTop: 2 }}>
            AVG RATING · {ratings.length} WEEKS
          </div>
        </div>
      )}

      <div style={{ flex: 1, minWidth: 260 }}>
        <div style={{ fontSize: 14.5, color: C.text2, lineHeight: 1.55 }}>
          {sentence(me)}
        </div>
        {me.top_problem && (
          <div
            onClick={() => onOpenCase(me.top_problem!.investigation_id, "resolved")}
            className="el-btn"
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                onOpenCase(me.top_problem!.investigation_id, "resolved");
              }
            }}
            style={{ display: "flex", gap: 8, alignItems: "baseline", marginTop: 8,
                     fontSize: 12.5, color: C.muted, cursor: "pointer" }}
          >
            <span style={{ fontFamily: mono, fontSize: 11, color: C.accent }}>
              case #{me.top_problem.investigation_id}
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {me.top_problem.summary}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/** One plain-English line explaining where the score came from. */
function sentence(me: PortfolioProduct): string {
  if (!me.has_data) {
    return `No feedback has been collected for ${me.product} yet — connect a source and the score starts moving.`;
  }
  if (me.score === 0) {
    return `Nothing is demanding attention on ${me.product}: no unfixed problems, no regressions, nothing awaiting triage.`;
  }
  const drivers = me.reasons.slice(0, 2).map((r) => r.text);
  const tail = drivers.length > 1 ? `${drivers[0]}, and ${drivers[1]}` : drivers[0];
  return `${me.product}: ${tail}.`;
}

function Reassurance({ running, queued, product }: {
  running: number; queued: number; product: string | null;
}) {
  const tail =
    running > 0 && queued > 0
      ? `${running} ${plural(running, "investigation")} running, ${queued} queued.`
      : running > 0
        ? `${running} ${plural(running, "investigation")} running.`
        : queued > 0
          ? `${queued} queued and waiting to run.`
          : "Nothing is running either.";
  return (
    <div style={{ maxWidth: 940, padding: "20px 22px", borderRadius: 12,
                  background: C.card, border: `1px solid rgba(76,192,119,.3)`,
                  display: "flex", alignItems: "center", gap: 13 }}>
      <span style={{ color: C.good, fontSize: 16 }}>✓</span>
      <div>
        <div style={{ fontSize: 14.5, fontWeight: 600, color: C.text2 }}>
          Nothing needs you{product ? ` on ${product}` : ""} — {tail}
        </div>
        <div style={{ fontSize: 12.5, color: C.dim, marginTop: 4 }}>
          No findings awaiting review, no stalled cases, every source reporting.
        </div>
      </div>
    </div>
  );
}

/** A non-case thing that still needs a decision — a stale source, for instance. */
function ActionRow({ title, detail, action, onAction }: {
  title: string; detail?: string | null; action: string; onAction: () => void;
}) {
  return (
    <div className="el-card" style={{ display: "flex", alignItems: "stretch", overflow: "hidden" }}>
      <div style={{ width: 3, flex: "none", background: C.accent }} />
      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 14,
                    padding: "11px 15px" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, color: C.text }}>{title}</div>
          {detail && (
            <div style={{ fontSize: 12, color: C.dim, marginTop: 4, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {detail}
            </div>
          )}
        </div>
        <button onClick={onAction} className="el-btn"
          style={{ flex: "none", background: C.accent, color: C.onAccent, border: "none",
                   borderRadius: 7, padding: "8px 14px", fontSize: 12.5, fontWeight: 600,
                   cursor: "pointer" }}>
          {action}
        </button>
      </div>
    </div>
  );
}

function Section({ title, count, color, action, children }: {
  title: string;
  count?: number;
  color?: string;
  action?: { label: string; onClick: () => void };
  children: ReactNode;
}) {
  return (
    <div style={{ marginBottom: 30 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12,
                    maxWidth: 940 }}>
        <Label style={{ color: color ?? C.faint }}>
          {title}{count != null ? ` · ${count}` : ""}
        </Label>
        <div style={{ flex: 1 }} />
        {action && (
          <span onClick={action.onClick} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") action.onClick(); }}
            style={{ fontSize: 12.5, color: C.dim, cursor: "pointer" }}>
            {action.label}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

/** Turn "…case #12…" into a link, so the brief is navigable prose. */
function Cited({ text, onOpen }: { text: string; onOpen: (id: number) => void }) {
  return (
    <>
      {text.split(/(case #\d+)/g).map((part, i) => {
        const m = part.match(/^case #(\d+)$/);
        if (!m) return <span key={i}>{part}</span>;
        return (
          <span key={i} onClick={() => onOpen(parseInt(m[1], 10))} className="el-btn"
            role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter") onOpen(parseInt(m[1], 10)); }}
            style={{ color: C.accent, cursor: "pointer", fontFamily: mono, fontSize: 12.5 }}>
            {part}
          </span>
        );
      })}
    </>
  );
}
