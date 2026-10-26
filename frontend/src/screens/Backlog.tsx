import { useState } from "react";
import { PlanItem, PlanOverride, RequestPlanItem, api, canReview, isGuest } from "../api";
import { EmptyState, PillTabs, SerifHeadline, StatTile } from "../components/casefile";
import { useAsync } from "../hooks";
import { Button, ErrorState, ScreenBody, Skeleton } from "../ui";
import { PlanRow } from "./plan/PlanRow";
import { PlanExport } from "./plan/PlanExport";
import { keyOf, planHeadline, preview } from "./plan/model";
import { usePlan } from "./plan/usePlan";
import "./plan/plan.css";

type SpecModalType=typeof import("../components/SpecModal").SpecModal;
interface Props { onOpenInvestigation:(id:number,status?:string)=>void;onGoCases:()=>void;onBack:()=>void;backLabel:string }
export function Backlog({onOpenInvestigation,onGoCases,onBack,backLabel}:Props) {
  const state=usePlan();
  const cases=useAsync(()=>api.cases(),[]);
  const [spec,setSpec]=useState<{item:RequestPlanItem;Modal:SpecModalType}|null>(null);
  const reviewer=canReview()&&!isGuest();
  if(!state.plan||!state.draft)return <div className="plan-v2"><ScreenBody>{state.error?<ErrorState title="Couldn't build your plan" detail={state.error} onRetry={state.reload}/>:<Skeleton rows={5} height={64}/>}</ScreenBody></div>;
  const draft=state.draft,plan=preview(state.plan,draft);
  const hunches=(cases.data?.cases??[]).filter(c=>c.id!=null&&c.status==="needs_human");
  const setOverride=(id:number|string,patch:PlanOverride|null)=>{
    const overrides={...draft.overrides};
    if(patch==null)delete overrides[String(id)];else overrides[String(id)]={...overrides[String(id)],...patch};
    state.change({...draft,overrides});
  };
  const toggle=(item:PlanItem,inPlan:boolean)=>{
    const id=keyOf(item);
    state.change({...draft,included:inPlan?draft.included.filter(x=>x!==id):[...draft.included.filter(x=>x!==id),id],
      excluded:inPlan?[...draft.excluded.filter(x=>x!==id),id]:draft.excluded.filter(x=>x!==id)});
  };
  const open=async(item:PlanItem)=>{
    if(reviewer&&state.pending&&!await state.flush())return;
    if(item.kind === "request"){
      const {SpecModal}=await import("../components/SpecModal");setSpec({item,Modal:SpecModal});
    }else onOpenInvestigation(item.investigation_id,"resolved");
  };
  const row=(item:PlanItem,inPlan:boolean)=><PlanRow key={keyOf(item)} item={item} inPlan={inPlan} editable={reviewer}
    segments={plan.segments??[]} note={plan.notes[String(keyOf(item))]} caseRow={item.kind === "request"?undefined:cases.data?.cases.find(r=>r.id===item.investigation_id)}
    onOpen={()=>void open(item)} onToggle={()=>toggle(item,inPlan)} onOverride={p=>setOverride(keyOf(item),p)}/>;
  const exportReady=async()=>{state.change({...draft});return state.flush();};
  return <div className="plan-v2"><ScreenBody><div className="pl-page">
    <div className="pl-intro"><div className="pl-actions"><Button variant="quiet" onClick={onBack}>← {backLabel === "Cases" ? "All problems" : backLabel}</Button><span className="pl-muted">{plan.product} · this quarter</span></div>
      <SerifHeadline>{planHeadline(plan)}</SerifHeadline>
      <p className="pl-muted">An estimate of future complaints avoided, not an instant rating gain. Existing low ratings stay until they age out.</p>
    </div>
    <PillTabs label="What to plan" value={draft.kind} onChange={kind=>state.change({...draft,kind})} panelId="plan-items"
      tabs={[{id:"bugs",label:"Bugs to fix"},{id:"requests",label:"Users are asking for"},{id:"all",label:"Everything"}]}/>
    <section className="pl-capacity" aria-label="Plan capacity">
      <label htmlFor="plan-capacity">Your capacity <strong>{draft.capacity_days} developer-days</strong>
        <input id="plan-capacity" type="range" min={10} max={60} step={1} value={draft.capacity_days}
          aria-valuetext={`${draft.capacity_days} developer-days this quarter`} onChange={e=>state.change({...draft,capacity_days:Number(e.target.value)})}/>
      </label>
      <div className="pl-stats" aria-live="polite">
        <StatTile value={`${plan.proposed.length} items`} caption={`${plan.committed_days} of ${draft.capacity_days} developer-days used`}/>
        <StatTile value={draft.kind === "requests"?plan.request_reviews:plan.complaints} caption={draft.kind === "requests"?"requesting reviews represented by this plan":"complaint matches addressed; reviews may overlap"}/>
        <StatTile value={plan.projected_stars>0?`~${plan.projected_stars.toFixed(2)}★`:"—"} caption={plan.projected_stars>0?"further 30-day rating drift this plan could prevent":"no rating benefit measured for this selection"}/>
      </div>
      <p className="pl-muted" role="status">{!reviewer?"Preview only. A reviewer can save and send the plan.":state.saving?"Saving your plan…":state.pending?"Edits ready to save…":plan.owned?"Plan saved.":"Suggested plan — your edits will save automatically."}
        {plan.committed_days>draft.capacity_days&&" Your pinned choices exceed capacity. Move an item to Next time or raise capacity."}</p>
      {state.error&&<p role="alert">{state.error} <Button variant="quiet" onClick={()=>void state.flush()}>Retry save</Button></p>}
    </section>
    <div id="plan-items" role="tabpanel" aria-label="Planned items" tabIndex={0} className="pl-stack">
      <SerifHeadline as="h2" size="section">In the plan · {plan.proposed.length}</SerifHeadline>
      {plan.proposed.length?plan.proposed.map(i=>row(i,true)):<EmptyState title="Nothing fits this selection yet." action={<Button onClick={onGoCases}>See all problems</Button>}>
        {plan.deferred.length?"Raise capacity or add one of the items below. Your explicit choices stay yours.":draft.kind === "requests"?"Repeated requests from your reviews will appear here. Connect feedback or check your sources to bring more in.":hunches.length?"Only proven problems are planned. These were looked into but are still hunches — approve one and it can be planned:":"Investigate a review spike first. Problems with a finding and no checked fix become planning candidates."}
        {/* "No problems ready" with two hunches sitting one screen away gave no next step. */}
        {!plan.deferred.length&&draft.kind!=="requests"&&hunches.length>0&&<span style={{display:"flex",flexDirection:"column",gap:6,marginTop:12,alignItems:"center"}}>
          {hunches.slice(0,5).map(h=><Button key={h.id} size="sm" variant="ghost" onClick={()=>onOpenInvestigation(h.id!,h.status)}>#{h.id} · {h.title}</Button>)}
        </span>}</EmptyState>}
      <section className="pl-cut pl-stack"><SerifHeadline as="h2" size="section">Next time · {plan.deferred.length}</SerifHeadline>
        {plan.deferred.length?plan.deferred.map(i=>row(i,false)):<p className="pl-muted">Everything in this selection fits. Lower capacity to compare a smaller plan.</p>}
      </section>
    </div>
    {reviewer&&<PlanExport kind={draft.kind} flush={exportReady} count={plan.proposed.length}/>}
    <details className="pl-context"><summary>How this plan is ranked · history and assumptions</summary><div className="pl-stack">
      <p className="pl-muted">Problems are ranked by impact for each developer-day. Requests use demand for each developer-day. Everything compares each item with the best of its own kind. Your pins and exclusions win over automatic choices.</p>
      <p className="pl-muted">{plan.unknown_effort} items use an estimated effort. Set effort, impact or priority group on a row to adjust it. No requesting review is counted as a promised rating improvement.</p>
      <p className="pl-muted">{Math.round(plan.resolution_rate*100)}% of resolved problems led to a checked fix.{plan.median_fix_days!=null&&` Past fixes took a median of ${plan.median_fix_days} days.`}</p>
      {plan.request_weight&&<p className="pl-muted">{plan.request_weight.why}</p>}
      <Button variant="quiet" onClick={onGoCases}>Review all problems</Button>
    </div></details>
  </div>{spec&&<spec.Modal slug={spec.item.slug} title={spec.item.summary} onClose={()=>setSpec(null)}/>}</ScreenBody></div>;
}
