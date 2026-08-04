import { useEffect, useMemo, useRef, useState } from "react";
import { CaseRow, SignalRow, ThemeCandidate, api, canReview } from "../api";
import { CaseCard } from "../components/CaseCard";
import { withToast } from "../components/Toast";
import { age, plural } from "../format";
import { useAsync } from "../hooks";
import { CASE_TABS, SEVERITY } from "../status";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { EmptyState, ErrorState, Label, ScreenHeader, Skeleton, WorkflowRail } from "../ui";
import { Icon } from "../components/Icon";

interface Props {
  productName: string | null;
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
  productName, params, setParams, onOpenCase, onNewCase, reloadKey, bumpReload,
}: Props) {
  const view = useAsync(() => api.cases(), [reloadKey]);
  const candidates = useAsync(() => api.feedCandidates(), [reloadKey]);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<number | null>(null);
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
  const liveSignals = signals.filter((s) => !s.dismissed);
  const dismissedSignals = signals.filter((s) => s.dismissed);
  const themes = (candidates.data?.candidates ?? []).filter((c) => !c.existing);
  const takenThemes = (candidates.data?.candidates ?? []).filter((c) => c.existing);
  const selectable = liveSignals.length + themes.length;
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
      setParams({ tab: "queued" });
    }
  };

  const run = async (label: string, fn: () => Promise<unknown>, success: string) => {
    setBusy(label);
    await withToast(fn, { success, failure: `${label} failed` });
    setBusy(null);
    bumpReload();
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
      <WorkflowRail active="signal" />

      <div className="el-case-filters" style={{ flex: "none", borderBottom: `1px solid ${C.border}`,
                    padding: `${S[3]} ${S[6]}`, display: "flex", alignItems: "center",
                    gap: S[2], flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: S[1], flexWrap: "wrap" }}>
          {CASE_TABS.map((t) => {
            const active = t.key === tab;
            const n = t.key === "all" ? counts.all : counts[t.key];
            return (
              <button
                key={t.key}
                onClick={() => setParams({ tab: t.key === "all" ? null : t.key })}
                className="el-btn"
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
        <div style={{ flex: 1 }} />
        <Select value={sev} onChange={(v) => setParams({ sev: v })}
                options={[["", "Any severity"], ...Object.entries(SEVERITY).map(
                  ([k, m]) => [k, `${m.label} severity`] as [string, string])]} />
        <Select value={source} onChange={(v) => setParams({ source: v })}
                options={[["", "Any source"], ...sources.map(
                  (s) => [s, sourceLabel(s)] as [string, string])]} />
        <Select value={range} onChange={(v) => setParams({ range: v })}
                options={RANGES.map((r) => [r.key, r.label] as [string, string])} />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search cases…"
          aria-label="Search cases"
          style={{ width: 200, background: C.card, border: `1px solid ${C.border3}`,
                   borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.sm,
                   padding: `${S[2]} ${S[3]}` }}
        />
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
              <CaseCard
                key={r.id != null ? `c-${r.id}` : `q-${r.queue_id}`}
                row={r}
                busy={r.queue_id != null && cancelling === r.queue_id}
                onOpen={(row) => row.id != null && onOpenCase(row.id, row.status)}
                onAction={r.status === "queued" ? cancelQueued : undefined}
              />
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

              {liveSignals.length > 0 && (
                <>
                  <Label style={{ marginBottom: S[2] }}>DETECTED · {liveSignals.length}</Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: S[2],
                                marginBottom: S[4] }}>
                    {liveSignals.map((s) => (
                      <SignalCard key={s.slug} signal={s} selected={!!selected[s.slug]}
                                  onToggle={() => toggle(s.slug, s.title)} />
                    ))}
                  </div>
                </>
              )}

              {themes.length > 0 && (
                <>
                  <Label style={{ marginBottom: S[2] }}>
                    RECURRING COMPLAINTS · {themes.length}
                  </Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: S[2],
                                marginBottom: S[4] }}>
                    {themes.map((t) => (
                      <ThemeCard key={t.slug} theme={t} selected={!!selected[t.slug]}
                                 onToggle={() => toggle(t.slug, t.statement)} />
                    ))}
                  </div>
                </>
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
                    DISMISSED AS NOISE · {dismissedSignals.length}
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
        <div style={{ flex: "none", borderTop: `1px solid ${C.border2}`, background: C.bgRaised,
                      padding: `${S[3]} ${S[6]}`, display: "flex", alignItems: "center", gap: S[4],
                      flexWrap: "wrap" }}>
          <span style={{ fontSize: T.base, color: C.text2 }}>
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
          <span>{signal.window}</span>
          <span>{age(signal.age_days)}</span>
        </div>
      </div>
    </label>
  );
}

function ThemeCard({ theme, selected, onToggle }: {
  theme: ThemeCandidate; selected: boolean; onToggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  const trend =
    theme.trend === "up" ? { s: "arrowUp", c: C.bad } :
    theme.trend === "down" ? { s: "arrowDown", c: C.good } : null;
  return (
    <div className="el-card" style={{ padding: `${S[3]} ${S[4]}` }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: S[3] }}>
        <input type="checkbox" checked={selected} onChange={onToggle}
          aria-label={`Select: ${theme.statement}`}
          style={{ width: 15, height: 15, marginTop: S[1], flex: "none",
                   accentColor: C.accent, cursor: "pointer" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-snug)" }}>{theme.statement}</div>
          <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[1],
                        flexWrap: "wrap" }}>
            <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
              {theme.count} {plural(theme.count, "review")}
            </span>
            {trend && (
              <span style={{ fontFamily: mono, fontSize: T.micro, color: trend.c }}>
                <Icon name={trend.s} size={11} /> {theme.trend}
              </span>
            )}
            {theme.label_source === "verbatim" && (
              <span title="Shown in a customer's own words — the generated label wasn't confident enough."
                style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[1]}`, borderRadius: R.control,
                         background: C.hover, color: C.faint }}>
                VERBATIM
              </span>
            )}
            {theme.verbatims.length > 1 && (
              <button onClick={() => setOpen((o) => !o)} className="el-btn el-btn--sm"
                aria-expanded={open}
                style={{ fontFamily: mono, fontSize: T.micro, color: C.dim, padding: `0 ${S[1]}` }}>
                <Icon name={open ? "chevronDown" : "chevronRight"} size={11} />
                {open ? "hide reviews" : `${theme.verbatims.length} reviews`}
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
        </div>
      </div>
    </div>
  );
}

function Select({ value, onChange, options }: {
  value: string; onChange: (v: string) => void; options: [string, string][];
}) {
  return (
    <select
      aria-label="Filter cases"
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
