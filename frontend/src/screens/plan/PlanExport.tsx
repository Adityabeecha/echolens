import { useState } from "react";
import { PlanExportResult, PlanKind, TrackerId, api, canReview, getActiveProduct, getSessionGeneration, isGuest } from "../../api";
import { useAsync } from "../../hooks";
import { formatRoute } from "../../nav";
import { Button, ErrorState } from "../../ui";

export function PlanExport({kind,flush,count}: {kind:PlanKind;flush:()=>Promise<boolean>;count:number}) {
  const productId=getActiveProduct();
  const [open,setOpen]=useState(false),[busy,setBusy]=useState<TrackerId|null>(null);
  const [result,setResult]=useState<PlanExportResult|null>(null),[error,setError]=useState<string|null>(null);
  const trackers=useAsync(()=>api.trackers(),[]);
  const send=async(tracker:TrackerId)=>{
    const generation=getSessionGeneration();
    setBusy(tracker);setError(null);setResult(null);
    try {
      if(!await flush())throw new Error("Save the plan before sending. Your edits are still here.");
      if(generation!==getSessionGeneration() || !canReview() || isGuest())return;
      setResult(await api.exportPlan(tracker,kind,productId));
    } catch(e){setError(String(e).replace(/^Error: /,""));}
    finally{setBusy(null);}
  };
  return <section className="pl-export">
    <Button variant="primary" disabled={!count || busy!=null} aria-expanded={open} onClick={()=>setOpen(v=>!v)}>Send the plan to…</Button>
    {open&&<div className="pl-stack">
      <p className="pl-muted">Send these {count} planned items as separate issues. Successfully sent items are remembered so retries do not duplicate them.</p>
      {trackers.error?<ErrorState title="Couldn't read your issue trackers" onRetry={trackers.reload}/>:trackers.loading?<p role="status">Reading connected trackers…</p>:<div className="pl-actions">
        {(["github","linear","jira"] as const).map((id)=>{
          const label=id === "github"?"GitHub Issues":id === "linear"?"Linear":"Jira";
          const ready=trackers.data?.trackers.some(t=>t.id===id&&t.configured);
          return ready?<Button key={id} loading={busy===id} disabled={busy!=null} onClick={()=>void send(id)}>{label}</Button>
            :<Button key={id} variant="quiet" onClick={()=>{window.location.hash=formatRoute({screen:id==="github"?"sources":"settings",productId:getActiveProduct()});}}>Connect {label} in {id === "github"?"Sources":"Settings"}</Button>;
        })}
      </div>}
      {error&&<p role="alert" className="pl-muted">{error}</p>}
      {result&&<div role="status" className="pl-stack">{result.results.map(r=><div key={r.key}>
        {r.url?<a href={r.url} target="_blank" rel="noreferrer">{r.title} ↗</a>:<strong>{r.title}</strong>}
        <span> · {r.status === "created"?"Sent":r.status === "existing"?"Already sent":r.error??"Couldn't send — try again"}</span>
      </div>)}</div>}
    </div>}
  </section>;
}
