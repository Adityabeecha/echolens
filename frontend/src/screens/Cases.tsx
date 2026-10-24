import { useEffect, useMemo, useRef, useState } from "react";
import {
  CASE_VIEW_FILTERS, CaseRow, CaseViewParams, Incident, IntentCounts, SavedView, SignalRow,
  ThemeCandidate, ThemeOverride, api, canReview, errorMessage, isGuest,
} from "../api";
import { CaseCard } from "../components/CaseCard";
import { withToast } from "../components/Toast";
import { money, plural, when } from "../format";
import { useAsync } from "../hooks";
import { CASE_TABS, SEVERITY } from "../status";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { EmptyState, ErrorState, Label, ScreenHeader, Skeleton } from "../ui";
import { Icon } from "../components/Icon";

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

const SOURCE_LABEL: Record<string, string> = {
  manual: "Opened by you",
  manual_theme: "Theme you picked",
  anomaly: "Detected spike",
  theme_volume_surge: "Rising theme",
  negative_review_spike: "1-star spike",
  rating_drop: "Rating drop",
  issue_velocity_surge: "GitHub issues",
  regression: "Regression",
  fix_regression: "Regression",
  challenge: "Re-opened by challenge",
};

const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s.replace(/_/g, " ");

/**
 * Cases — the whole lifecycle in one list.
 *
 * This replaces the Case Feed and the Archive, which were the same cases split
 * by whether they had finished: you had to know which of two screens a case had
 * moved to before you could look for it. Filter tabs do that job now, and they
 * live in the URL so a filtered view is a link you can send someone.
 *
 * Signals — things EchoLens noticed but is not yet accountable for — sit in a
 * collapsed section at the bottom rather than competing with real cases at the
 * top, which is what made the old feed unreadable.
 */
export function Cases({
  productName, productId = null, params, setParams, onOpenCase, onNewCase, reloadKey, bumpReload,
}: Props) {
  const view = useAsync(() => api.cases(), [reloadKey]);
  const candidates = useAsync(() => api.feedCandidates(), [reloadKey]);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [runningNow, setRunningNow] = useState<number | null>(null);
  const [signalsOpen, setSignalsOpen] = useState(params.signals === "1");
  // Local mirror of the search box. Writing straight to the URL on every
  // keystroke called history.replaceState 20 times for a 20-character query;
  // Safari throws SecurityError past ~100 calls / 30s, uncaught, which tripped
  // the ErrorBoundary and blanked the screen mid-search.
  const [search, setSearch] = useState(params.q ?? "");
  useEffect(() => setSearch(params.q ?? ""), [params.q]);
  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.q ?? "") !== search) setParams({ q: search || null });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  // Arriving from onboarding's "Review N signals in Cases". Those signals are
  // not cases yet, so the case list above is empty and the Signals section sits
  // below a full-height empty state — off screen, which reads as "nothing is
  // here". Bring it into view once, after the data lands.
  const signalsRef = useRef<HTMLDivElement | null>(null);
  const scrolledToSignals = useRef(false);
  useEffect(() => {
    if (scrolledToSignals.current || params.signals !== "1" || !view.data) return;
    if ((view.data.signals ?? []).length === 0) return;
    scrolledToSignals.current = true;
    requestAnimationFrame(() =>
      signalsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, [params.signals, view.data]);

  const reviewer = canReview();

  const tab = params.tab ?? "all";
  const sev = params.sev ?? "";
  const source = params.source ?? "";
  const range = params.range ?? "";
  const q = params.q ?? "";

  const all = view.data?.cases ?? [];
  const product = productName ?? view.data?.product ?? null;

  const sources = useMemo(
    () => Array.from(new Set(all.map((c) => c.source).filter(Boolean))).sort(),
    [all],
  );

  const rows = useMemo(() => {
    const statuses = CASE_TABS.find((t) => t.key === tab)?.statuses ?? null;
    const days = RANGES.find((r) => r.key === range)?.days ?? null;
    const needle = q.trim().toLowerCase();
    return all.filter((c) => {
      if (statuses && !(statuses as string[]).includes(c.status)) return false;
      if (sev && c.severity !== sev) return false;
      if (source && c.source !== source) return false;
      if (days != null && (c.age_days == null || c.age_days > days)) return false;
      if (needle && !`${c.title} ${c.why} #${c.id ?? ""}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [all, tab, sev, source, range, q]);

  const filtered = !!(sev || source || range || q);
  const counts = view.data?.counts ?? {};

  // Signals and themes are the same decision — "is this worth a case?" — so they
  // share one selection and one commit, instead of two lists with two buttons.
  const signals = view.data?.signals ?? [];
  const SEV_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };
  const liveSignals = signals.filter((s) => !s.dismissed);
  const dismissedSignals = signals.filter((s) => s.dismissed);
  const allThemes = candidates.data?.candidates ?? [];
  const themes = allThemes.filter((c) => !c.existing);
  const takenThemes = allThemes.filter((c) => c.existing);
  const requests = candidates.data?.requests ?? [];

  // Related signals (same window, same theme or both product-wide) arrive
  // grouped as incidents. An incident is ONE row here; its members are shown
  // inside it rather than again as separate rows.
  const incidents = view.data?.incidents ?? [];
  const inIncident = new Set(incidents.flatMap((i) => i.members));
  const bySlug = new Map(signals.map((s) => [s.slug, s]));
  const loneSignals = liveSignals.filter((s) => !inIncident.has(s.slug));

  // What the reviews behind each card are FOR. The filter keeps a card when the
  // chosen intent leads it or makes up at least a quarter of it.
  const intent = (params.intent ?? "") as IntentFilter;
  const showIntent = (c?: IntentCounts | null) => intentMatches(c, intent);
  const visIncidents = incidents.filter((i) => showIntent(i.intents));
  const visSignals = loneSignals.filter((s) => showIntent(s.intents));
  // One ordering across both shapes, using the incident lead's strongest z.
  const detected = [
    ...visIncidents.map((incident) => ({ z: incident.z, incident, signal: null })),
    ...visSignals.map((signal) => ({ z: signal.z, signal, incident: null })),
  ].sort((a, b) =>
    SEV_RANK[signalSeverity(b)] - SEV_RANK[signalSeverity(a)] || b.z - a.z);
  const visThemes = themes.filter((t) => showIntent(t.intents));
  const visRequests = requests.filter((t) => showIntent(t.intents));
  const hiddenByIntent = intent
    ? (incidents.length + loneSignals.length + themes.length + requests.length)
      - (visIncidents.length + visSignals.length + visThemes.length + visRequests.length)
    : 0;

  const selectable = incidents.length + loneSignals.length + themes.length;
  const selectedCount = Object.keys(selected).length;

  const toggle = (slug: string, statement: string) =>
    setSelected((s) => {
      const next = { ...s };
      if (next[slug]) delete next[slug];
      else next[slug] = statement;
      return next;
    });

  const investigateSelected = async () => {
    if (selectedCount === 0) return;
    setBusy("queue");
    const slugs = Object.keys(selected);
    const result = await withToast(() => api.queueThemes(slugs, selected), {
      success: (r) => r.summary || `${slugs.length} ${plural(slugs.length, "case")} queued.`,
      failure: "Couldn't queue those",
    });
    setBusy(null);
    if (result) {
      setSelected({});
      bumpReload();
      // A selected item can start immediately; land where it actually is.
      setParams({ tab: (result.queue?.running?.length ?? 0) > 0 ? "running" : "queued" });
    }
  };

  const run = async (label: string, fn: () => Promise<unknown>, success: string) => {
    setBusy(label);
    await withToast(fn, { success, failure: `${label} failed` });
    setBusy(null);
    bumpReload();
  };

  // "Investigate now anyway": one deferred item, past today's cap. The server
  // records who did it on the queue row.
  const runNow = async (row: CaseRow) => {
    if (row.queue_id == null) return;
    setRunningNow(row.queue_id);
    const result = await withToast(() => api.runQueuedNow(row.queue_id!), {
      success: "Started now, outside today's limit.",
      failure: "Couldn't start that item",
    });
    setRunningNow(null);
    bumpReload();
    if (result?.investigation_id) onOpenCase(result.investigation_id, "running");
  };

  const editTheme = async (body: Parameters<typeof api.setThemeOverride>[0], success: string) => {
    await withToast(() => api.setThemeOverride(body), {
      success, failure: "Couldn't save that change",
    });
    candidates.reload();
    view.reload();
  };

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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Cases"
        product={product}
        subtitle="Every case, from queued to verified"
        right={
          reviewer ? (
            <button onClick={onNewCase} className="el-btn el-btn--primary"
              style={{ borderRadius: R.control,
                       padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base, cursor: "pointer" }}>
              <Icon name="plus" size={15} /> New case
            </button>
          ) : undefined
        }
      />

      {/* filter bar — every value here is in the URL */}
      <div className="el-case-filters" style={{ flex: "none", borderBottom: `1px solid ${C.border}`,
                    padding: `${S[3]} ${S[6]}`, display: "flex", alignItems: "center",
                    gap: S[2], flexWrap: "wrap" }}>
        <div className="el-ui-forms-case-tabs" role="group" aria-label="Case status">
          {CASE_TABS.map((t) => {
            const active = t.key === tab;
            const n = t.key === "all" ? counts.all : counts[t.key];
            return (
              <button
                key={t.key}
                onClick={() => setParams({ tab: t.key === "all" ? null : t.key })}
                className="el-btn"
                aria-pressed={active}
                style={{
                  background: active ? C.active : "transparent",
                  color: active ? C.text : C.muted,
                  border: `1px solid ${active ? C.border3 : "transparent"}`,
                  borderRadius: R.control, padding: `${S[1]} ${S[3]}`, fontSize: T.sm, cursor: "pointer",
                  fontFamily: sans, whiteSpace: "nowrap",
                }}
              >
                {t.label}
                {n != null && (
                  <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginLeft: 7 }}>
                    {n}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="el-ui-forms-case-controls">
          <Select label="Severity" value={sev} onChange={(v) => setParams({ sev: v })}
                  options={[["", "Any severity"], ...Object.entries(SEVERITY).map(
                    ([k, m]) => [k, k === "unknown" ? "Severity unknown" : `${m.label} severity`] as [string, string])]} />
          <Select label="Source" value={source} onChange={(v) => setParams({ source: v })}
                  options={[["", "Any source"], ...sources.map(
                    (s) => [s, sourceLabel(s)] as [string, string])]} />
          <Select label="Time range" value={range} onChange={(v) => setParams({ range: v })}
                  options={RANGES.map((r) => [r.key, r.label] as [string, string])} />
          <Select label="Review intent (signals and themes)" value={intent}
                  onChange={(v) => setParams({ intent: v || null })}
                  options={INTENT_FILTERS.map((f) => [f.key, f.key ? f.label : "Any intent"] as [string, string])} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search cases…"
            aria-label="Search cases"
            style={{ width: 200, minWidth: 0, background: C.card, border: `1px solid ${C.border3}`,
                     borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.sm,
                     padding: `${S[2]} ${S[3]}` }}
          />
          <SavedViewsBar key={productId ?? "none"} productId={productId} params={{ ...params, q: search }}
            onApply={(next) => { setSearch(next.q ?? ""); setParams(next); }} />
        </div>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]} ${S[10]}` }}>
        {view.error ? (
          <ErrorState onRetry={view.reload} />
        ) : view.loading && !view.data ? (
          <Skeleton rows={4} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={emptyTitle(tab, filtered, product, selectable)}
            body={emptyBody(tab, filtered, product, selectable)}
            action={filtered ? "Clear filters" : selectable > 0 ? "Show signals" : undefined}
            onAction={
              filtered
                ? () => setParams({ sev: null, source: null, range: null, q: null })
                : selectable > 0
                  ? () => setSignalsOpen(true)
                  : undefined
            }
          />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
            {rows.map((r) => (
              <div key={r.id != null ? `c-${r.id}` : `q-${r.queue_id}`}
                   style={{ display: "flex", flexDirection: "column", gap: S[1] }}>
                <CaseCard
                  row={r}
                  busy={r.queue_id != null && cancelling === r.queue_id}
                  onOpen={(row) => row.id != null && onOpenCase(row.id, row.status)}
                  onAction={r.status === "queued" ? cancelQueued : undefined}
                />
                {r.deferred && (
                  <DeferredBar row={r} reviewer={reviewer}
                               busy={runningNow === r.queue_id} onRunNow={() => runNow(r)} />
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── signals: noticed, not yet a case ───────────────────────── */}
        <div ref={signalsRef}
             style={{ maxWidth: MEASURE, marginTop: S[8], borderTop: `1px solid ${C.border}`,
                      paddingTop: 18, scrollMarginTop: S[4] }}>
          <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap" }}>
            {/* A real <button> so click and keyboard run the SAME handler.
                They used to be two handlers, and the keyboard one only flipped
                local state — so a keyboard user's expanded Signals section
                never reached the URL and their shared link arrived collapsed,
                breaking the shareable-view guarantee for keyboard users only. */}
            <button
              onClick={() => { setSignalsOpen((o) => !o); setParams({ signals: signalsOpen ? null : "1" }); }}
              className="el-btn el-btn--sm"
              aria-expanded={signalsOpen}
              style={{ padding: `${S[1]} ${S[2]}`, marginLeft: `calc(-1 * ${S[2]})` }}
            >
              <Icon name={signalsOpen ? "chevronDown" : "chevronRight"} size={12}
                    style={{ color: selectable > 0 ? C.info : C.faint }} />
              <Label style={{ color: selectable > 0 ? C.info : C.faint }}>
                Signals · not yet cases · {selectable}
              </Label>
            </button>
            <div style={{ flex: 1 }} />
            {reviewer && signalsOpen && (
              <>
                <SmallButton
                  disabled={!!busy}
                  onClick={() => run("Scan", () => api.scan(),
                    "Scan finished — any new signals are listed below.")}
                >
                  {busy === "Scan" ? "Scanning…" : "Scan now"}
                </SmallButton>
                <SmallButton
                  disabled={!!busy}
                  onClick={() => run("Triage", () => api.triage(true),
                    "Triage finished — worthwhile signals became cases.")}
                >
                  {busy === "Triage" ? "Triaging…" : "Run triage"}
                </SmallButton>
              </>
            )}
          </div>

          {!signalsOpen ? (
            <p style={{ fontSize: T.sm, color: C.dim, margin: "8px 0 0", lineHeight: "var(--el-lh-normal)" }}>
              Spikes and recurring complaints EchoLens has noticed but hasn't investigated.
              {selectable > 0
                ? ` Open this to pick which ${plural(selectable, "one")} become cases.`
                : " Nothing is waiting for triage right now."}
            </p>
          ) : (
            <div style={{ marginTop: S[3] }}>
              <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 14px", lineHeight: "var(--el-lh-normal)" }}>
                Tick anything worth a case and commit once — they run one at a time, inside the
                daily budget. Nothing here has been investigated yet.
              </p>

              {selectable === 0 && takenThemes.length === 0 && dismissedSignals.length === 0 && (
                <EmptyState
                  title={`No untriaged signals for ${product ?? "this product"}`}
                  body="Everything EchoLens has detected is already a case, queued, or dismissed as noise. Run a scan to look again."
                />
              )}

              {(selectable > 0 || requests.length > 0) && (
                <IntentFilterBar value={intent} hidden={hiddenByIntent}
                                 onChange={(v) => setParams({ intent: v || null })} />
              )}

              {visIncidents.length + visSignals.length > 0 && (
                <>
                  <Label style={{ marginBottom: S[2] }}>
                    DETECTED · {visIncidents.length + visSignals.length}
                  </Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: S[2],
                                marginBottom: S[4] }}>
                    {detected.map(({ incident: inc, signal: s }) => inc ? (
                      <IncidentCard key={inc.key} incident={inc}
                                    members={inc.members.map((m) => bySlug.get(m)).filter(
                                      (m): m is SignalRow => !!m)}
                                    selected={!!selected[inc.lead]}
                                    onToggle={() => toggle(inc.lead, inc.title)} />
                    ) : s && (
                      <SignalCard key={s.slug} signal={s} selected={!!selected[s.slug]}
                                  onToggle={() => toggle(s.slug, s.title)} />
                    ))}
                  </div>
                </>
              )}

              {visThemes.length > 0 && (
                <>
                  <Label style={{ marginBottom: S[2] }}>
                    RECURRING COMPLAINTS · {visThemes.length}
                  </Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: S[2],
                                marginBottom: S[4] }}>
                    {visThemes.map((t) => (
                      <ThemeCard key={t.slug} theme={t} selected={!!selected[t.slug]}
                                 onToggle={() => toggle(t.slug, t.statement)}
                                 menu={reviewer ? (
                                   <ThemeMenu theme={t} others={allThemes} onEdit={editTheme} />
                                 ) : undefined} />
                    ))}
                  </div>
                </>
              )}

              {/* Asked for, not complained about: 3-5 star reviews with a
                  "wish / please add / would love" in them. Not investigated —
                  there is no root cause to find — so no checkbox. */}
              {visRequests.length > 0 && (
                <>
                  <Label style={{ marginBottom: S[2] }}>
                    REQUESTS FROM USERS · {visRequests.length}
                  </Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: S[2],
                                marginBottom: S[4] }}>
                    {visRequests.map((t) => (
                      <ThemeCard key={t.slug} theme={t}
                                 menu={reviewer ? (
                                   <ThemeMenu theme={t} others={requests} onEdit={editTheme} />
                                 ) : undefined} />
                    ))}
                  </div>
                </>
              )}

              {(candidates.data?.muted ?? 0) > 0 && (
                <MutedThemes count={candidates.data?.muted ?? 0} reviewer={reviewer}
                             onUnmute={(slug) => editTheme({ slug, action: "unmute" },
                               "Theme unmuted — it shows again.")} />
              )}

              {takenThemes.length > 0 && (
                <div style={{ fontSize: T.sm, color: C.faint, marginBottom: S[3] }}>
                  {takenThemes.length} more{" "}
                  {plural(takenThemes.length, "complaint is", "complaints are")} already queued or
                  investigated — {takenThemes.length === 1 ? "it is" : "they are"} in the list above.
                </div>
              )}

              {dismissedSignals.length > 0 && (
                <>
                  <Label style={{ marginBottom: S[2], color: C.faint }}>
                    DISMISSED OR MERGED · {dismissedSignals.length}
                  </Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
                    {dismissedSignals.map((s) => (
                      <div key={s.slug} style={{ display: "flex", alignItems: "center", gap: S[2],
                                                 padding: `${S[2]} ${S[3]}`, background: C.card2,
                                                 border: `1px solid ${C.border2}`,
                                                 borderRadius: R.control, opacity: 0.72 }}>
                        <span style={{ flex: 1, minWidth: 0, fontSize: T.sm, color: C.muted,
                                       overflow: "hidden", textOverflow: "ellipsis",
                                       whiteSpace: "nowrap" }}>
                          {s.title}
                        </span>
                        {s.dismissed_reason && (
                          <span style={{ fontSize: T.sm, color: C.dim, fontStyle: "italic",
                                         maxWidth: 320, overflow: "hidden",
                                         textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {s.dismissed_reason}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* one commit for any number of selections */}
      {reviewer && selectedCount > 0 && (
        <div className="el-ui-forms-selection" role="group" aria-label="Selected signals and themes"
          style={{ flex: "none", border: `1px solid ${C.border3}`, background: C.bgRaised,
                      borderRadius: R.card, boxShadow: "var(--el-e3)",
                      padding: `${S[3]} ${S[4]}`, display: "flex", alignItems: "center", gap: S[3],
                      flexWrap: "wrap" }}>
          <span role="status" aria-live="polite" style={{ fontSize: T.base, color: C.text2 }}>
            <strong>{selectedCount}</strong> selected
          </span>
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>
            runs one at a time, inside today's budget
          </span>
          <div style={{ flex: 1 }} />
          <SmallButton onClick={() => setSelected({})}>Clear</SmallButton>
          <button onClick={investigateSelected} disabled={busy === "queue"} className="el-btn el-btn--primary"
            style={{ borderRadius: R.control,
                     padding: `${S[2]} ${S[4]}`, fontWeight: 600, fontSize: T.base,
                     cursor: busy === "queue" ? "wait" : "pointer" }}>
            {busy === "queue" ? "Queueing…" : `Investigate selected (${selectedCount})`}
          </button>
        </div>
      )}
    </div>
  );
}

function emptyTitle(tab: string, filtered: boolean, product: string | null,
                    signals = 0): string {
  if (filtered) return "No cases match those filters";
  const label = CASE_TABS.find((t) => t.key === tab)?.label ?? "Cases";
  if (tab === "all") {
    // Onboarding hands off here saying "review N signals in Cases". A signal is
    // not yet a case, so `cases` is legitimately empty — but the title said "No
    // cases yet", which reads as "nothing was found" and contradicts the
    // sentence the user just clicked. Name what IS here.
    return signals > 0
      ? `${signals} ${plural(signals, "signal")} waiting for you in ${product ?? "this product"}`
      : `No cases yet for ${product ?? "this product"}`;
  }
  return `Nothing under ${label} for ${product ?? "this product"}`;
}

function emptyBody(tab: string, filtered: boolean, product: string | null, signals: number) {
  if (filtered) return "Widen the filters, or clear them to see every case.";
  switch (tab) {
    case "needs-review":
      return "Nothing is waiting on you — every finding has been reviewed and no case has stalled.";
    case "running":
      return "No investigation is running. Start one from Signals below.";
    case "queued":
      return "Nothing is waiting to run. Pick signals below and they queue here in order.";
    case "resolved":
      return `No case has resolved yet for ${product ?? "this product"}. Resolved cases and verified fixes collect here.`;
    case "dismissed":
      return "Nothing has been dismissed. Findings you challenge and signals ruled out as noise land here.";
    default:
      return signals > 0
        ? `EchoLens has found ${signals} ${plural(signals, "signal")} worth a look. Open Signals below and pick what becomes a case.`
        : "Cases start from a detected signal, a recurring complaint, or a case you open yourself with + New case.";
  }
}

/** Signals carry no severity field; derive a band from z so the sort is meaningful. */
function signalSeverity(s: { z: number }): string {
  const z = Math.abs(s.z);
  return z >= 3 ? "high" : z >= 2 ? "medium" : "low";
}

function detectedOn(ageDays: number | null): string | null {
  if (ageDays == null || !Number.isFinite(ageDays)) return null;
  const d = new Date();
  d.setDate(d.getDate() - Math.max(0, Math.round(ageDays)));
  return when(d.toISOString());
}

function SignalCard({ signal, selected, onToggle }: {
  signal: SignalRow; selected: boolean; onToggle: () => void;
}) {
  return (
    <label className="el-card" style={{ display: "flex", alignItems: "flex-start", gap: S[3],
                                        padding: `${S[3]} ${S[4]}`, cursor: "pointer" }}>
      <input type="checkbox" checked={selected} onChange={onToggle}
        aria-label={`Select: ${signal.title}`}
        style={{ width: 15, height: 15, marginTop: S[1], flex: "none",
                 accentColor: C.accent, cursor: "pointer" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-snug)" }}>{signal.title}</div>
        <div style={{ display: "flex", gap: S[2], marginTop: S[1], flexWrap: "wrap",
                      fontFamily: mono, fontSize: T.micro, color: C.faint }}>
          <span>{sourceLabel(signal.type)}</span>
          <span>z {signal.z.toFixed(1)}</span>
          <span>{signal.window} window</span>
          {detectedOn(signal.age_days) && <span>detected {detectedOn(signal.age_days)}</span>}
        </div>
        <IntentPills counts={signal.intents} />
      </div>
    </label>
  );
}

function ThemeCard({ theme, selected, onToggle, menu }: {
  theme: ThemeCandidate;
  /** Omitted for display-only cards (user requests), which have no checkbox. */
  selected?: boolean;
  onToggle?: () => void;
  menu?: React.ReactNode;
}) {
  // The statement IS the first quote when it fell back to verbatim, so one
  // quote is nothing new to show; otherwise even a single example is worth it.
  const quotesToShow = theme.label_source === "verbatim" ? 1 : 0;
  const [open, setOpen] = useState(false);
  const trend =
    theme.trend === "up" ? { s: "arrowUp", c: C.bad } :
    theme.trend === "down" ? { s: "arrowDown", c: C.good } : null;
  return (
    <div className="el-card" style={{ padding: `${S[3]} ${S[4]}` }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: S[3] }}>
        {onToggle && (
          <input type="checkbox" checked={!!selected} onChange={onToggle}
            aria-label={`Select: ${theme.statement}`}
            style={{ width: 15, height: 15, marginTop: S[1], flex: "none",
                     accentColor: C.accent, cursor: "pointer" }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-snug)" }}
               title={theme.renamed ? `Generated name: ${theme.original_statement ?? ""}` : undefined}>
            {theme.statement}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[1],
                        flexWrap: "wrap" }}>
            <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
              {theme.count} {plural(theme.count, "review")}
            </span>
            {trend && (
              <span style={{ fontFamily: mono, fontSize: T.micro, color: trend.c }}>
                · <Icon name={trend.s} size={11} /> {theme.trend === "up" ? "rising" : "falling"}
              </span>
            )}
            {theme.label_source === "verbatim" && (
              <span title="Shown in a customer's own words — the generated label wasn't confident enough."
                style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[1]}`, borderRadius: R.control,
                         background: C.hover, color: C.faint }}>
                VERBATIM
              </span>
            )}
            {theme.avg_rating != null && (
              <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
                · avg {theme.avg_rating.toFixed(1)}★
              </span>
            )}
            {theme.renamed && (
              <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>· renamed</span>
            )}
            {(theme.merged_from?.length ?? 0) > 0 && (
              <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
                · {theme.merged_from!.length} merged in
              </span>
            )}
            {theme.verbatims.length > quotesToShow && (
              <button onClick={() => setOpen((o) => !o)} className="el-btn el-btn--sm"
                aria-expanded={open}
                style={{ fontFamily: mono, fontSize: T.micro, color: C.dim, padding: `0 ${S[1]}` }}>
                <Icon name={open ? "chevronDown" : "chevronRight"} size={11} />
                {open ? "hide examples" : `show ${theme.verbatims.length} example ${plural(theme.verbatims.length, "review")}`}
              </button>
            )}
          </div>
          {open && (
            <div style={{ display: "flex", flexDirection: "column", gap: S[1], marginTop: S[2],
                          paddingLeft: 10, borderLeft: `2px solid ${C.border3}` }}>
              {theme.verbatims.map((v, i) => (
                <div key={i} style={{ fontSize: T.sm, color: C.dim, lineHeight: "var(--el-lh-normal)" }}>“{v}”</div>
              ))}
            </div>
          )}
          <IntentPills counts={theme.intents} />
        </div>
        {menu}
      </div>
    </div>
  );
}

// ── intents ─────────────────────────────────────────────────────────────

type IntentFilter = "" | "bug" | "feature_request" | "ux_confusion";

const INTENT_META: { key: keyof IntentCounts; label: string; color: string }[] = [
  { key: "bug", label: "Bug", color: C.bad },
  { key: "feature_request", label: "Request", color: C.info },
  { key: "ux_confusion", label: "UX confusion", color: C.accent },
  { key: "praise", label: "Praise", color: C.good },
  { key: "other", label: "Other", color: C.faint },
];

const INTENT_FILTERS: { key: IntentFilter; label: string }[] = [
  { key: "", label: "All" },
  { key: "bug", label: "Bugs" },
  { key: "feature_request", label: "Requests" },
  { key: "ux_confusion", label: "UX confusion" },
];

/** Keep a card when the chosen intent leads it or is at least a quarter of it.
 * A card with no reviews behind it (a GitHub burst) only shows under All. */
function intentMatches(counts: IntentCounts | null | undefined, filter: IntentFilter): boolean {
  if (!filter) return true;
  if (!counts) return false;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const n = counts[filter] ?? 0;
  if (!total || !n) return false;
  const top = Math.max(...Object.values(counts));
  return n === top || n / total >= 0.25;
}

function IntentPills({ counts }: { counts?: IntentCounts | null }) {
  if (!counts) return null;
  const shown = INTENT_META.filter((m) => (counts[m.key] ?? 0) > 0);
  if (shown.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: S[1], marginTop: S[2], flexWrap: "wrap" }}
         aria-label="What these reviews are about">
      {shown.map((m) => (
        <span key={m.key}
          style={{ display: "inline-flex", alignItems: "center", gap: S[1],
                   padding: `1px ${S[2]}`, borderRadius: R.pill,
                   border: `1px solid ${C.border3}`, fontSize: T.micro, color: C.muted,
                   fontFamily: mono, whiteSpace: "nowrap" }}>
          <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%",
                                     background: m.color, flex: "none" }} />
          {m.label} {counts[m.key]}
        </span>
      ))}
    </div>
  );
}

function IntentFilterBar({ value, onChange, hidden }: {
  value: IntentFilter; onChange: (v: IntentFilter) => void; hidden: number;
}) {
  return (
    <div role="group" aria-label="Filter by what the reviews are about"
         style={{ display: "flex", alignItems: "center", gap: S[1], flexWrap: "wrap",
                  marginBottom: S[3] }}>
      {INTENT_FILTERS.map((f) => {
        const active = f.key === value;
        return (
          <button key={f.key || "all"} onClick={() => onChange(f.key)} className="el-btn"
            aria-pressed={active}
            style={{ background: active ? C.active : "transparent",
                     color: active ? C.text : C.muted,
                     border: `1px solid ${active ? C.border3 : "transparent"}`,
                     borderRadius: R.control, padding: `${S[1]} ${S[3]}`, fontSize: T.sm,
                     cursor: "pointer", fontFamily: sans, whiteSpace: "nowrap" }}>
            {f.label}
          </button>
        );
      })}
      {hidden > 0 && (
        <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginLeft: S[2] }}>
          {hidden} hidden by this filter
        </span>
      )}
    </div>
  );
}

// ── incidents ───────────────────────────────────────────────────────────

function IncidentCard({ incident, members, selected, onToggle }: {
  incident: Incident; members: SignalRow[]; selected: boolean; onToggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  const others = members.length - 1;
  return (
    <div className="el-card" style={{ padding: `${S[3]} ${S[4]}` }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: S[3] }}>
        <input type="checkbox" checked={selected} onChange={onToggle}
          aria-label={`Select incident: ${incident.title}`}
          style={{ width: 15, height: 15, marginTop: S[1], flex: "none",
                   accentColor: C.accent, cursor: "pointer" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-snug)" }}>
            {incident.title}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[1],
                        flexWrap: "wrap", fontFamily: mono, fontSize: T.micro, color: C.faint }}>
            <span style={{ color: C.info }}>INCIDENT</span>
            <span>{members.length} related signals, same window</span>
            <span>z {incident.z.toFixed(1)}</span>
            <button onClick={() => setOpen((o) => !o)} className="el-btn el-btn--sm"
              aria-expanded={open}
              style={{ fontFamily: mono, fontSize: T.micro, color: C.dim, padding: `0 ${S[1]}` }}>
              <Icon name={open ? "chevronDown" : "chevronRight"} size={11} />
              {open ? "hide signals" : "show signals"}
            </button>
          </div>
          {open && (
            <div style={{ display: "flex", flexDirection: "column", gap: S[1], marginTop: S[2],
                          paddingLeft: 10, borderLeft: `2px solid ${C.border3}` }}>
              {members.map((m, i) => (
                <div key={m.slug} style={{ display: "flex", gap: S[2], flexWrap: "wrap",
                                           fontSize: T.sm, color: C.dim }}>
                  <span style={{ color: i === 0 ? C.text2 : C.dim }}>{m.title}</span>
                  <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
                    {sourceLabel(m.type)} · z {m.z.toFixed(1)}{i === 0 ? " · strongest" : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
          {selected && others > 0 && (
            <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[2] }}>
              Investigates the strongest signal; the other {others}{" "}
              {plural(others, "is", "are")} noted on the case.
            </div>
          )}
          <IntentPills counts={incident.intents} />
        </div>
      </div>
    </div>
  );
}

// ── editable themes ─────────────────────────────────────────────────────

type OverrideBody = Parameters<typeof api.setThemeOverride>[0];

function ThemeMenu({ theme, others, onEdit }: {
  theme: ThemeCandidate; others: ThemeCandidate[];
  onEdit: (body: OverrideBody, success: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"menu" | "rename" | "merge">("menu");
  const [label, setLabel] = useState(theme.statement);
  const [into, setInto] = useState("");
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const targets = others.filter((o) => o.slug !== theme.slug);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const save = async (body: OverrideBody, success: string) => {
    setSaving(true);
    await onEdit(body, success);
    setSaving(false);
    setOpen(false);
  };

  const item = (text: string, onClick: () => void, disabled = false) => (
    <button onClick={onClick} disabled={disabled || saving} className="el-btn"
      style={{ display: "block", width: "100%", textAlign: "left", background: "transparent",
               border: "none", color: disabled ? C.faint : C.text2, fontSize: T.sm,
               fontFamily: sans, padding: `${S[2]} ${S[3]}`, cursor: disabled ? "default" : "pointer" }}>
      {text}
    </button>
  );

  return (
    <div ref={ref} style={{ position: "relative", flex: "none" }}>
      <button onClick={() => { setOpen((o) => !o); setMode("menu"); setLabel(theme.statement); }}
        className="el-btn el-btn--sm" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Edit theme: ${theme.statement}`} title="Rename, merge or mute"
        style={{ color: C.dim, padding: `0 ${S[2]}`, fontSize: T.base, lineHeight: 1 }}>
        ⋯
      </button>
      {open && (
        <div role="menu"
          style={{ position: "absolute", right: 0, top: "100%", marginTop: S[1], zIndex: 20,
                   minWidth: 240, maxWidth: "min(320px, 80vw)", background: C.bgRaised,
                   border: `1px solid ${C.border3}`, borderRadius: R.control,
                   boxShadow: "var(--el-e3)", padding: S[1] }}>
          {mode === "menu" && (
            <>
              {item("Rename…", () => setMode("rename"))}
              {item(targets.length ? "Merge into…" : "Merge into… (no other themes)",
                    () => setMode("merge"), targets.length === 0)}
              {item("Mute — hide it and stop new signals", () =>
                save({ slug: theme.slug, action: "mute" },
                     "Theme muted. It's hidden and won't raise new signals."))}
              {theme.renamed && item("Restore generated name", () =>
                save({ slug: theme.slug, action: "rename", label: "" }, "Generated name restored."))}
            </>
          )}
          {mode === "rename" && (
            <form onSubmit={(e) => { e.preventDefault();
                                     save({ slug: theme.slug, action: "rename", label },
                                          "Theme renamed."); }}
                  style={{ display: "flex", flexDirection: "column", gap: S[2], padding: S[2] }}>
              <input value={label} onChange={(e) => setLabel(e.target.value)} autoFocus
                aria-label="New theme name" maxLength={120}
                style={{ background: C.card, border: `1px solid ${C.border3}`,
                         borderRadius: R.control, color: C.text, fontFamily: sans,
                         fontSize: T.sm, padding: `${S[2]} ${S[3]}` }} />
              <div style={{ display: "flex", gap: S[2], justifyContent: "flex-end" }}>
                <SmallButton onClick={() => setMode("menu")}>Back</SmallButton>
                <button type="submit" disabled={saving || !label.trim()}
                  className="el-btn el-btn--primary el-btn--sm">
                  {saving ? "Saving…" : "Rename"}
                </button>
              </div>
            </form>
          )}
          {mode === "merge" && (
            <div style={{ display: "flex", flexDirection: "column", gap: S[2], padding: S[2] }}>
              <select value={into} onChange={(e) => setInto(e.target.value)}
                aria-label="Theme to merge into"
                style={{ background: C.card, border: `1px solid ${C.border3}`,
                         borderRadius: R.control, color: C.text, fontFamily: sans,
                         fontSize: T.sm, padding: S[2] }}>
                <option value="">Choose a theme…</option>
                {targets.map((t) => <option key={t.slug} value={t.slug}>{t.statement}</option>)}
              </select>
              <div style={{ display: "flex", gap: S[2], justifyContent: "flex-end" }}>
                <SmallButton onClick={() => setMode("menu")}>Back</SmallButton>
                <button disabled={saving || !into}
                  onClick={() => save({ slug: theme.slug, action: "merge", into },
                                      "Merged — its reviews now count toward the other theme.")}
                  className="el-btn el-btn--primary el-btn--sm">
                  {saving ? "Merging…" : "Merge"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function MutedThemes({ count, reviewer, onUnmute }: {
  count: number; reviewer: boolean; onUnmute: (slug: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ThemeOverride[] | null>(null);
  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      try {
        setRows((await api.themeOverrides()).overrides.filter((o) => o.muted));
      } catch {
        setRows([]);
      }
    }
  };
  return (
    <div style={{ marginBottom: S[4] }}>
      <button onClick={toggle} className="el-btn el-btn--sm" aria-expanded={open}
        style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, padding: `0 ${S[1]}` }}>
        <Icon name={open ? "chevronDown" : "chevronRight"} size={11} />
        {count} muted {plural(count, "theme")}
      </button>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: S[1], marginTop: S[2] }}>
          {rows == null ? (
            <span style={{ fontSize: T.sm, color: C.faint }}>Loading…</span>
          ) : rows.length === 0 ? (
            <span style={{ fontSize: T.sm, color: C.faint }}>Nothing is muted.</span>
          ) : rows.map((o) => (
            <div key={o.slug} style={{ display: "flex", alignItems: "center", gap: S[2],
                                       fontSize: T.sm, color: C.dim }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>
                {o.label || o.slug.replace(/^(theme|request)-p\d+-/, "").replace(/-/g, " ")}
              </span>
              {o.updated_by && (
                <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
                  by {o.updated_by}
                </span>
              )}
              {reviewer && (
                <SmallButton onClick={async () => {
                  await onUnmute(o.slug);
                  setRows((r) => (r ?? []).filter((x) => x.slug !== o.slug));
                }}>Unmute</SmallButton>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── daily cap ───────────────────────────────────────────────────────────

/** Under a queued card that lost on today's budget: why it is waiting, and the
 * one-off way past the cap, with what it is likely to cost. */
function DeferredBar({ row, reviewer, busy, onRunNow }: {
  row: CaseRow; reviewer: boolean; busy: boolean; onRunNow: () => void;
}) {
  const est = row.estimate;
  const estText = est
    ? est.basis === "median"
      ? `est. ~${money(est.usd)} (typical ${est.tier} case, from ${est.samples} past)`
      : `est. up to ${money(est.usd)} (${est.tier} budget cap)`
    : null;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: S[3], flexWrap: "wrap",
                  padding: `${S[2]} ${S[4]}`, marginLeft: S[2], borderLeft: `2px solid ${C.accentLine}`,
                  fontSize: T.sm, color: C.dim }}>
      <span style={{ flex: 1, minWidth: 200 }}>{row.why}</span>
      {reviewer && (
        <>
          {estText && (
            <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}
                  title="An estimate, not a quote — real cost depends on how much evidence the case needs.">
              {estText}
            </span>
          )}
          <button onClick={onRunNow} disabled={busy} className="el-btn el-btn--sm"
            style={{ border: `1px solid ${C.border3}`, borderRadius: R.control,
                     padding: `${S[1]} ${S[3]}`, color: C.text2, cursor: busy ? "wait" : "pointer" }}>
            {busy ? "Starting…" : "Investigate now anyway"}
          </button>
        </>
      )}
    </div>
  );
}

function Select({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value || "")}
      style={{ background: C.card, border: `1px solid ${C.border3}`, borderRadius: R.control,
               color: value ? C.text : C.muted, fontFamily: sans, fontSize: T.sm,
               padding: `${S[2]} ${S[2]}`, cursor: "pointer" }}
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  );
}

function SmallButton({ children, onClick, disabled }: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button onClick={onClick} disabled={disabled} className="el-btn"
      style={{ background: "transparent", color: C.muted, border: `1px solid ${C.border3}`,
               borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.sm, fontFamily: sans,
               cursor: disabled ? "wait" : "pointer" }}>
      {children}
    </button>
  );
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
    <div className="el-ui-forms-saved-views" aria-label="Saved Cases views" style={{ display: "flex", flexDirection: "column", gap: S[2], minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
        {rows.map((view) => {
          const active = CASE_VIEW_FILTERS.every(k => (view.params[k] ?? "") === (current[k] ?? ""));
          return (
            <div key={view.id} style={{ display: "inline-flex", alignItems: "center", borderRadius: R.pill,
              border: `1px solid ${active ? C.accentLine : C.border3}`, background: active ? C.accentBg : C.card }}>
              <button className="el-btn el-btn--sm" aria-pressed={active} title={view.name}
                disabled={busy} onClick={() => onApply(Object.fromEntries(
                  CASE_VIEW_FILTERS.map(k => [k, view.params[k] || null])))}
                style={{ color: active ? C.accent : C.text3, padding: `${S[1]} ${S[3]}`, maxWidth: 180 }}>
                <span className="el-truncate">{view.name}</span>
              </button>
              {canManage && <>
                <button className="el-btn el-btn--sm" aria-label={`Rename ${view.name}`} disabled={busy}
                  onClick={() => begin(view)} style={{ color: C.dim, fontSize: T.micro }}>Rename</button>
                <button className="el-btn el-btn--sm" aria-label={`Delete ${view.name}`} disabled={busy}
                  onClick={() => mutate(() => api.deleteSavedView(view.id, productId))} style={{ color: C.dim }}>
                  <Icon name="close" size={12} />
                </button>
              </>}
            </div>
          );
        })}
        {canManage && <button className="el-btn el-btn--ghost el-btn--sm" onClick={() => begin(null)}
          disabled={busy || views.loading || !!views.error || rows.length >= 20}
          title={rows.length >= 20 ? "You can save up to 20 views per product" : "Save these Cases filters"}>
          Save view
        </button>}
        <span style={{ fontSize: T.micro, color: C.faint }}>
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
          disabled={busy} onChange={(e) => setName(e.target.value)}
          style={{ minWidth: 0, width: 220, padding: `${S[2]} ${S[3]}`, borderRadius: R.control,
            border: `1px solid ${C.border3}`, background: C.card, color: C.text, fontSize: T.sm }} />
        <button className="el-btn el-btn--primary el-btn--sm" type="submit" disabled={busy || !name.trim()}>
          {busy ? "Saving..." : editing ? "Rename view" : "Save"}
        </button>
        <button className="el-btn el-btn--ghost el-btn--sm" type="button" disabled={busy}
          onClick={() => { setEditing(undefined); setError(null); }}>Cancel</button>
      </form>}
      {views.error && <div role="alert" style={{ fontSize: T.sm, color: C.bad }}>
        Couldn't load saved views. <button className="el-btn el-btn--sm" onClick={views.reload}>Retry</button>
      </div>}
      {error && <div role="alert" style={{ fontSize: T.sm, color: C.bad }}>{error}</div>}
    </div>
  );
}
