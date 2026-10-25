import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  CASE_VIEW_FILTERS, CaseRow, CaseViewParams, Incident, SavedView, SignalRow, SpikeCategory, ThemeCandidate,
  api, canReview, errorMessage, isGuest,
} from "../api";
import { withToast } from "../components/Toast";
import { money, plural } from "../format";
import { useAsync } from "../hooks";
import { SEVERITY } from "../status";
import { C, R, S, T } from "../theme";
import { Button, ErrorState, Skeleton } from "../ui";
import { Icon } from "../components/Icon";
import { EmptyState, ListRow, PillTabs, SerifHeadline } from "../components/casefile";
import {
  CATEGORY_GROUPS, LEGACY_TABS, PROBLEM_TABS, ProblemSort, ProblemTab, SORTS, detailLine, headline,
  inTab, needsDecision, sortRows, verdictOf,
} from "./cases/problems";
import {
  IncidentRow, MutedTopics, OverrideBody, SpikeRow, ThemeMenu, ThemeRow, strengthOf, typeLabel,
} from "./cases/SpikeRows";
import "./cases/cases.css";

interface Props {
  productName: string | null;
  productId?: number | null;
  params: Record<string, string>;
  setParams: (next: Record<string, string | null>) => void;
  onOpenCase: (id: number, status?: string) => void;
  onNewCase: () => void;
  reloadKey: number;
  bumpReload: () => void;
}

const RANGES: { key: string; label: string; days: number | null }[] = [
  { key: "", label: "Any time", days: null },
  { key: "7", label: "Last 7 days", days: 7 },
  { key: "30", label: "Last 30 days", days: 30 },
  { key: "90", label: "Last 90 days", days: 90 },
];

const SEV_RANK: Record<string, number> = { strong: 3, medium: 2, weak: 1 };
const GROUP_KEYS = new Set<string>(CATEGORY_GROUPS.map((g) => g.id));

/** One untriaged item in New spikes: an incident, a lone spike, or a theme. */
type Item =
  | { kind: "incident"; key: string; z: number; category: SpikeCategory; incident: Incident }
  | { kind: "signal"; key: string; z: number; category: SpikeCategory; signal: SignalRow }
  | { kind: "theme"; key: string; z: number; category: SpikeCategory; theme: ThemeCandidate }
  | { kind: "request"; key: string; z: number; category: SpikeCategory; theme: ThemeCandidate };

/**
 * Problems — every problem, by verdict, and the new spikes waiting for a call.
 *
 * Opens with a serif answer ("3 problems need a decision · 2 new spikes to look
 * at"), then the problems as case-file rows (verdict stamp · title · one muted
 * line), then New spikes grouped by what they are about. Filters, tabs and sort
 * live in the URL so a view is a link you can send.
 */
export function Cases({
  productName, productId = null, params, setParams, onOpenCase, onNewCase, reloadKey, bumpReload,
}: Props) {
  // Order matters to the render checks in scripts/: cases first, then themes.
  const view = useAsync(() => api.cases(), [reloadKey]);
  const candidates = useAsync(() => api.feedCandidates(), [reloadKey]);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [runningNow, setRunningNow] = useState<number | null>(null);
  const [moreOpen, setMoreOpen] = useState(!!(params.sev || params.range));
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  // Local mirror of the search box: writing the URL on every keystroke hit
  // Safari's replaceState limit and blanked the screen mid-search.
  const [search, setSearch] = useState(params.q ?? "");
  useEffect(() => setSearch(params.q ?? ""), [params.q]);
  useEffect(() => {
    const t = setTimeout(() => { if ((params.q ?? "") !== search) setParams({ q: search || null }); }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Arriving from onboarding's "Review N spikes": bring New spikes into view once.
  const spikesRef = useRef<HTMLElement | null>(null);
  const scrolled = useRef(false);
  useEffect(() => {
    if (scrolled.current || params.signals !== "1" || !view.data) return;
    scrolled.current = true;
    requestAnimationFrame(() => spikesRef.current?.scrollIntoView({ block: "start" }));
  }, [params.signals, view.data]);

  const reviewer = canReview();
  const legacy = LEGACY_TABS[params.tab ?? ""] ?? null;
  const tab: ProblemTab = PROBLEM_TABS.some((t) => t.id === params.tab) ? params.tab as ProblemTab : "all";
  const sort: ProblemSort = SORTS.some((s) => s.id === params.sort) ? params.sort as ProblemSort : "important";
  const sev = params.sev ?? "";
  const source = params.source ?? "";
  const range = params.range ?? "";
  const q = params.q ?? "";
  const intent = GROUP_KEYS.has(params.intent ?? "") ? params.intent as SpikeCategory : "";

  const all = view.data?.cases ?? [];
  const product = productName ?? view.data?.product ?? null;
  const open = all.filter((c) => c.status !== "dismissed");
  const dismissedCases = all.filter((c) => c.status === "dismissed");
  const sources = useMemo(() => Array.from(new Set(all.map((c) => c.source).filter(Boolean))).sort(), [all]);

  const rows = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? null;
    const needle = q.trim().toLowerCase();
    const base = legacy ? all.filter((c) => legacy.statuses.includes(c.status)) : open.filter((c) => inTab(c, tab));
    return sortRows(base.filter((c) => {
      if (sev && c.severity !== sev) return false;
      if (source && c.source !== source) return false;
      if (days != null && (c.age_days == null || c.age_days > days)) return false;
      if (needle && !`${c.title} ${c.why} #${c.id ?? ""}`.toLowerCase().includes(needle)) return false;
      return true;
    }), sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, tab, legacy, sev, source, range, q, sort]);
  const filtered = !!(sev || source || range || q);
  const tabCount = (t: ProblemTab) => open.filter((c) => inTab(c, t)).length;

  // ── New spikes ──
  const signals = view.data?.signals ?? [];
  const incidents = view.data?.incidents ?? [];
  const inIncident = new Set(incidents.flatMap((i) => i.members));
  const bySlug = new Map(signals.map((s) => [s.slug, s]));
  const live = signals.filter((s) => !s.dismissed);
  const lone = live.filter((s) => !inIncident.has(s.slug));
  const dismissedSpikes = signals.filter((s) => s.dismissed);
  const allThemes = candidates.data?.candidates ?? [];
  const themes = allThemes.filter((c) => !c.existing);
  const takenThemes = allThemes.filter((c) => c.existing);
  const requests = candidates.data?.requests ?? [];
  const items: Item[] = [
    ...incidents.map((incident) => ({ kind: "incident" as const, key: incident.lead, z: incident.z,
      category: incident.category ?? "bug", incident })),
    ...lone.map((signal) => ({ kind: "signal" as const, key: signal.slug, z: signal.z,
      category: signal.category ?? "bug", signal })),
    ...themes.map((theme) => ({ kind: "theme" as const, key: theme.slug, z: -1,
      category: theme.category ?? "bug", theme })),
    ...requests.map((theme) => ({ kind: "request" as const, key: theme.slug, z: -2,
      category: "feature_request" as const, theme })),
  ];
  const rank = (i: Item) => i.kind === "incident" ? SEV_RANK[strengthOf(i.incident)]
    : i.kind === "signal" ? SEV_RANK[strengthOf(i.signal)] : 0;
  items.sort((a, b) => rank(b) - rank(a) || b.z - a.z);
  const spikeCount = incidents.length + lone.length;
  const selectable = spikeCount + themes.length;
  const groups = CATEGORY_GROUPS.filter((g) => !intent || g.id === intent)
    .map((g) => ({ ...g, items: items.filter((i) => i.category === g.id) }))
    .filter((g) => g.items.length > 0);

  // ── selection & actions ──
  const selectedSlugs = Object.keys(selected);
  const selectedCount = selectedSlugs.length;
  const themeSlugs = new Set(themes.map((t) => t.slug));
  const spikeSelection = selectedSlugs.filter((s) => !themeSlugs.has(s));
  // An incident is picked by its lead; merging or dismissing it covers every member.
  const expand = (slugs: string[]) => slugs.flatMap((s) => incidents.find((i) => i.lead === s)?.members ?? [s]);
  const toggle = (slug: string, statement: string) => setSelected((cur) => {
    const next = { ...cur };
    if (next[slug]) delete next[slug]; else next[slug] = statement;
    return next;
  });

  const lookInto = async (picks: Record<string, string>) => {
    const slugs = Object.keys(picks);
    if (slugs.length === 0) return;
    setBusy(slugs.length === 1 ? slugs[0] : "queue");
    const result = await withToast(() => api.queueThemes(slugs, picks), {
      success: (r) => r.summary || `${slugs.length} queued.`,
      failure: "Couldn't start looking into those",
    });
    setBusy(null);
    if (result) {
      setSelected({});
      bumpReload();
      if (params.tab) setParams({ tab: null });
    }
  };
  const merge = async () => {
    setBusy("merge");
    const result = await withToast(() => api.mergeSpikes(expand(spikeSelection)), {
      success: (r) => r.summary, failure: "Couldn't merge those",
    });
    setBusy(null);
    if (result) { setSelected({}); bumpReload(); }
  };
  const dismiss = async (e: FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) return;
    setBusy("dismiss");
    const result = await withToast(() => api.dismissSpikes(expand(spikeSelection), reason.trim()), {
      success: (r) => r.summary, failure: "Couldn't dismiss those",
    });
    setBusy(null);
    if (result) { setSelected({}); setDismissing(false); setReason(""); bumpReload(); }
  };
  const run = async (label: string, fn: () => Promise<unknown>, success: string) => {
    setBusy(label);
    await withToast(fn, { success, failure: `${label} didn't work` });
    setBusy(null);
    bumpReload();
  };
  // "Investigate now anyway": one deferred item, past today's limit.
  const runNow = async (row: CaseRow) => {
    if (row.queue_id == null) return;
    setRunningNow(row.queue_id);
    const result = await withToast(() => api.runQueuedNow(row.queue_id!), {
      success: "Started now, outside today's limit.", failure: "Couldn't start that one",
    });
    setRunningNow(null);
    bumpReload();
    if (result?.investigation_id) onOpenCase(result.investigation_id, "running");
  };
  const cancelQueued = async (row: CaseRow) => {
    if (row.queue_id == null) return;
    setCancelling(row.queue_id);
    await withToast(() => api.cancelQueued(row.queue_id!), {
      success: "Taken off the list.", failure: "Couldn't cancel that",
    });
    setCancelling(null);
    bumpReload();
  };
  const editTheme = async (body: OverrideBody, success: string) => {
    await withToast(() => api.setThemeOverride(body), { success, failure: "Couldn't save that change" });
    candidates.reload();
    view.reload();
  };

  const decide = open.filter(needsDecision).length;
  const fixed = open.filter((c) => verdictOf(c) === "fixWorked").length;

  const row = (r: CaseRow) => (
    <ListRowWithExtra key={r.id != null ? `c-${r.id}` : `q-${r.queue_id}`} row={r} reviewer={reviewer}
      busy={(r.queue_id != null && cancelling === r.queue_id) || runningNow === r.queue_id}
      onOpen={() => r.id != null && onOpenCase(r.id, r.status)}
      onCancel={() => cancelQueued(r)} onRunNow={() => runNow(r)} />
  );

  return (
    <div className="pr-screen">
      <main className="pr-main">
        <header className="pr-head">
          <div className="pr-head__meta">
            <span>{product ?? "This product"} · <b>{open.length}</b> {plural(open.length, "problem")}
              {fixed > 0 && <> · {fixed} fixed</>}</span>
            <span className="pr-head__spacer" />
            {reviewer && <Button variant="ghost" size="sm" icon="plus" onClick={onNewCase}>New problem</Button>}
          </div>
          <SerifHeadline as="h1" size="page">
            {view.data ? headline(decide, spikeCount, open.length) : "Problems"}
          </SerifHeadline>
        </header>

        {/* tabs, source, search, sort — every value is in the URL */}
        <div style={{ display: "flex", flexDirection: "column", gap: S[3] }}>
          <div className="pr-toolbar">
            <PillTabs label="Problems by verdict" panelId="pr-problems" value={legacy ? "all" : tab}
              tabs={PROBLEM_TABS.map((t) => ({ id: t.id, label: view.data && t.id !== "all"
                ? `${t.label} ${tabCount(t.id)}` : t.label }))}
              onChange={(t) => setParams({ tab: t === "all" ? null : t })} />
            <span className="pr-toolbar__spacer" />
            <select className="pr-select" aria-label="Where it came from" value={source}
              onChange={(e) => setParams({ source: e.target.value || null })}>
              <option value="">Any source</option>
              {sources.map((s) => <option key={s} value={s}>{typeLabel(s)}</option>)}
            </select>
            <input className="pr-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search problems…" aria-label="Search problems" />
          </div>
          <div className="pr-toolbar">
            <SavedViewsBar key={productId ?? "none"} productId={productId} params={{ ...params, q: search }}
              onApply={(next) => { setSearch(next.q ?? ""); setParams(next); }} />
            <span className="pr-toolbar__spacer" />
            <select className="pr-select" aria-label="Sort" value={sort}
              onChange={(e) => setParams({ sort: e.target.value === "important" ? null : e.target.value })}>
              {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <button type="button" className="pr-more" aria-expanded={moreOpen} onClick={() => setMoreOpen((o) => !o)}>
              {moreOpen ? "Fewer filters" : "More filters"}
            </button>
          </div>
          {moreOpen && (
            <div className="pr-filters-extra">
              <select className="pr-select" aria-label="Severity" value={sev}
                onChange={(e) => setParams({ sev: e.target.value || null })}>
                <option value="">Any severity</option>
                {Object.entries(SEVERITY).map(([k, m]) => (
                  <option key={k} value={k}>{k === "unknown" ? "Impact unknown" : `${m.label} severity`}</option>))}
              </select>
              <select className="pr-select" aria-label="Time range" value={range}
                onChange={(e) => setParams({ range: e.target.value || null })}>
                {RANGES.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
              </select>
            </div>
          )}
          {legacy && (
            <span className="pr-chip">Showing: {legacy.label}
              <button type="button" onClick={() => setParams({ tab: null })}>Show all</button></span>
          )}
        </div>

        <section id="pr-problems" role="tabpanel" aria-label="Problems" className="pr-section">
          {view.error ? (
            <ErrorState onRetry={view.reload} />
          ) : view.loading && !view.data ? (
            <Skeleton rows={4} />
          ) : rows.length === 0 ? (
            <EmptyState title={filtered ? "Nothing matches those filters." : emptyTitle(tab, product)}
              action={filtered ? (
                <Button onClick={() => { setSearch(""); setParams({ sev: null, source: null, range: null, q: null }); }}>
                  Clear filters</Button>
              ) : spikeCount > 0 ? (
                <Button onClick={() => spikesRef.current?.scrollIntoView({ block: "start" })}>See the new spikes</Button>
              ) : undefined}>
              {filtered ? "Widen the filters, or clear them to see every problem." : emptyBody(tab, spikeCount)}
            </EmptyState>
          ) : (
            <div className="pr-list">{rows.map(row)}</div>
          )}
          {!legacy && tab === "all" && dismissedCases.length > 0 && (
            <details className="pr-disclosure" style={{ marginTop: S[3] }}>
              <summary>{dismissedCases.length} dismissed {plural(dismissedCases.length, "problem")}</summary>
              <div className="pr-list">{dismissedCases.map(row)}</div>
            </details>
          )}
        </section>

        {/* ── New spikes: noticed, not yet a problem ── */}
        <section ref={spikesRef} className="pr-section" aria-labelledby="pr-spikes-title" style={{ scrollMarginTop: 16 }}>
          <div className="pr-section__head">
            <SerifHeadline as="h2" size="section" id="pr-spikes-title">New spikes</SerifHeadline>
            <span style={{ fontSize: T.sm, color: C.muted }}>{items.length} waiting</span>
            <span className="pr-head__spacer" />
            <select className="pr-select" aria-label="Kind of spike" value={intent}
              onChange={(e) => setParams({ intent: e.target.value || null })}>
              <option value="">Every kind</option>
              {CATEGORY_GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
            </select>
            {reviewer && (
              <>
                <Button variant="ghost" size="sm" disabled={!!busy} loading={busy === "Scan"}
                  title="Look for new spikes in the latest reviews and issues"
                  onClick={() => run("Scan", () => api.scan(), "Scan finished — anything new is listed below.")}>
                  Scan now</Button>
                <Button variant="ghost" size="sm" disabled={!!busy} loading={busy === "Triage"}
                  title="Let EchoLens pick which spikes are worth looking into (triage)"
                  onClick={() => run("Triage", () => api.triage(true), "Done — the spikes worth it are being looked into.")}>
                  Pick for me</Button>
              </>
            )}
          </div>
          <p className="pr-section__note">
            Things EchoLens noticed but hasn't looked into. Tick what's worth it and look into them together —
            they run one at a time, inside today's limit.
          </p>

          {groups.length === 0 && takenThemes.length === 0 && dismissedSpikes.length === 0 && (
            <EmptyState title="No new spikes.">
              Everything EchoLens noticed is already a problem, being looked into, or dismissed. Scan to look again.
            </EmptyState>
          )}

          {groups.map((g) => (
            <div key={g.id} className="pr-group" role="group" aria-label={g.label}>
              <h3 className="pr-group__title" title={g.empty}>{g.label} <span>{g.items.length}</span></h3>
              {g.items.map((i) => {
                if (i.kind === "incident") {
                  const inc = i.incident;
                  return <IncidentRow key={i.key} incident={inc}
                    members={inc.members.map((m) => bySlug.get(m)).filter((m): m is SignalRow => !!m)}
                    selected={!!selected[inc.lead]} onToggle={() => toggle(inc.lead, inc.title)}
                    busy={busy === inc.lead}
                    onLook={reviewer ? () => lookInto({ [inc.lead]: inc.title }) : undefined} />;
                }
                if (i.kind === "signal") {
                  const s = i.signal;
                  return <SpikeRow key={i.key} signal={s} selected={!!selected[s.slug]}
                    onToggle={() => toggle(s.slug, s.title)} busy={busy === s.slug}
                    onLook={reviewer ? () => lookInto({ [s.slug]: s.title }) : undefined} />;
                }
                const t = i.theme;
                if (i.kind === "request") {
                  return <ThemeRow key={i.key} theme={t} request
                    menu={reviewer ? <ThemeMenu theme={t} others={requests} onEdit={editTheme} /> : undefined} />;
                }
                return <ThemeRow key={i.key} theme={t} selected={!!selected[t.slug]}
                  onToggle={() => toggle(t.slug, t.statement)} busy={busy === t.slug}
                  onLook={reviewer ? () => lookInto({ [t.slug]: t.statement }) : undefined}
                  menu={reviewer ? <ThemeMenu theme={t} others={allThemes} onEdit={editTheme} /> : undefined} />;
              })}
            </div>
          ))}

          {takenThemes.length > 0 && (
            <p className="pr-section__note" style={{ marginTop: S[3] }}>
              {takenThemes.length} more {plural(takenThemes.length, "complaint is", "complaints are")} already
              being looked into — {takenThemes.length === 1 ? "it is" : "they are"} in the problems above.
            </p>
          )}
          {(candidates.data?.muted ?? 0) > 0 && (
            <MutedTopics count={candidates.data?.muted ?? 0} reviewer={reviewer}
              load={async () => (await api.themeOverrides()).overrides}
              onUnmute={(slug) => editTheme({ slug, action: "unmute" }, "Unmuted — it shows again.")} />
          )}
          {dismissedSpikes.length > 0 && (
            <details className="pr-disclosure">
              <summary>{dismissedSpikes.length} dismissed {plural(dismissedSpikes.length, "spike")}</summary>
              <div className="pr-dismissed">
                {dismissedSpikes.map((s) => (
                  <div key={s.slug} className="pr-dismissed__row">
                    <span className="pr-dismissed__title">{s.title}</span>
                    <span className="pr-dismissed__why" title={s.dismissed_reason ?? undefined}>
                      {s.dismissed_why ?? s.dismissed_reason ?? "Dismissed"}
                    </span>
                  </div>
                ))}
              </div>
            </details>
          )}
        </section>

        {/* one decision for any number of picks */}
        {reviewer && selectedCount > 0 && (
          <div className="pr-batch" role="group" aria-label="Selected spikes">
            <span className="pr-batch__count" role="status" aria-live="polite">
              <strong>{selectedCount}</strong> selected
            </span>
            <span className="pr-batch__note">
              {view.data?.daily_limit != null
                ? `Up to ${view.data.daily_limit} a day — the rest wait for tomorrow`
                : "Runs one at a time, inside today's limit"}
            </span>
            <span className="pr-batch__spacer" />
            <Button variant="quiet" size="sm" onClick={() => { setSelected({}); setDismissing(false); }}>Clear</Button>
            <Button size="sm" disabled={!!busy || spikeSelection.length === 0}
              title={spikeSelection.length === 0 ? "Recurring complaints are muted from their ⋯ menu instead" : undefined}
              onClick={() => setDismissing((d) => !d)} aria-expanded={dismissing}>Dismiss…</Button>
            <Button size="sm" disabled={!!busy || spikeSelection.length < 2} loading={busy === "merge"}
              title={spikeSelection.length < 2 ? "Pick two or more spikes to merge" : undefined}
              onClick={merge}>Merge into one problem</Button>
            <Button variant="primary" size="sm" loading={busy === "queue"} disabled={!!busy}
              onClick={() => lookInto(selected)}>Look into {selectedCount === 1 ? "it" : "these"}</Button>
            {dismissing && (
              <form onSubmit={dismiss}>
                <input className="pr-input" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus
                  maxLength={300} placeholder="Why? e.g. a known issue we already track"
                  aria-label="Reason for dismissing" />
                <Button type="submit" variant="primary" size="sm" disabled={!reason.trim()} loading={busy === "dismiss"}>
                  Dismiss {spikeSelection.length} {plural(spikeSelection.length, "spike")}
                </Button>
              </form>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

/** A problem row, plus the one line of actions a queued row needs. */
function ListRowWithExtra({ row, reviewer, busy, onOpen, onCancel, onRunNow }: {
  row: CaseRow; reviewer: boolean; busy: boolean; onOpen: () => void; onCancel: () => void; onRunNow: () => void;
}) {
  const est = row.estimate;
  return (
    <>
      <ListRow variant={verdictOf(row)} title={row.title} detail={detailLine(row)} onClick={onOpen} />
      {row.status === "queued" && reviewer && (
        <div className="pr-extra">
          {row.deferred && est && (
            <span className="pr-extra__est" title="An estimate, not a quote — real cost depends on how much proof it needs.">
              {est.basis === "median" ? `about ${money(est.usd)}` : `up to ${money(est.usd)}`}
            </span>
          )}
          {row.deferred && (
            <Button size="sm" variant="ghost" loading={busy} onClick={onRunNow}>Look into it now anyway</Button>
          )}
          <Button size="sm" variant="quiet" disabled={busy} onClick={onCancel}>Cancel</Button>
        </div>
      )}
    </>
  );
}

function emptyTitle(tab: ProblemTab, product: string | null): string {
  const name = product ?? "this product";
  switch (tab) {
    case "confirmed": return "Nothing is confirmed yet.";
    case "hunches": return "No hunches waiting.";
    case "requests": return "No requests turned into problems.";
    case "watching": return "No fix is being watched.";
    case "fixed": return "No confirmed fixes yet.";
    default: return `No problems yet for ${name}.`;
  }
}

function emptyBody(tab: ProblemTab, spikes: number): string {
  switch (tab) {
    case "confirmed": return "A problem is confirmed once two independent kinds of source agree on the cause.";
    case "hunches": return "Hunches are problems with only one kind of proof so far. None are waiting.";
    case "requests": return "What users ask for is listed under New spikes → Requests.";
    case "watching": return "After you send a problem to GitHub and the fix ships, EchoLens watches the reviews here.";
    case "fixed": return "A fix lands here when the reviews show the complaints stopped.";
    default: return spikes > 0
      ? `EchoLens noticed ${spikes} new ${plural(spikes, "spike")}. Pick what's worth looking into below.`
      : "Problems start from a spike EchoLens notices, a recurring complaint, or one you open yourself.";
  }
}

/** Personal filter presets. Applying one clears every filter it did not save. */
export function SavedViewsBar({ productId, params, onApply }: {
  productId: number | null;
  params: Record<string, string>;
  onApply: (params: Record<string, string | null>) => void;
}) {
  const views = useAsync(() => api.savedViews(productId), [productId]);
  const [editing, setEditing] = useState<SavedView | null | undefined>(undefined);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  if (productId == null) return null;
  const guest = isGuest(), canManage = guest || canReview();
  const rows = views.data?.views ?? [];
  const current: CaseViewParams = {};
  for (const key of CASE_VIEW_FILTERS) if (params[key]) current[key] = params[key];
  const begin = (view: SavedView | null) => {
    setEditing(view); setName(view?.name ?? ""); setError(null);
  };
  const mutate = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError(null);
    try {
      await operation();
      if (!alive.current) return;
      setEditing(undefined);
      views.reload();
    } catch (e) {
      if (alive.current) setError(errorMessage(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  };
  return (
    <div className="el-ui-forms-saved-views" aria-label="Saved views" style={{ display: "flex", flexDirection: "column", gap: S[2], minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
        {rows.map((view) => {
          const active = CASE_VIEW_FILTERS.every(k => (view.params[k] ?? "") === (current[k] ?? ""));
          return (
            <div key={view.id} style={{ display: "inline-flex", alignItems: "center", borderRadius: R.pill,
              border: `1px solid ${active ? C.ink : C.line}`, background: active ? C.soft : C.paper }}>
              <button className="el-btn el-btn--sm" aria-pressed={active} title={view.name}
                disabled={busy} onClick={() => onApply(Object.fromEntries(
                  CASE_VIEW_FILTERS.map(k => [k, view.params[k] || null])))}
                style={{ color: C.ink, padding: `${S[1]} ${S[3]}`, maxWidth: 180 }}>
                <span className="el-truncate">{view.name}</span>
              </button>
              {canManage && <>
                <button className="el-btn el-btn--sm" aria-label={`Rename ${view.name}`} disabled={busy}
                  onClick={() => begin(view)} style={{ color: C.muted, fontSize: T.micro }}>Rename</button>
                <button className="el-btn el-btn--sm" aria-label={`Delete ${view.name}`} disabled={busy}
                  onClick={() => mutate(() => api.deleteSavedView(view.id, productId))} style={{ color: C.muted }}>
                  <Icon name="close" size={12} />
                </button>
              </>}
            </div>
          );
        })}
        {canManage && <button className="el-btn el-btn--ghost el-btn--sm" onClick={() => begin(null)}
          disabled={busy || views.loading || !!views.error || rows.length >= 20}
          title={rows.length >= 20 ? "You can save up to 20 views per product" : "Save these filters as a view"}>
          Save view
        </button>}
        <span style={{ fontSize: T.xs, color: C.muted }}>
          {guest ? "Saved on this browser" : !canManage ? "Reviewer access required to save views" :
            `${rows.length} saved ${plural(rows.length, "view")}`}
        </span>
      </div>
      {editing !== undefined && <form onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim() || busy) return;
        return mutate(() => editing
          ? api.updateSavedView(editing.id, name, editing.params, productId)
          : api.createSavedView(name, current, productId));
      }} style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
        <input aria-label="View name" placeholder="Name this view" value={name} maxLength={80} required autoFocus
          disabled={busy} onChange={(e) => setName(e.target.value)} className="pr-input" style={{ width: 220 }} />
        <button className="el-btn el-btn--primary el-btn--sm" type="submit" disabled={busy || !name.trim()}>
          {busy ? "Saving..." : editing ? "Rename view" : "Save"}
        </button>
        <button className="el-btn el-btn--ghost el-btn--sm" type="button" disabled={busy}
          onClick={() => { setEditing(undefined); setError(null); }}>Cancel</button>
      </form>}
      {views.error && <div role="alert" style={{ fontSize: T.sm, color: C.ink }}>
        Couldn't load saved views. <button className="el-btn el-btn--sm" onClick={views.reload}>Retry</button>
      </div>}
      {error && <div role="alert" style={{ fontSize: T.sm, color: C.ink }}>{error}</div>}
    </div>
  );
}
