import { CaseRow, PlanItem, PlanOverride, PlanSegment } from "../../api";
import { ListRow, stampFor } from "../../components/casefile";
import { Button } from "../../ui";
import { keyOf } from "./model";

export function PlanRow({item,inPlan,editable,segments,note,caseRow,onOpen,onToggle,onOverride}: {
  item:PlanItem; inPlan:boolean; editable:boolean; segments:PlanSegment[]; note?:string; caseRow?:CaseRow;
  onOpen:()=>void; onToggle:()=>void; onOverride:(patch:PlanOverride|null)=>void;
}) {
  const request=item.kind === "request";
  const detail=request ? `${item.count} requesting reviews · ${item.happy_count} rated 4–5★`
    : `${item.volume} complaint matches · ${item.projected.confident?`could prevent ${item.projected.stars.toFixed(2)}★ more drift`:"rating effect not measured"}`;
  return <article className="pl-row" data-plan-key={String(keyOf(item))}>
    <ListRow variant={request?"request":stampFor(caseRow ?? item)} title={item.summary} detail={detail} onClick={onOpen}/>
    <div className="pl-row-controls">
      <span className="pl-effort">{editable && <Button size="sm" aria-label={`Decrease effort for ${item.summary}`} disabled={item.effort.days<=.5}
        onClick={()=>onOverride({effort_days:Math.max(.5,item.effort.days-(item.effort.days<=2?.5:1))})}>−</Button>}
        <span>{item.effort.days} developer-days{!item.effort.known && !item.effort.overridden?" · estimate":""}</span>
        {editable && <Button size="sm" aria-label={`Increase effort for ${item.summary}`} disabled={item.effort.days>=365}
          onClick={()=>onOverride({effort_days:Math.min(365,item.effort.days+(item.effort.days<2?.5:1))})}>+</Button>}</span>
      {editable && <Button size="sm" variant="quiet" onClick={onToggle}>{inPlan?"Next time":"Add to plan"}</Button>}
      <details className="pl-row-detail"><summary>Why this is here · estimates</summary>
        <div className="pl-stack">
          <p className="pl-muted">{request?"Requests are ranked by demand for each developer-day. A request has no measured rating loss.":item.projected.basis}</p>
          <p className="pl-muted">{request
            ? `${item.avg_rating == null ? "Average rating not recorded" : `${item.avg_rating.toFixed(1)}★ average rating among requesting reviews`}. ${item.happy_count} reviews rated 4–5★ contribute extra weight to demand.`
            : <span title={`Severity score ${item.severity.score.toFixed(2)}; higher means worse`}>{item.severity.band} impact · open for {item.persistence_days} days</span>}</p>
          <p className="pl-muted">Effort: {item.effort.basis}. {item.effort.overridden&&"Set by you."}</p>
          {item.impact?.overridden&&<p className="pl-muted">Your impact choice weights planning value by {item.impact.factor}×.</p>}
          {item.segment&&<p className="pl-muted">{item.segment.label} weights planning value by {item.segment.factor}×. {item.segment.why}</p>}
          {note&&<p>{note}</p>}
          {request ? item.verbatims.map((quote,i)=><blockquote key={i} className="pl-quote">“{quote}”</blockquote>)
            : <p className="pl-muted">{item.evidence_count} cited proof items · <span title={item.evidence_refs.join(" · ")}>Open the problem to read the sources.</span></p>}
          {editable && <div className="pl-actions">
            {item.impact&&<label>Impact <select className="pl-input" aria-label={`Impact for ${item.summary}`} value={item.impact.level}
              onChange={e=>onOverride({impact:Number(e.target.value)})}>{[1,2,3,4,5].map(n=><option key={n} value={n}>{n} · {["","Minimal","Low","Medium","High","Critical"][n]}</option>)}</select></label>}
            <label>Priority group <select className="pl-input" aria-label={`Priority group for ${item.summary}`} value={item.segment?.key??""}
              onChange={e=>onOverride({segment:e.target.value||null})}><option value="">None</option>{segments.map(s=><option key={s.key} value={s.key}>{s.label}</option>)}</select></label>
            <Button variant="quiet" onClick={()=>onOverride(null)}>Reset estimates</Button>
          </div>}
        </div>
      </details>
    </div>
  </article>;
}
