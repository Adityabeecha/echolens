import { useEffect, useRef, useState } from "react";
import { BacklogItem, QuarterPlan, api, canReview } from "../api";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Bar, Centered, EmptyState, ErrorState, Label, ScreenHeader } from "../ui";
import { Icon } from "../components/Icon";

const BAND: Record<string, string> = { high: C.bad, medium: C.accent, low: C.dim };

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
  const reviewer = canReview();

  const load = (days?: number) => {
    setLoading(true);
    api
      .backlogPlan(days)
      .then((p) => {
        setPlan(p);
        setCapacity(p.capacity_days);
        setError(null);
      })
      .catch((e) => setError(String(e).replace("Error: ", "")))
      .finally(() => setLoading(false));
  };

  useEffect(() => load(), []);

  const commit = async (included: number[], excluded: number[], days = capacity) => {
    // `saving` only disables the buttons on the NEXT render, so two fast clicks
    // both read the same pre-mutation plan and the second overwrote the first —
    // one dropped item silently reappeared with no explanation. This ref is set
    // synchronously, so the second call is refused before it can read stale ids.
    if (!reviewer || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      setPlan(await api.saveBacklogPlan({ included, excluded, capacity_days: days }));
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

  const inIds = plan.proposed.map((i) => i.investigation_id);
  const outIds = plan.deferred.map((i) => i.investigation_id);
  const drop = (id: number) => commit(inIds.filter((x) => x !== id), [...outIds, id]);
  const add = (id: number) => commit([...inIds, id], outIds.filter((x) => x !== id));

  const empty = plan.proposed.length === 0 && plan.deferred.length === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Plan"
        product={plan.product}
        subtitle="Open problems, ranked by value per engineer-day"
        back={{ label: backLabel, onClick: onBack }}
        right={
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>
            {plan.owned ? "YOUR PLAN" : "PROPOSED"} · {plan.generated}
          </span>
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]}` }}>
        {empty ? (
          <EmptyState
            title={`Nothing to plan yet for ${plan.product || "this product"}`}
            body="A problem enters the plan once a case resolves with a finding and no verified fix. Investigate something and it shows up here, ranked by what each engineer-day buys you."
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
                  type="number" min={1} max={200} value={capacity}
                  disabled={!reviewer}
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
                    value={plan.projected_stars > 0 ? `+${plan.projected_stars.toFixed(2)}★` : "—"}
                    color={plan.projected_stars > 0 ? C.good : C.muted} />
              <Stat label="RESOLUTION RATE"
                    value={`${Math.round(plan.resolution_rate * 100)}%`} color={C.text} />
              {plan.median_fix_days != null && (
                <Stat label="MEDIAN FIX" value={`${plan.median_fix_days}d`} color={C.muted} />
              )}
            </div>

            {plan.unknown_effort > 0 && (
              <div style={{ maxWidth: MEASURE, marginBottom: S[4], padding: `${S[2]} ${S[4]}`,
                            border: `1px solid ${C.border3}`, background: C.card2,
                            borderRadius: R.control, fontSize: T.sm, color: C.muted, lineHeight: "var(--el-lh-normal)" }}>
                {plan.unknown_effort} item{plan.unknown_effort === 1 ? " has" : "s have"} no
                effort signal yet — no linked issue labels and no fix history to learn from. They're
                ranked on impact alone rather than on a guessed estimate.
              </div>
            )}

            {error && (
              <div style={{ maxWidth: MEASURE, marginBottom: S[4], padding: `${S[2]} ${S[3]}`,
                            border: `1px solid ${C.bad}55`, background: `${C.bad}14`,
                            borderRadius: R.control, fontSize: T.sm, color: C.bad }}>{error}</div>
            )}

            <Label style={{ marginBottom: S[1], color: C.accent }}>
              THIS QUARTER · {plan.proposed.length}
            </Label>
            <p style={{ fontSize: T.sm, color: C.dim, margin: "0 0 12px", lineHeight: "var(--el-lh-normal)" }}>
              Ranked by value per engineer-day. EchoLens proposes; you decide — drop anything and
              the plan re-fills around your choice.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
              {plan.proposed.map((i) => (
                <Row key={i.investigation_id} item={i} inPlan busy={saving}
                     canEdit={reviewer} onToggle={() => drop(i.investigation_id)}
                     onOpen={onOpenInvestigation} note={plan.notes[String(i.investigation_id)]} />
              ))}
            </div>

            {plan.deferred.length > 0 && (
              <>
                <Label style={{ margin: "26px 0 12px", color: C.faint }}>
                  DIDN'T FIT · {plan.deferred.length}
                </Label>
                <div style={{ display: "flex", flexDirection: "column", gap: S[2], maxWidth: MEASURE }}>
                  {plan.deferred.map((i) => (
                    <Row key={i.investigation_id} item={i} inPlan={false} busy={saving}
                         canEdit={reviewer} onToggle={() => add(i.investigation_id)}
                         onOpen={onOpenInvestigation} note={plan.notes[String(i.investigation_id)]} />
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div style={{ fontFamily: mono, fontSize: T.micro, letterSpacing: ".1em", color: C.faint }}>{label}</div>
      <div style={{ fontSize: T.xl, fontWeight: 700, fontFamily: mono, color, marginTop: S[1] }}>{value}</div>
    </div>
  );
}

function Row({ item, inPlan, busy, canEdit, onToggle, onOpen, note }: {
  item: BacklogItem;
  inPlan: boolean;
  busy: boolean;
  canEdit: boolean;
  onToggle: () => void;
  onOpen: (id: number, status?: string) => void;
  note?: string;
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
            {item.effort.days}d
          </span>
        </div>

        <div style={{ fontSize: T.sm, color: C.muted, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
          {item.defence}
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
                   border: `1px solid ${inPlan ? C.border3 : "rgba(240,166,60,.4)"}`,
                   borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.sm, fontFamily: sans,
                   cursor: busy ? "wait" : "pointer", flex: "none", alignSelf: "center" }}>
          {inPlan ? "Drop" : "Add"}
        </button>
      )}
    </div>
  );
}
