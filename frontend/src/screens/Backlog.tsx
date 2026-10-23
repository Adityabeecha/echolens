import { useEffect, useRef, useState } from "react";
import {
  BacklogItem, PlanItem, PlanKind, PlanOverride, PlanSegment, QuarterPlan, RequestPlanItem,
  api, canReview,
} from "../api";
import { age, plural } from "../format";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Bar, Centered, EmptyState, ErrorState, Label, ScreenHeader } from "../ui";
import { Icon } from "../components/Icon";
import { SubTabs } from "../components/SubTabs";

const BAND: Record<string, string> = { high: C.bad, medium: C.accent, low: C.dim };

const isRequest = (i: PlanItem): i is RequestPlanItem => i.kind === "request";
/** What the plan stores for an item: investigation id, or request slug. */
const keyOf = (i: PlanItem): number | string => (isRequest(i) ? i.slug : i.investigation_id);

const KINDS: { key: PlanKind; label: string }[] = [
  { key: "bugs", label: "Bugs to fix" },
  { key: "requests", label: "Users are asking for" },
  { key: "all", label: "All" },
];
const SUBTITLE: Record<PlanKind, string> = {
  bugs: "Open problems, ranked by value per engineer-day",
  requests: "What users ask for, ranked by demand per engineer-day",
  all: "Bugs and requests in one plan, each scored against the best of its kind",
};

/** The spec modal, loaded on first use. */
type SpecModalType = typeof import("../components/SpecModal").SpecModal;

/** Rebuilt from the structured fields: the server's sentence carries raw floats. */
function defenceLine(i: BacklogItem): string {
  const bits = [`${i.severity.band} severity (${i.severity.score.toFixed(2)})`];
  if (i.volume) bits.push(`${i.volume} affected ${plural(i.volume, "review")}`);
  bits.push(`open · ${age(i.persistence_days)}`);
  if (i.projected.confident) bits.push(`~${i.projected.stars.toFixed(2)}★ recoverable`);
  bits.push(effortLabel(i));
  if (i.impact?.overridden) bits.push(`impact ×${i.impact.factor} (set by you)`);
  if (i.segment) bits.push(`×${i.segment.factor} ${i.segment.label.toLowerCase()} (set by you)`);
  bits.push(`${i.evidence_count} cited evidence ${plural(i.evidence_count, "item")}`);
  return bits.join(" · ");
}

function effortLabel(i: PlanItem): string {
  if (i.effort.overridden) return `${i.effort.days}d effort (set by you)`;
  return i.effort.known ? `${i.effort.days}d effort (${i.effort.basis})` : `est. ${i.effort.days}d (default)`;
}

interface Props {
  onOpenInvestigation: (id: number, status?: string) => void;
  onGoCases: () => void;
  onBack: () => void;
  backLabel: string;
}

/**
 * The quality backlog — EchoLens proposes a plan, the PM edits and owns it.
 *
 * Ranked by impact-per-effort rather than impact, because a slightly smaller
 * problem that costs a day genuinely should beat one that costs three weeks.
 * Every line shows the arithmetic that placed it there.
 */
export function Backlog({ onOpenInvestigation, onGoCases, onBack, backLabel }: Props) {
  const [plan, setPlan] = useState<QuarterPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const [capacity, setCapacity] = useState<number>(20);
  const [kind, setKind] = useState<PlanKind>("bugs");
  const [spec, setSpec] = useState<{ slug: string; title: string; Modal: SpecModalType } | null>(null);
  const reviewer = canReview();

  const load = (days?: number) => {
    setLoading(true);
    api
      .backlogPlan(days, kind)
      .then((p) => {
        setPlan(p);
        setCapacity(p.capacity_days);
        setError(null);
      })
      .catch((e) => setError(String(e).replace("Error: ", "")))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(), [kind]);

  // Imported on click so the modal (and its tracker calls) stays out of Plan's
  // first paint; a second open reuses the loaded module.
  const openSpec = (item: RequestPlanItem) => {
    import("../components/SpecModal")
      .then((m) => setSpec({ slug: item.slug, title: item.summary, Modal: m.SpecModal }))
      .catch((e) => setError(String(e).replace("Error: ", "")));
  };

  const commit = async (included: (number | string)[], excluded: (number | string)[], days = capacity,
                        overrides?: Record<string, PlanOverride>) => {
    // `saving` only disables the buttons on the NEXT render, so two fast clicks
    // both read the same pre-mutation plan and the second overwrote the first —
    // one dropped item silently reappeared with no explanation. This ref is set
    // synchronously, so the second call is refused before it can read stale ids.
    if (!reviewer || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      setPlan(await api.saveBacklogPlan({ included, excluded, capacity_days: days, overrides }, kind));
      setError(null);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  if (loading && !plan) return <Centered>Ranking your open problems…</Centered>;
  if (!plan) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't build a plan" detail={error ?? undefined}
                    onRetry={() => load()} />
      </div>
    );
  }

  // Only explicit choices are overrides. Pinning every automatic proposal and
  // excluding all overflow prevents the planner from refilling or resizing.
  const inIds = plan.included ?? [];
  const outIds = plan.excluded ?? [];
  const drop = (id: number | string) => commit(inIds.filter((x) => x !== id), [...outIds, id]);
  const add = (id: number | string) => commit([...inIds, id], outIds.filter((x) => x !== id));

  // One item's estimate changed: send the WHOLE override map (the server
  // replaces it wholesale), with this item's entry merged or removed.
  const setOverride = (id: number | string, patch: PlanOverride | null) => {
    const all = { ...(plan.overrides ?? {}) };
    const key = String(id);
    const merged = patch == null ? {} : { ...(all[key] ?? {}), ...patch };
    const clean = Object.fromEntries(
      Object.entries(merged).filter(([, v]) => v != null)) as PlanOverride;
    if (Object.keys(clean).length) all[key] = clean;
    else delete all[key];
    commit(inIds, outIds, capacity, all);
  };
  const segments = plan.segments ?? [];

  const empty = plan.proposed.length === 0 && plan.deferred.length === 0;
  const counts = plan.counts;
  const tabs = KINDS.map((k) => ({
    key: k.key,
    label: counts && k.key !== "all" ? `${k.label} · ${counts[k.key]}` : k.label,
  }));
  const row = (i: PlanItem, inPlan: boolean) => {
    const id = keyOf(i);
    const common = {
      inPlan, busy: saving, canEdit: reviewer, segments,
      onToggle: () => (inPlan ? drop(id) : add(id)),
      onOverride: (p: PlanOverride | null) => setOverride(id, p),
      note: plan.notes[String(id)],
    };
    return isRequest(i)
      ? <RequestRow key={i.slug} item={i} onSpec={() => openSpec(i)} {...common} />
      : <Row key={i.investigation_id} item={i} onOpen={onOpenInvestigation} {...common} />;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Plan"
        product={plan.product}
        subtitle={SUBTITLE[kind]}
        back={{ label: backLabel, onClick: onBack }}
        right={
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>
            {plan.owned ? "YOUR PLAN" : "PROPOSED"} · {plan.generated}
          </span>
        }
      />
      <SubTabs tabs={tabs} active={kind} onChange={setKind} label="What to plan" />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {empty ? (
          <EmptyState
            title={kind === "requests" ? `No repeated requests from ${plan.product || "this product"} users yet`
              : `Nothing to plan yet for ${plan.product || "this product"}`}
            body={kind === "requests"
              ? "Requests come from 3–5★ reviews that ask for something (“please add…”, “I wish…”). Once two or more ask for the same thing it shows up here, ranked by demand per engineer-day."
              : "A problem enters the plan once a case resolves with a finding and no verified fix. Investigate something and it shows up here, ranked by what each engineer-day buys you."}
            action="Go to Cases"
            onAction={onGoCases}
          />
        ) : (
          <>
            {/* capacity + the outcome the plan projects */}
            <div style={{ maxWidth: MEASURE, display: "flex", gap: S[5], flexWrap: "wrap",
                          alignItems: "flex-end", padding: `${S[4]} ${S[5]}`, background: C.card,
                          border: `1px solid ${C.border2}`, borderRadius: R.card, marginBottom: S[5] }}>
              <div>
                <Label style={{ marginBottom: S[1] }}>CAPACITY (ENGINEER-DAYS)</Label>
                <input
                  aria-label="Capacity in engineer-days"
                  type="number" min={1} max={200} value={capacity}
                  disabled={!reviewer || saving}
                  onChange={(e) => setCapacity(Number(e.target.value))}
                  // Clamp on commit. Number("") is 0 and Number("abc") is NaN,
                  // and min/max are not enforced by React — clearing the field
                  // saved capacity_days: 0, which emptied the plan and rendered
                  // "COMMITTED 14d OF 0d" with no error anywhere.
                  onBlur={() => {
                    const safe = Number.isFinite(capacity) && capacity >= 1
                      ? Math.min(200, Math.round(capacity))
                      : 1;
                    if (safe !== capacity) setCapacity(safe);
                    commit(inIds, outIds, safe);
                  }}
                  style={{ width: 90, background: C.bgRaised, border: `1px solid ${C.border3}`,
                           borderRadius: R.control, color: C.text, fontFamily: mono, fontSize: T.md,
                           padding: `${S[2]} ${S[2]}` }}
                />
              </div>
              <div style={{ flex: 1, minWidth: 220 }}>
                <Label style={{ marginBottom: S[2] }}>
                  COMMITTED {plan.committed_days}d OF {plan.capacity_days}d
                </Label>
                <Bar pct={(plan.committed_days / Math.max(1, plan.capacity_days)) * 100}
                     color={plan.committed_days > plan.capacity_days ? C.bad : C.accent}
                     height={7} />
              </div>
              <Stat label="PROJECTED RECOVERY"
                    hint="Estimated rating gain if every item in this plan is fixed, based on each finding's share of recent negative reviews."
                    value={plan.projected_stars > 0 ? `+${plan.projected_stars.toFixed(2)}★` : "—"}
                    color={plan.projected_stars > 0 ? C.good : C.muted} />
              {kind !== "requests" && (
                <Stat label="RESOLUTION RATE"
                      value={`${Math.round(plan.resolution_rate * 100)}%`} color={C.text} />
              )}
              {kind !== "requests" && plan.median_fix_days != null && (
                <Stat label="MEDIAN FIX" value={`${plan.median_fix_days}d`} color={C.muted} />
              )}
            </div>

            {plan.unknown_effort > 0 && (
              <div style={{ maxWidth: MEASURE, marginBottom: S[4], padding: `${S[2]} ${S[4]}`,
                            border: `1px solid ${C.border3}`, background: C.card2,
                            borderRadius: R.control, fontSize: T.sm, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
                {plan.unknown_effort} item{plan.unknown_effort === 1 ? " has" : "s have"} no
                effort signal yet — {kind === "bugs" ? "no linked issue labels and no fix history to learn from"
                  : "nothing says how big a request is until you set it"}. They
                use a default estimate of {plan.proposed.concat(plan.deferred).find((i) => !i.effort.known)?.effort.days ?? 5}d,
                which counts toward your capacity — treat their rank as provisional.
              </div>
            )}

            {error && (
              <div style={{ maxWidth: MEASURE, marginBottom: S[4], padding: `${S[2]} ${S[3]}`,
                            border: `1px solid ${C.bad}55`, background: `${C.bad}14`,
                            borderRadius: R.control, fontSize: T.sm, color: C.bad }}>{error}</div>
            )}

            <Label as="h2" style={{ marginBottom: S[1], color: C.accent }}>
              THIS QUARTER · {plan.proposed.length}
            </Label>
            <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 12px", lineHeight: "var(--el-lh-normal)" }}>
              {kind === "bugs" ? "Ranked by value per engineer-day."
                : kind === "requests" ? `Ranked by demand per engineer-day. ${plan.request_weight?.why ?? ""}`
                : "Bugs and requests are measured differently, so each is scored as a share of the best of its kind."}
              {" "}EchoLens proposes; you decide — drop anything and
              the plan re-fills around your choice.{reviewer && " Adjust effort, impact or segment on any item and the ranking updates at once."}
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
              {plan.proposed.map((i) => row(i, true))}
            </div>

            {plan.deferred.length > 0 && (
              <>
                <Label style={{ margin: "26px 0 12px", color: C.faint }}>
                  DIDN'T FIT · {plan.deferred.length}
                </Label>
                <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
                  {plan.deferred.map((i) => row(i, false))}
                </div>
              </>
            )}
          </>
        )}
      </div>
      {spec && <spec.Modal slug={spec.slug} title={spec.title} onClose={() => setSpec(null)} />}
    </div>
  );
}

function Stat({ label, value, color, hint }: { label: string; value: string; color: string; hint?: string }) {
  return (
    <div title={hint}>
      <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint }}>{label}</div>
      <div style={{ fontSize: T.xl, fontWeight: 700, fontFamily: mono, color, marginTop: S[1] }}>{value}</div>
      {hint && (
        <div style={{ fontSize: T.micro, color: C.dim, marginTop: S[1], maxWidth: 200,
                      lineHeight: "var(--el-lh-snug)" }}>
          Rating gain if the whole plan ships
        </div>
      )}
    </div>
  );
}

function Row({ item, inPlan, busy, canEdit, onToggle, onOpen, note, segments, onOverride }: {
  item: BacklogItem;
  inPlan: boolean;
  busy: boolean;
  canEdit: boolean;
  onToggle: () => void;
  onOpen: (id: number, status?: string) => void;
  note?: string;
  segments: PlanSegment[];
  onOverride: (patch: PlanOverride | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const band = BAND[item.severity.band] ?? C.dim;
  return (
    <div className="el-card" style={{ display: "flex", gap: S[3], padding: `${S[3]} ${S[4]}`,
                                      opacity: inPlan ? 1 : 0.74 }}>
      <div style={{ width: 3, borderRadius: R.sm, background: band, flex: "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>#{item.rank}</span>
          <button
            onClick={() => onOpen(item.investigation_id, "resolved")}
            className="el-btn"
            style={{ fontSize: T.md, fontWeight: 600, color: C.text,
                     flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
            {item.summary}
          </button>
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.card,
                         background: `${band}1a`, border: `1px solid ${band}55`, color: band }}>
            {item.effort.overridden ? `${item.effort.days}d · set by you`
              : item.effort.known ? `${item.effort.days}d` : `est. ${item.effort.days}d (default)`}
          </span>
          {item.segment && <SegmentPill segment={item.segment} />}
        </div>

        <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
          {defenceLine(item)}
        </div>

        {note && (
          <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[1], fontStyle: "italic" }}>
            “{note}”
          </div>
        )}

        <div style={{ display: "flex", gap: S[3], marginTop: S[2], flexWrap: "wrap" }}>
          <button onClick={() => setOpen((o) => !o)} className="el-btn"
            style={{ fontFamily: mono, fontSize: T.micro, color: C.dim }}>
            <Icon name={open ? "chevronDown" : "chevronRight"} size={11} />
            {open ? "hide evidence" : `${item.evidence_count} evidence`}
          </button>
          {item.projected.confident && (
            <span style={{ fontFamily: mono, fontSize: T.micro, color: C.good }}>
              +{item.projected.stars.toFixed(2)}★ if fixed
            </span>
          )}
        </div>

        <Estimates item={item} canEdit={canEdit} busy={busy} segments={segments}
                   onOverride={onOverride} />

        {open && (
          <div style={{ marginTop: S[2], paddingLeft: 10, borderLeft: `2px solid ${C.border3}`,
                        display: "flex", flexDirection: "column", gap: S[1] }}>
            <div style={{ fontSize: T.sm, color: C.dim, lineHeight: "var(--el-lh-normal)" }}>
              {item.projected.basis}
            </div>
            <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, wordBreak: "break-all" }}>
              {item.evidence_refs.join(" · ") || "no cited refs"}
            </div>
          </div>
        )}
      </div>

      {canEdit && (
        <button onClick={onToggle} disabled={busy} className="el-btn"
          style={{ background: "transparent", color: inPlan ? C.dim : C.accent,
                   border: `1px solid ${inPlan ? C.border3 : "var(--el-accent-line)"}`,
                   borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.sm, fontFamily: sans,
                   cursor: busy ? "wait" : "pointer", flex: "none", alignSelf: "center" }}>
          {inPlan ? "Drop" : "Add"}
        </button>
      )}
    </div>
  );
}

/** Rebuilt from the structured fields, like defenceLine for bugs. */
function requestLine(i: RequestPlanItem): string {
  const bits = [`${i.count} requesting ${plural(i.count, "review")}`];
  if (i.avg_rating != null) bits.push(`avg ${i.avg_rating}★`);
  if (i.happy_count) bits.push(`${i.happy_count} at 4–5★ count extra`);
  bits.push(effortLabel(i));
  if (i.impact?.overridden) bits.push(`impact ×${i.impact.factor} (set by you)`);
  if (i.segment) bits.push(`×${i.segment.factor} ${i.segment.label.toLowerCase()} (set by you)`);
  return bits.join(" · ");
}

/** A feature-request theme on the plan: demand, quotes, and a spec to hand off. */
function RequestRow({ item, inPlan, busy, canEdit, onToggle, onSpec, note, segments, onOverride }: {
  item: RequestPlanItem;
  inPlan: boolean;
  busy: boolean;
  canEdit: boolean;
  onToggle: () => void;
  onSpec: () => void;
  note?: string;
  segments: PlanSegment[];
  onOverride: (patch: PlanOverride | null) => void;
}) {
  return (
    <div className="el-card" style={{ display: "flex", gap: S[3], padding: `${S[3]} ${S[4]}`,
                                      opacity: inPlan ? 1 : 0.74 }}>
      <div style={{ width: 3, borderRadius: R.sm, background: C.good, flex: "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>#{item.rank}</span>
          <span style={{ fontSize: T.md, fontWeight: 600, color: C.text, flex: 1, minWidth: 0,
                         overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {item.summary}
          </span>
          <span style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.card,
                         background: `${C.good}1a`, border: `1px solid ${C.good}55`, color: C.good }}>
            REQUEST · {item.effort.overridden ? `${item.effort.days}d · set by you`
              : item.effort.known ? `${item.effort.days}d` : `est. ${item.effort.days}d (default)`}
          </span>
          {item.segment && <SegmentPill segment={item.segment} />}
        </div>

        <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
          {requestLine(item)}
        </div>

        {item.verbatims.map((q) => (
          <div key={q} title={q}
               style={{ fontSize: T.sm, color: C.text3, marginTop: S[1], fontStyle: "italic",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            “{q}”
          </div>
        ))}

        {note && (
          <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[1] }}>Note: {note}</div>
        )}

        <div style={{ display: "flex", gap: S[3], marginTop: S[2], flexWrap: "wrap" }}>
          <button onClick={onSpec} className="el-btn"
            style={{ fontFamily: mono, fontSize: T.micro, color: C.accent }}>
            <Icon name="external" size={11} /> Write spec
          </button>
        </div>

        <Estimates item={item} canEdit={canEdit} busy={busy} segments={segments}
                   onOverride={onOverride} />
      </div>

      {canEdit && (
        <button onClick={onToggle} disabled={busy} className="el-btn"
          style={{ background: "transparent", color: inPlan ? C.dim : C.accent,
                   border: `1px solid ${inPlan ? C.border3 : "var(--el-accent-line)"}`,
                   borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.sm, fontFamily: sans,
                   cursor: busy ? "wait" : "pointer", flex: "none", alignSelf: "center" }}>
          {inPlan ? "Drop" : "Add"}
        </button>
      )}
    </div>
  );
}

/** A reviewer-set priority segment. The tooltip says what it does to value. */
function SegmentPill({ segment }: { segment: PlanSegment }) {
  return (
    <span title={segment.why}
      style={{ fontFamily: mono, fontSize: T.micro, padding: `0 ${S[2]}`, borderRadius: R.pill,
               background: C.accentBg, border: `1px solid ${C.accentLine}`, color: C.accent,
               cursor: "help" }}>
      {segment.label} · ×{segment.factor}
    </span>
  );
}

const IMPACT_LABEL: Record<number, string> = {
  1: "1 · minimal", 2: "2 · low", 3: "3 · medium", 4: "4 · high", 5: "5 · critical",
};

function SetByYou() {
  return <span style={{ fontFamily: mono, fontSize: T.micro, color: C.accent }}>set by you</span>;
}

const ctl = {
  background: C.bgRaised, border: `1px solid ${C.border3}`, borderRadius: R.control,
  color: C.text, fontFamily: sans, fontSize: T.sm, padding: `2px ${S[2]}`,
} as const;

/**
 * Inline estimate overrides for a reviewer: effort (engineer-days), impact
 * (1–5) and a manual priority segment. Each change saves with the plan and the
 * server re-ranks immediately; overridden values are marked "set by you".
 */
function Estimates({ item, canEdit, busy, segments, onOverride }: {
  item: PlanItem;
  canEdit: boolean;
  busy: boolean;
  segments: PlanSegment[];
  onOverride: (patch: PlanOverride | null) => void;
}) {
  if (!canEdit) return null;
  const days = item.effort.days;
  const step = days <= 2 ? 0.5 : 1;
  const bump = (dir: 1 | -1) => {
    const next = Math.round(Math.max(0.5, Math.min(365, days + dir * step)) * 2) / 2;
    if (next !== days) onOverride({ effort_days: next });
  };
  const impact = item.impact;
  const touched = item.effort.overridden || impact?.overridden || item.segment != null;
  const estimated = item.effort.estimated;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: S[4], alignItems: "center", marginTop: S[2],
                  fontSize: T.sm, color: C.dim }}>
      <div style={{ display: "flex", alignItems: "center", gap: S[1] }}
           title={estimated ? `EchoLens estimated ${estimated.days}d (${estimated.basis})` : item.effort.basis}>
        <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".08em" }}>EFFORT</span>
        <button className="el-btn" style={ctl} disabled={busy || days <= 0.5}
          aria-label="Decrease effort" onClick={() => bump(-1)}>−</button>
        <span style={{ fontFamily: mono, color: C.text, minWidth: 34, textAlign: "center" }}>{days}d</span>
        <button className="el-btn" style={ctl} disabled={busy || days >= 365}
          aria-label="Increase effort" onClick={() => bump(1)}>+</button>
        {item.effort.overridden && <SetByYou />}
      </div>
      {impact && (
        <label style={{ display: "flex", alignItems: "center", gap: S[1] }}
               title="Impact on a 1–5 scale. Each step doubles or halves value; the default comes from severity.">
          <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".08em" }}>IMPACT</span>
          <select value={impact.level} disabled={busy} style={ctl}
            onChange={(e) => {
              const lvl = Number(e.target.value);
              onOverride({ impact: lvl === impact.default ? null : lvl });
            }}>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {IMPACT_LABEL[n]}{n === impact.default ? " (measured)" : ""}
              </option>
            ))}
          </select>
          {impact.overridden && <SetByYou />}
        </label>
      )}
      {segments.length > 0 && (
        <label style={{ display: "flex", alignItems: "center", gap: S[1] }}
               title={item.segment?.why ?? "EchoLens has no data on who pays. Flag an item that hits a priority segment to multiply its value."}>
          <span style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".08em" }}>SEGMENT</span>
          <select value={item.segment?.key ?? ""} disabled={busy} style={ctl}
            onChange={(e) => onOverride({ segment: e.target.value || null })}>
            <option value="">None</option>
            {segments.map((s) => (
              <option key={s.key} value={s.key}>{s.label} (×{s.factor})</option>
            ))}
          </select>
        </label>
      )}
      {touched && (
        <button className="el-btn" disabled={busy} onClick={() => onOverride(null)}
          style={{ fontFamily: mono, fontSize: T.micro, color: C.dim }}>
          <Icon name="retry" size={10} /> reset to EchoLens's estimate
        </button>
      )}
    </div>
  );
}
