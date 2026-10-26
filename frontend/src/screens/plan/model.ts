import type { PlanItem, PlanKind, PlanOverride, QuarterPlan } from "../../api";

export const isRequest = (item: PlanItem) => item.kind === "request";
export const keyOf = (item: PlanItem): number | string => item.kind === "request" ? item.slug : item.investigation_id;
// Same nonnegative half-up rule as backlog._plan_round, including exact ties.
const roundRank=(value:number,digits:number)=>Math.floor(value*10**digits+.5)/10**digits;
export interface Draft {
  capacity_days: number; included: (number | string)[]; excluded: (number | string)[];
  overrides: Record<string, PlanOverride>; kind: PlanKind;
}
export function fromPlan(plan: QuarterPlan, kind: PlanKind = "bugs"): Draft {
  return { capacity_days:Math.max(10,Math.min(60,plan.capacity_days)), included:plan.included ?? [],
    excluded:plan.excluded ?? [], overrides:plan.overrides ?? {}, kind };
}
export function preview(plan: QuarterPlan, draft: Draft) {
  const pool = [...plan.proposed, ...plan.deferred].filter(i => draft.kind === "all" || (i.kind === "request" ? draft.kind === "requests" : draft.kind === "bugs"));
  const items = pool.map(item => {
    const ov = draft.overrides[String(keyOf(item))] ?? {};
    const estimated=item.effort.estimated ?? item.effort;
    const days = ov.effort_days ?? estimated.days;
    const known=ov.effort_days!=null || estimated.known;
    const impact = item.impact;
    const level = ov.impact ?? impact?.default ?? 3;
    const factor = (plan.impact_scale?.[String(level)] ?? 1) / (plan.impact_scale?.[String(impact?.default ?? 3)] ?? 1);
    const segment = plan.segments?.find(s => s.key === ov.segment) ?? null;
    const oldDivisor=item.kind === "request" || item.effort.known ? item.effort.days : 1;
    const divisor=item.kind === "request" || known ? Math.max(.5,days) : 1;
    const value = item.base_value ?? item.value_per_day * oldDivisor / Math.max(.001,(impact?.factor ?? 1)*(item.segment?.factor ?? 1));
    return { ...item, effort:{...item.effort, days, known, basis:ov.effort_days!=null?"set by you":estimated.basis, overridden:ov.effort_days != null},
      impact:impact ? {...impact,level,factor,overridden:ov.impact != null} : undefined, segment,
      value_per_day:roundRank(value * factor * (segment?.factor ?? 1) / divisor,2) } as PlanItem;
  });
  const max = (request: boolean) => Math.max(1e-9,...items.filter(i=>isRequest(i)===request).map(i=>i.value_per_day));
  const bestBug=max(false), bestRequest=max(true);
  const score = (i: PlanItem) => draft.kind === "all" ? roundRank(i.value_per_day/(isRequest(i)?bestRequest:bestBug),3) : i.value_per_day;
  items.sort((a,b)=>score(b)-score(a) || Number(isRequest(a))-Number(isRequest(b)) || b.value_per_day-a.value_per_day || (a.tie_order??a.rank)-(b.tie_order??b.rank));
  const excluded=new Set(draft.excluded), byId=new Map(items.map(i=>[keyOf(i),i]));
  const pins = draft.included.filter(id=>byId.has(id) && !excluded.has(id));
  for(const item of items) if(item.kind !== "request" && (item as PlanItem & {decision?:{decision:string}}).decision?.decision === "fix_now" && !excluded.has(keyOf(item)) && !pins.includes(keyOf(item))) pins.push(keyOf(item));
  const proposed=pins.map(id=>byId.get(id)!);
  let used=proposed.reduce((n,i)=>n+i.effort.days,0);
  for(const item of items) if(!excluded.has(keyOf(item)) && !pins.includes(keyOf(item)) && used+item.effort.days<=draft.capacity_days){ proposed.push(item); used+=item.effort.days; }
  const selected=new Set(proposed.map(keyOf));
  return { ...plan, proposed, deferred:items.filter(i=>!selected.has(keyOf(i))), capacity_days:draft.capacity_days,
    committed_days:Math.round(used*10)/10, projected_stars:Math.round(proposed.reduce((n,i)=>n+i.projected.stars,0)*100)/100,
    unknown_effort:items.filter(i=>!i.effort.known).length,
    complaints:proposed.reduce((n,i)=>n+(i.kind === "request" ? 0 : i.volume),0),
    request_reviews:proposed.reduce((n,i)=>n+(i.kind === "request" ? i.count : 0),0) };
}
export function planHeadline(plan: Pick<QuarterPlan,"proposed"|"projected_stars"> & Partial<Pick<QuarterPlan,"deferred"|"capacity_days">>): string {
  const bugs=plan.proposed.filter(i=>i.kind !== "request").length;
  if(!plan.proposed.length) {
    if(!plan.deferred?.length) return "No problems or requests are ready to plan.";
    return plan.deferred.every(item=>item.effort.days > (plan.capacity_days ?? 0))
      ? `No item fits in ${plan.capacity_days} developer-days.` : "No items are selected for this quarter yet.";
  }
  if(!bugs) return plan.proposed.length === 1 ? "One request fits your next release." : `${plan.proposed.length} requests fit your next release.`;
  return `Fix ${bugs === 1 ? "this problem" : `these ${bugs}`} this quarter${plan.projected_stars>0 ? ` — ${bugs === 1 ? "it" : "they"} could prevent about ${plan.projected_stars.toFixed(2)}★ of further drift.` : "."}`;
}
export function mergeReply(base: QuarterPlan, reply: QuarterPlan): QuarterPlan {
  const kept=[...base.proposed,...base.deferred].filter(i=>reply.kind!=="all" && (isRequest(i)?"requests":"bugs")!==reply.kind);
  const map=new Map(kept.map(i=>[keyOf(i),i]));
  for(const i of [...reply.proposed,...reply.deferred])map.set(keyOf(i),i);
  return {...reply,proposed:[...map.values()],deferred:[]};
}
