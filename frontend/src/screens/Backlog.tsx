import { useEffect, useState } from "react";
import { BacklogItem, QuarterPlan, api, canReview } from "../api";
import { C, mono, sans } from "../theme";
import { Bar, Centered, Label, ScreenHeader } from "../ui";

const BAND: Record<string, string> = { high: C.bad, medium: C.accent, low: C.dim };

interface Props {
  onOpenInvestigation: (id: number, status?: string) => void;
}

/**
 * The quality backlog — EchoLens proposes a plan, the PM edits and owns it.
 *
 * Ranked by impact-per-effort rather than impact, because a slightly smaller
 * problem that costs a day genuinely should beat one that costs three weeks.
 * Every line shows the arithmetic that placed it there.
 */
export function Backlog({ onOpenInvestigation }: Props) {
  const [plan, setPlan] = useState<QuarterPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
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
    if (!reviewer) return;
    setSaving(true);
    try {
      setPlan(await api.saveBacklogPlan({ included, excluded, capacity_days: days }));
      setError(null);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !plan) return <Centered>Ranking your open problems…</Centered>;
  if (error && !plan) return <Centered>{error}</Centered>;
  if (!plan) return <Centered>Backend unavailable.</Centered>;

  const inIds = plan.proposed.map((i) => i.investigation_id);
  const outIds = plan.deferred.map((i) => i.investigation_id);
  const drop = (id: number) => commit(inIds.filter((x) => x !== id), [...outIds, id]);
  const add = (id: number) => commit([...inIds, id], outIds.filter((x) => x !== id));

  const empty = plan.proposed.length === 0 && plan.deferred.length === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title={`Quality Backlog${plan.product ? ` · ${plan.product}` : ""}`}
        right={
          <span style={{ fontFamily: mono, fontSize: 11.5, color: C.muted }}>
            {plan.owned ? "YOUR PLAN" : "PROPOSED"} · {plan.generated}
          </span>
        }
      />
      <div style={{ flex: 1, overflow: "auto", padding: "22px 28px" }}>
        {empty ? (
          <div style={{ maxWidth: 720, padding: "30px 22px", border: `1px dashed ${C.border4}`,
                        borderRadius: 12, textAlign: "center", color: C.dim, fontSize: 13.5,
                        lineHeight: 1.6 }}>
            Nothing to plan yet — a problem enters the backlog once an investigation resolves
            with a finding and no verified fix. Investigate something from the Cases screen and
            it will show up here, ranked.
          </div>
        ) : (
          <>
            {/* capacity + the outcome the plan projects */}
            <div style={{ maxWidth: 980, display: "flex", gap: 22, flexWrap: "wrap",
                          alignItems: "flex-end", padding: "16px 20px", background: C.card,
                          border: `1px solid ${C.border2}`, borderRadius: 12, marginBottom: 22 }}>
              <div>
                <Label style={{ marginBottom: 6 }}>CAPACITY (ENGINEER-DAYS)</Label>
                <input
                  type="number" min={1} max={200} value={capacity}
                  disabled={!reviewer}
                  onChange={(e) => setCapacity(Number(e.target.value))}
                  onBlur={() => commit(inIds, outIds, capacity)}
                  style={{ width: 90, background: C.bgRaised, border: `1px solid ${C.border3}`,
                           borderRadius: 7, color: C.text, fontFamily: mono, fontSize: 14,
                           padding: "8px 10px" }}
                />
              </div>
              <div style={{ flex: 1, minWidth: 220 }}>
                <Label style={{ marginBottom: 7 }}>
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
              <div style={{ maxWidth: 980, marginBottom: 18, padding: "10px 15px",
                            border: `1px solid ${C.border3}`, background: C.card2,
                            borderRadius: 9, fontSize: 12.5, color: C.muted, lineHeight: 1.5 }}>
                ⓘ {plan.unknown_effort} item{plan.unknown_effort === 1 ? " has" : "s have"} no
                effort signal yet — no linked issue labels and no fix history to learn from. They're
                ranked on impact alone rather than on a guessed estimate.
              </div>
            )}

            {error && (
              <div style={{ maxWidth: 980, marginBottom: 16, padding: "10px 14px",
                            border: `1px solid ${C.bad}55`, background: `${C.bad}14`,
                            borderRadius: 8, fontSize: 12.5, color: C.bad }}>{error}</div>
            )}

            <Label style={{ marginBottom: 4, color: C.accent }}>
              THIS QUARTER · {plan.proposed.length}
            </Label>
            <p style={{ fontSize: 12.5, color: C.dim, margin: "0 0 12px", lineHeight: 1.55 }}>
              Ranked by value per engineer-day. EchoLens proposes; you decide — drop anything and
              the plan re-fills around your choice.
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 9, maxWidth: 980 }}>
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
                <div style={{ display: "flex", flexDirection: "column", gap: 9, maxWidth: 980 }}>
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
      <div style={{ fontFamily: mono, fontSize: 9, letterSpacing: ".1em", color: C.faint }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, fontFamily: mono, color, marginTop: 5 }}>{value}</div>
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
    <div className="el-card" style={{ display: "flex", gap: 13, padding: "14px 17px",
                                      opacity: inPlan ? 1 : 0.74 }}>
      <div style={{ width: 3, borderRadius: 2, background: band, flex: "none" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontFamily: mono, fontSize: 11, color: C.faint }}>#{item.rank}</span>
          <span
            onClick={() => onOpen(item.investigation_id, "resolved")}
            className="el-btn"
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter") onOpen(item.investigation_id, "resolved"); }}
            style={{ fontSize: 14, fontWeight: 600, color: C.text, cursor: "pointer",
                     flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
            {item.summary}
          </span>
          <span style={{ fontFamily: mono, fontSize: 10.5, padding: "2px 8px", borderRadius: 10,
                         background: `${band}1a`, border: `1px solid ${band}55`, color: band }}>
            {item.effort.days}d
          </span>
        </div>

        <div style={{ fontSize: 12, color: C.muted, marginTop: 6, lineHeight: 1.5 }}>
          {item.defence}
        </div>

        {note && (
          <div style={{ fontSize: 12.5, color: C.text3, marginTop: 6, fontStyle: "italic" }}>
            “{note}”
          </div>
        )}

        <div style={{ display: "flex", gap: 12, marginTop: 8, flexWrap: "wrap" }}>
          <span onClick={() => setOpen((o) => !o)} className="el-btn" role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter") setOpen((o) => !o); }}
            style={{ fontFamily: mono, fontSize: 10.5, color: C.dim, cursor: "pointer" }}>
            {open ? "▾ hide evidence" : `▸ ${item.evidence_count} evidence`}
          </span>
          {item.projected.confident && (
            <span style={{ fontFamily: mono, fontSize: 10.5, color: C.good }}>
              +{item.projected.stars.toFixed(2)}★ if fixed
            </span>
          )}
        </div>

        {open && (
          <div style={{ marginTop: 9, paddingLeft: 10, borderLeft: `2px solid ${C.border3}`,
                        display: "flex", flexDirection: "column", gap: 5 }}>
            <div style={{ fontSize: 12, color: C.dim, lineHeight: 1.5 }}>
              {item.projected.basis}
            </div>
            <div style={{ fontFamily: mono, fontSize: 10.5, color: C.faint, wordBreak: "break-all" }}>
              {item.evidence_refs.join(" · ") || "no cited refs"}
            </div>
          </div>
        )}
      </div>

      {canEdit && (
        <button onClick={onToggle} disabled={busy} className="el-btn"
          style={{ background: "transparent", color: inPlan ? C.dim : C.accent,
                   border: `1px solid ${inPlan ? C.border3 : "rgba(240,166,60,.4)"}`,
                   borderRadius: 6, padding: "7px 12px", fontSize: 12.5, fontFamily: sans,
                   cursor: busy ? "wait" : "pointer", flex: "none", alignSelf: "center" }}>
          {inPlan ? "Drop" : "Add"}
        </button>
      )}
    </div>
  );
}
