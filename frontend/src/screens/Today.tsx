import { lazy, Suspense, useEffect, useState } from "react";
import { CaseRow, RequestPlanItem, api, canReview, getActiveProduct, isAdmin, isGuest } from "../api";
import { EmptyState, ListRow, SerifHeadline, stampFor } from "../components/casefile";
import { withToast } from "../components/Toast";
import { plural } from "../format";
import { useAsync } from "../hooks";
import { Button, ErrorState, ScreenBody, Skeleton } from "../ui";
import { FocusProblem } from "./today/FocusProblem";
import { GoodNews, openEngineering } from "./today/GoodNews";
import { CollectionNote, HealthDetails, QueuedWork, WeeklyUpdate } from "./today/TodayDetails";
import { headline, liveStep, openProblems, plainWords } from "./today/model";
import "./today/today.css";

const SpecModal = lazy(() => import("../components/SpecModal").then(m => ({ default:m.SpecModal })));

interface Props {
  productName: string | null;
  onOpenCase: (id: number, status?: string) => void;
  onGoCases: (tab?: string) => void;
  onGoSources: () => void;
  onGoPlan: () => void;
  onAddProduct?: () => void;
  onSignIn?: () => void;
  reloadKey: number;
  bumpReload: () => void;
}

/** One decision first. All sentences and measurements come from stored data. */
export function Today({ productName, onOpenCase, onGoCases, onGoSources, onGoPlan, onAddProduct,
  onSignIn, reloadKey, bumpReload }: Props) {
  const productId = getActiveProduct();
  const cases = useAsync(() => api.cases(), [productId, reloadKey]);
  const portfolio = useAsync(() => api.portfolio(), [productId, reloadKey]);
  const fixwatch = useAsync(() => api.fixwatch(), [productId, reloadKey]);
  const live = useAsync(() => api.liveInvestigations(), [productId, reloadKey]);
  const snapshot = useAsync(() => api.snapshot(), [productId, reloadKey]);
  const sources = useAsync(() => api.sources(), [productId, reloadKey]);
  const brief = useAsync(() => api.brief(), [productId, reloadKey]);
  const requests = useAsync(() => api.backlogPlan(undefined, "requests"), [productId, reloadKey]);
  const rows = cases.data?.cases ?? [];
  const watches = fixwatch.data?.watches ?? [];
  const problems = openProblems(rows, watches);
  const focus = problems[0];
  const overview = useAsync(() => api.overview(focus?.id ?? undefined), [productId, reloadKey, focus?.id]);
  const timeline = useAsync(() => api.timeline(30), [productId, reloadKey]);
  const metrics = overview.data?.focus?.investigation_id === focus?.id ? overview.data?.focus ?? null : null;
  const [spec, setSpec] = useState<RequestPlanItem | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [collecting, setCollecting] = useState(false);
  const guest = isGuest();
  const reviewer = canReview() && !guest;
  const product = productName ?? cases.data?.product ?? "Your product";
  const me = portfolio.data?.products.find(p => p.product_id === productId) ?? null;
  const hasData = me?.has_data ?? ((snapshot.data?.reviews ?? 0) > 0 || rows.length > 0);
  const stale = (sources.data?.connected ?? []).filter(s => s.stale || s.error);
  const spikes = cases.data?.incidents?.length ?? cases.data?.signals.filter(s => !s.dismissed).length ?? me?.untriaged ?? 0;
  const running = rows.filter(r => r.status === "running");
  const queued = rows.filter(r => r.status === "queued");
  const decisions = problems.filter(r => ["needs_review", "needs_human", "regressed"].includes(r.status)).length;
  const loading = cases.loading || portfolio.loading || fixwatch.loading || sources.loading || (overview.loading && !metrics);
  const requestRows = [...(requests.data?.proposed ?? []), ...(requests.data?.deferred ?? [])]
    .filter((r): r is RequestPlanItem => r.kind === "request");
  const fixes = overview.data?.confirmed_fixes ?? [];
  const also = problems.slice(1, 5);
  const extra = problems.length - 1 - also.length;
  const date = new Date();
  const greeting = date.getHours() < 12 ? "Good morning" : date.getHours() < 18 ? "Good afternoon" : "Good evening";

  // Poll only while work is active, and wait for each read to finish first.
  useEffect(() => {
    if (live.loading || live.refreshing || !(running.length + queued.length)) return;
    const timer = window.setTimeout(live.reload, 5000);
    return () => window.clearTimeout(timer);
  }, [live.data, live.loading, live.refreshing, live.reload, running.length, queued.length]);

  const cancel = async (row: CaseRow) => {
    if (row.queue_id == null) return;
    setCancelling(row.queue_id);
    const result = await withToast(() => api.cancelQueued(row.queue_id!), {
      success:"Removed from the queue.", failure:"Couldn't cancel that queued item",
    });
    setCancelling(null);
    if (result) { cases.reload(); live.reload(); bumpReload(); }
  };
  const collect = async () => {
    setCollecting(true);
    await withToast(() => api.collectorsRun(), {
      success:r => `Collected ${r.results.reduce((n, x) => n + x.inserted, 0)} new items.`,
      failure:"Couldn't collect. Check your sources and try again.",
    });
    setCollecting(false);
    sources.reload(); overview.reload(); bumpReload();
  };
  const retry = () => { cases.reload(); overview.reload(); portfolio.reload(); fixwatch.reload(); };

  return <div className="today-v2"><ScreenBody style={{ padding:"36px var(--el-gutter) 64px" }}>
    <div className="today-v2__content">
      <div className="today-intro" aria-busy={loading}>
        <div className="today-greeting">{greeting} · {product} · {date.toLocaleDateString(undefined, { weekday:"long", month:"long", day:"numeric" })} · health{" "}
          <strong>{me?.has_data ? me.health : "—"}</strong>/100
          <span title="Health is higher when fewer problems and review spikes need attention."> · higher is healthier</span></div>
        <SerifHeadline>{loading ? "Reading today's reviews…" : cases.error ? "Your problems couldn't be loaded."
          : headline({ focus, count:problems.length, drag:metrics?.rating_drag, hasData,
            spikes, stale:stale.length })}</SerifHeadline>
        <div className="today-summary">
          {loading ? "Checking investigations" : <>
            <Button variant="quiet" onClick={() => onGoCases("needs-review")}>{decisions} {plural(decisions, "decision")} waiting</Button>
            <span>{running.length} {plural(running.length, "investigation")} running{queued.length > 0 ? ` · ${queued.length} waiting to start` : ""}</span>
          </>}
        </div>
      </div>

      {cases.error ? <ErrorState title="Your problems couldn't be loaded" detail="Try again to refresh Today." onRetry={retry} />
        : loading ? <div className="today-placeholder" role="status" aria-label="Reading your problems"><Skeleton rows={4} height={54} /></div>
        : focus ? <FocusProblem row={focus} metrics={metrics} timeline={timeline.data} loading={timeline.loading}
            onOpen={() => onOpenCase(focus.id!, focus.status)}
            onTicket={reviewer && focus.finding_id != null ? () => openEngineering(focus.id!) : undefined} />
        : <EmptyState title={stale.length ? "Refresh your feedback before deciding." : spikes > 0 ? "Choose which review spikes to investigate."
            : hasData ? "Nothing needs a decision from you." : "Connect your first feedback source."}
          action={<Button variant="primary" onClick={stale.length ? onGoSources : spikes > 0 || hasData ? () => onGoCases("all") : onGoSources}>
            {stale.length ? "Review sources" : spikes > 0 ? "Review the spikes" : hasData ? "See all problems" : "Connect a source"}</Button>}>
          {stale.length ? "Some feedback is out of date. Check your sources before calling this a quiet day."
            : running.length + queued.length > 0 ? `EchoLens is working through ${running.length + queued.length} ${plural(running.length + queued.length, "investigation")}. You can follow the work below.`
            : watches.some(w => w.status === "watching") ? "EchoLens is watching the complaints after your shipped fixes. Their progress is below."
            : me?.has_data ? "EchoLens is watching connected reviews for new complaints. Any problem that needs your decision will appear here."
            : "Connect reviews so EchoLens can spot what changed and show you the proof."}
        </EmptyState>}
      {overview.error && !loading && <p className="today-muted">The latest measurements couldn't be loaded. Stored problems are still available. <Button variant="quiet" onClick={overview.reload}>Retry measurements</Button></p>}

      <div className="today-columns">
        <section className="today-section" aria-labelledby="today-also-title">
          <SerifHeadline as="h2" size="section" id="today-also-title">Also worth a look</SerifHeadline>
          <div>
            {also.map(row => <ListRow key={row.id} variant={stampFor(row)} title={plainWords(row.title)}
              detail={stampFor(row) === "hunch" ? "A hunch — needs a second source" : "Proof ready for your decision"}
              onClick={() => onOpenCase(row.id!, row.status)} />)}
            {requestRows.slice(0, 1).map(row => <ListRow key={row.slug} variant="request" title={plainWords(row.summary)}
              detail={`${row.count} requesting ${plural(row.count, "review")} · read the spec`} onClick={() => setSpec(row)} />)}
            {running.map(row => {
              const step = live.data?.investigations.find(i => i.id === row.id)?.current_step;
              return <ListRow key={row.id} variant="live" title={`Looking into: ${plainWords(row.title)}`}
                detail={<em className="today-live-step">{row.paused ? "Paused — open the problem to continue" : liveStep(step ?? null)}</em>}
                onClick={() => onOpenCase(row.id!, "running")} />;
            })}
          </div>
          {requests.loading && <p className="today-muted">Reading repeated requests…</p>}
          {requests.error && <p className="today-muted">Repeated requests couldn't be loaded. <Button variant="quiet" onClick={requests.reload}>Retry requests</Button></p>}
          {!also.length && !requestRows.length && !running.length && !requests.loading && !requests.error && <p className="today-muted">No other problems or repeated requests to show. New ones will appear as your sources update.</p>}
          {extra > 0 && <p className="today-muted">{extra} more {plural(extra, "problem")} in All problems.</p>}
          {live.error && running.length > 0 && <p className="today-muted">Live progress couldn't be refreshed. Open a problem for its stored steps.</p>}
          <div className="today-actions"><Button variant="quiet" onClick={() => onGoCases("all")}>See all problems →</Button>
            <Button variant="quiet" onClick={onGoPlan}>Plan what to fix</Button></div>
        </section>
        <section className="today-section" aria-labelledby="today-good-title">
          <SerifHeadline as="h2" size="section" id="today-good-title">Good news</SerifHeadline>
          {fixwatch.error ? <p className="today-muted">Fix checks couldn't be loaded. <Button variant="quiet" onClick={fixwatch.reload}>Try again</Button></p>
            : <GoodNews fixes={fixes} watches={watches} onOpen={onOpenCase} onReload={() => { overview.reload(); fixwatch.reload(); }} />}
        </section>
      </div>

      <div className="today-context">
        <CollectionNote freshness={overview.data?.freshness} staleCount={stale.length} collecting={collecting}
          onSources={onGoSources} onCollect={reviewer ? collect : undefined} />
        {sources.error && <div className="today-context-line"><span>Source health couldn't be checked.</span><Button variant="quiet" onClick={onGoSources}>Review sources</Button></div>}
        <WeeklyUpdate brief={brief.data} error={brief.error} onRetry={brief.reload} onOpen={id => onOpenCase(id, "resolved")} />
        <HealthDetails product={me} snapshot={snapshot.data} overview={overview.data} onOpen={id => onOpenCase(id, "resolved")} />
        <QueuedWork rows={queued} busy={cancelling} onCancel={reviewer ? cancel : undefined} onCases={() => onGoCases("queued")} />
        {guest ? <div className="today-context-line"><span>You're exploring a demo product. Sign in to connect your own app and investigate its reviews.</span>
          {onSignIn && <Button onClick={onSignIn}>Sign in</Button>}</div>
          : isAdmin() && onAddProduct ? <div className="today-context-line"><span>Ready to track another app?</span><Button onClick={onAddProduct}>Add a product</Button></div>
          : <p className="today-muted">Your workspace admin can connect another product.</p>}
      </div>
    </div>
    {spec && <Suspense fallback={<p role="status">Opening the request…</p>}><SpecModal slug={spec.slug} title={spec.summary} onClose={() => setSpec(null)} /></Suspense>}
  </ScreenBody></div>;
}
