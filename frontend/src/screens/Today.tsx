import { ReactNode, useState } from "react";
import { CaseRow, PortfolioProduct, api, getActiveProduct, isAdmin, isGuest } from "../api";
import { CaseCard } from "../components/CaseCard";
import { withToast } from "../components/Toast";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { statusMeta } from "../status";
import { C, E, MEASURE, R, S, T, mono } from "../theme";
import { Icon } from "../components/Icon";
import {
  Button, EmptyState, ErrorState, Label, ScreenBody, ScreenHeader, Skeleton, Spark
} from "../ui";

interface Props {
  productName: string | null;
  onOpenCase: (id: number, status?: string) => void;
  onGoCases: (tab?: string) => void;
  onGoSources: () => void;
  onGoPlan: () => void;
  /** Opens the add-product overlay. Admin-only; absent for everyone else. */
  onAddProduct?: () => void;
  /** Returns a guest to the sign-in screen. */
  onSignIn?: () => void;
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
  productName, onOpenCase, onGoCases, onGoSources, onGoPlan, onAddProduct, onSignIn,
  reloadKey, bumpReload
}: Props) {
  const cases = useAsync(() => api.cases(), [reloadKey]);
  const portfolio = useAsync(() => api.portfolio(), [reloadKey]);
  const snapshot = useAsync(() => api.snapshot(), [reloadKey]);
  const sources = useAsync(() => api.sources(), [reloadKey]);
  const brief = useAsync(() => api.brief(), [reloadKey]);
  const [cancelling, setCancelling] = useState<number | null>(null);

  const rows = cases.data?.cases ?? [];
  const product = productName ?? cases.data?.product ?? null;
  // Joined on product_id, falling back to the name. Matching on the name alone
  // meant any divergence between /products' spelling and /portfolio's dropped
  // the match — and ScoreStrip returns null when it does, so the score and the
  // verdict, the most prominent things on the home screen, vanished with no
  // error and no empty state.
  const activeId = getActiveProduct();
  const me = (portfolio.data?.products ?? []).find(
    (p) => (activeId != null && p.product_id === activeId) || p.product === product,
  ) ?? null;

  const staleSources = (sources.data?.connected ?? []).filter((s) => s.stale || s.error);
  const needsYou = rows.filter((r) => statusMeta(r.status).needsYou);
  const running = rows.filter((r) => r.status === "running");
  const queued = rows.filter((r) => r.status === "queued");

  // "Open" = a real problem with no verified fix. Ranked by how bad it is, and
  // deduped against the action queue so Today never shows one case twice.
  // `id` is null for queued rows, so a null must never make it into the dedupe
  // set — one null would hide every other null-id row.
  const surfaced = new Set(needsYou.map((r) => r.id).filter((id): id is number => id != null));
  const allOpenProblems = rows
    .filter((r) => ["resolved", "needs_review", "needs_human", "regressed"].includes(r.status))
    .filter((r) => r.id == null || !surfaced.has(r.id))
    .sort((a, b) =>
      (b.severity_score ?? 0) - (a.severity_score ?? 0) ||
      (b.impact?.affected_pct ?? 0) - (a.impact?.affected_pct ?? 0));
  const OPEN_PROBLEM_LIMIT = 5;
  const openProblems = allOpenProblems.slice(0, OPEN_PROBLEM_LIMIT);
  const hiddenOpenProblems = allOpenProblems.length - openProblems.length;

  const cancelQueued = async (row: CaseRow) => {
    if (row.queue_id == null) return;
    setCancelling(row.queue_id);
    await withToast(() => api.cancelQueued(row.queue_id!), {
      success: "Removed from the queue.",
      failure: "Couldn't cancel that queued item"
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
        subtitle="What needs you right now"
        right={
          <span style={{ display: "inline-flex", alignItems: "center", gap: S[4] }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: S[2],
                           fontFamily: mono, fontSize: T.xs, color: C.muted }}>
              {running.length > 0 && (
                <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%",
                              background: C.accent, animation: "elPulse 1.6s infinite" }} />
              )}
              {running.length > 0
                ? `${running.length} ${plural(running.length, "investigation")} running`
                : "nothing running"}
            </span>
            {/* Out in the open, not buried in the product switcher's dropdown:
                adding a product is the main thing an owner comes here to do
                when the workspace is thin. */}
            {onAddProduct && isAdmin() && (
              <Button variant="ghost" size="sm" icon="plus" onClick={onAddProduct}>
                Add a product
              </Button>
            )}
          </span>
        }
      />

      <ScreenBody>
        <AccessNote onSignIn={onSignIn} />
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
              title="Needs you"
              count={needsYou.length + staleSources.length}
              color={C.accent}
              emphasis
            >
              {loading ? (
                <Skeleton rows={2} height={62} />
              ) : needsYou.length === 0 && staleSources.length === 0 ? (
                <Reassurance running={running.length} queued={queued.length} product={product} />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
                  {staleSources.map((s, i) => (
                    <ActionRow
                      key={`src-${i}-${s.name}-${s.detail}`}
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
            <Section title="Running & queued" count={running.length + queued.length}>
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
                <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
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
              title="Top open problems"
              // The TOTAL, not the truncated list. This read openProblems.length
              // AFTER slice(0,5), so 30 open problems rendered as
              // "TOP OPEN PROBLEMS · 5" — a count the user had no reason to
              // doubt and no way to correct.
              count={allOpenProblems.length}
              action={{ label: "Plan the quarter", onClick: onGoPlan }}
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
                <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
                  {openProblems.map((r) => (
                    <CaseCard key={`open-${r.id}`} row={r}
                              onOpen={(row) => row.id != null && onOpenCase(row.id, row.status)} />
                  ))}
                  {hiddenOpenProblems > 0 && (
                    <Button variant="quiet" size="sm"
                      onClick={() => onGoCases("needs-review")}
                      style={{ alignSelf: "flex-start", color: C.accent }}
                    >
                      {hiddenOpenProblems} more open{" "}
                      {hiddenOpenProblems === 1 ? "problem" : "problems"} in Cases
                      <Icon name="arrowRight" size={13} />
                    </Button>
                  )}
                </div>
              )}
            </Section>

            {/* ── d. what changed ───────────────────────────────────── */}
            <Section title="This week">
              {brief.data && brief.data.lines.length > 0 ? (
                <div style={{ maxWidth: MEASURE, padding: `${S[4]} ${S[5]}`,
                              background: C.card, border: `1px solid ${C.border2}`,
                              borderRadius: R.card,
                              display: "flex", flexDirection: "column", gap: S[2] }}>
                  <Label style={{ marginBottom: S[1] }}>{brief.data.generated}</Label>
                  {brief.data.lines.map((line, i) => (
                    <div key={i} style={{ fontSize: T.base,
                                          lineHeight: "var(--el-lh-normal)",
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
      </ScreenBody>
    </div>
  );
}

/**
 * One line explaining why "Add a product" is not on this screen.
 *
 * A control that is simply absent reads as a missing feature. A guest needs to
 * know an account unlocks it; a reviewer needs to know it is admin-only, which
 * is otherwise invisible — the button vanishes with no explanation, and the
 * only way to find out is to ask.
 */
function AccessNote({ onSignIn }: { onSignIn?: () => void }) {
  const guest = isGuest();
  // Admins have the button, so they need no explanation.
  if (isAdmin()) return null;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap",
                  maxWidth: MEASURE, marginBottom: S[5], padding: `${S[3]} ${S[4]}`,
                  background: C.bgRaised, border: `1px solid ${C.border2}`,
                  borderRadius: R.card, fontSize: T.sm, color: C.muted }}>
      <Icon name="info" size={14} style={{ color: C.info, flex: "none" }} />
      <span style={{ flex: 1, minWidth: 220 }}>
        {guest
          ? "You're exploring a demo product. Sign in to connect your own app and run investigations on it."
          : "Connecting a new product is admin-only — it attaches collectors that keep pulling, so it stays with the workspace owner. You can investigate and review everything here."}
      </span>
      {guest && onSignIn && (
        <Button variant="ghost" size="sm" onClick={onSignIn}>Sign in</Button>
      )}
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
  me, weekly, onOpenCase, loading
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
    healthy: { color: C.good, label: "Nothing demanding attention" }
  };

  if (loading) {
    return <div style={{ maxWidth: MEASURE, height: 120, borderRadius: R.card,
                         background: C.card, border: `1px solid ${C.border2}`,
                         marginBottom: S[8], animation: "elSkeleton 1.6s infinite" }} />;
  }
  if (!me) return null;

  const band = BAND[me.band] ?? BAND.healthy;
  const delta = me.negative_rate_delta_pct;
  const ratings = weekly.map((w) => w.avg_rating).filter((r): r is number => r != null);

  // This is the most important object on the home screen, so it is built to
  // read that way: raised surface, a real shadow, and a band-coloured wash
  // behind the number. Previously it was the same flat card as everything
  // below it and the eye had no reason to land here first.
  return (
    <section
      aria-label="Product score"
      style={{
        maxWidth: MEASURE, marginBottom: S[8], padding: `${S[5]} ${S[6]}`,
        background: `linear-gradient(180deg, ${C.bgRaised}, ${C.card})`,
        border: `1px solid ${C.border3}`, borderRadius: R.card,
        boxShadow: E[2], position: "relative", overflow: "hidden",
        display: "flex", alignItems: "center", gap: S[6], flexWrap: "wrap"
      }}
    >
      {/* Band colour as a top rule rather than a barely-visible border tint. */}
      <span aria-hidden style={{ position: "absolute", inset: "0 0 auto 0", height: 2,
                    background: band.color }} />

      <div style={{ flex: "none" }}>
        <Label>EchoLens score</Label>
        <div style={{ display: "flex", alignItems: "baseline", gap: S[3], marginTop: S[2] }}>
          <span className="el-num" style={{ fontSize: T.display, fontWeight: 700,
                         color: band.color, lineHeight: 1 }}>
            {Math.round(me.score)}
          </span>
          {me.has_data && delta !== 0 && (
            <span
              title="Share of reviews that are negative, last 7 days vs the prior month"
              style={{ display: "inline-flex", alignItems: "center", gap: 2,
                       fontFamily: mono, fontSize: T.sm,
                       color: delta > 0 ? C.bad : C.good, whiteSpace: "nowrap" }}
            >
              <Icon name={delta > 0 ? "arrowUp" : "arrowDown"} size={12} />
              {Math.round(Math.abs(delta))} pts
            </span>
          )}
        </div>
        <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1] }}>{band.label}</div>
      </div>

      {ratings.length > 1 && (
        <div style={{ flex: "none" }}>
          <Spark points={ratings} color={C.accent} width={110} height={34}
                 title="Average star rating by week" />
          <Label style={{ marginTop: S[1] }}>
            Avg rating · {ratings.length} weeks
          </Label>
        </div>
      )}

      <div style={{ flex: 1, minWidth: 260 }}>
        <p style={{ margin: 0, fontSize: T.md, color: C.text2,
                    lineHeight: "var(--el-lh-normal)" }}>
          {sentence(me)}
        </p>
        {me.top_problem && (
          <Button
            variant="quiet"
            size="sm"
            onClick={() => onOpenCase(me.top_problem!.investigation_id, "resolved")}
            style={{ marginTop: S[2], marginLeft: `calc(-1 * ${S[3]})`, maxWidth: "100%" }}
          >
            <span className="el-mono" style={{ fontSize: T.xs, color: C.accent }}>
              case #{me.top_problem.investigation_id}
            </span>
            <span className="el-truncate" style={{ color: C.muted }}>
              {me.top_problem.summary}
            </span>
          </Button>
        )}
      </div>
    </section>
  );
}

/** One plain-English line explaining where the score came from. */
function sentence(me: PortfolioProduct): string {
  if (!me.has_data) {
    return `No feedback has been collected for ${me.product} yet — connect a source and the score starts moving.`;
  }
  if (me.score === 0) {
    return `Nothing is demanding attention on ${me.product}: no unfixed problems, no regressions, no signals waiting on a decision.`;
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
    <div style={{ maxWidth: MEASURE, padding: `${S[5]} ${S[5]}`, borderRadius: R.card,
                  background: C.card, border: `1px solid ${C.goodLine}`,
                  display: "flex", alignItems: "center", gap: S[3] }}>
      <span style={{ color: C.good, flex: "none", display: "grid", placeItems: "center",
                     width: 26, height: 26, borderRadius: R.pill, background: C.goodBg }}>
        <Icon name="check" size={15} />
      </span>
      <div>
        <div style={{ fontSize: T.md, fontWeight: 600, color: C.text2 }}>
          Nothing needs you{product ? ` on ${product}` : ""} — {tail}
        </div>
        <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[1] }}>
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
      <span aria-hidden style={{ width: 3, flex: "none", background: C.accent }} />
      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: S[4],
                    padding: `${S[3]} ${S[4]}` }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: T.base, fontWeight: 600, color: C.text }}>{title}</div>
          {detail && (
            <div className="el-truncate" style={{ fontSize: T.sm, color: C.dim,
                          marginTop: S[1] }}>
              {detail}
            </div>
          )}
        </div>
        <Button variant="primary" size="sm" onClick={onAction} style={{ flex: "none" }}>
          {action}
        </Button>
      </div>
    </div>
  );
}

/**
 * A section heading.
 *
 * `emphasis` exists because "Needs you" and "This week" had identical visual
 * weight — one is a queue of things blocking the reader, the other is a digest.
 * Flat hierarchy on the home screen is why nothing looked prioritised.
 */
function Section({ title, count, color, action, emphasis, children }: {
  title: string;
  count?: number;
  color?: string;
  action?: { label: string; onClick: () => void };
  emphasis?: boolean;
  children: ReactNode;
}) {
  return (
    <section style={{ marginBottom: S[8] }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[3], marginBottom: S[3],
                    maxWidth: MEASURE }}>
        {emphasis ? (
          <h2 style={{ margin: 0, display: "flex", alignItems: "center", gap: S[2],
                       fontSize: T.md, fontWeight: 600, color: color ?? C.text2 }}>
            {title}
            {count != null && count > 0 && (
              <span className="el-num" style={{ fontSize: T.xs, fontWeight: 600,
                            color: C.onAccent, background: color ?? C.accent,
                            borderRadius: R.pill, padding: `1px ${S[2]}`, lineHeight: "var(--el-lh-normal)" }}>
                {count}
              </span>
            )}
          </h2>
        ) : (
          <Label style={{ color: color ?? C.faint }}>
            {title}{count != null ? ` · ${count}` : ""}
          </Label>
        )}
        <div style={{ flex: 1 }} />
        {action && (
          <Button variant="quiet" size="sm" onClick={action.onClick}>
            {action.label}
          </Button>
        )}
      </div>
      {children}
    </section>
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
          <button key={i} onClick={() => onOpen(parseInt(m[1], 10))}
            className="el-btn el-btn--sm"
            style={{ color: C.accent, fontFamily: mono, fontSize: T.sm,
                     padding: 0, display: "inline", background: "none" }}>
            {part}
          </button>
        );
      })}
    </>
  );
}
