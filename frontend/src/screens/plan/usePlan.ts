import { useEffect, useRef, useState } from "react";
import { QuarterPlan, api, canReview, getActiveProduct, getSessionGeneration, isGuest } from "../../api";
import { Draft, fromPlan, mergeReply } from "./model";

// A departing screen may still be saving when the same product is opened again.
const departures=new Map<string,{draft:Draft;completion:Promise<boolean>}>();

/** Serial saves keep a slow reply from replacing newer slider or effort edits. */
export function usePlan() {
  const productId=useRef(getActiveProduct()).current;
  const generation=useRef(getSessionGeneration()).current, key=`${generation}:${productId}`;
  const [plan,setPlan]=useState<QuarterPlan|null>(null);
  const [draft,setDraft]=useState<Draft|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [saving,setSaving]=useState(false);
  const [revision,setRevision]=useState(0);
  const current=useRef<Draft|null>(null), rev=useRef(0), saved=useRef(0), queued=useRef(0);
  const tail=useRef<Promise<boolean>>(Promise.resolve(true));
  const mounted=useRef(true), loadSeq=useRef(0);
  const load=()=>{
    const seq=++loadSeq.current;
    const departing=departures.get(key);
    const read=async()=>{
      const completed=departing ? await departing.completion : true;
      if(!mounted.current || seq!==loadSeq.current || generation!==getSessionGeneration())return;
      const p=await api.backlogPlan(undefined,"all");
      if(!mounted.current || seq!==loadSeq.current)return;
      const restore=departing && !completed;
      const d=restore ? departing.draft : fromPlan(p,current.current?.kind ?? departing?.draft.kind ?? "bugs");
      setPlan(p);current.current=d;setDraft(d);
      if(restore){rev.current=1;saved.current=0;setError("Your edits are still here. The previous save failed; retry saving.");}
      else setError(null);
      if(departures.get(key)===departing)departures.delete(key);
    };
    void read().catch(e=>mounted.current&&setError(String(e).replace(/^Error: /,"")));
  };
  const flush=():Promise<boolean>=>{
    if(!canReview() || isGuest())return Promise.resolve(false);
    const snapshot=current.current, version=rev.current;
    if(!snapshot || version===saved.current || version===queued.current)return tail.current;
    queued.current=version;
    tail.current=tail.current.catch(()=>false).then(async()=>{
      if(generation!==getSessionGeneration())return false;
      if(mounted.current)setSaving(true);
      try {
        const response=await api.saveBacklogPlan(snapshot,snapshot.kind,productId);
        saved.current=version;
        if(mounted.current && version===rev.current){setPlan(p=>p?mergeReply(p,response):response);setError(null);}
        return true;
      } catch(e) {
        if(mounted.current){setError(`Your edits are still here. Saving failed: ${String(e).replace(/^Error: /,"")}`);queued.current=saved.current;}
        return false;
      } finally {if(mounted.current)setSaving(false);}
    });
    return tail.current;
  };
  useEffect(()=>{mounted.current=true;load();return()=>{
    mounted.current=false;
    if(current.current && rev.current!==saved.current && canReview() && !isGuest() && generation===getSessionGeneration()){
      const departing={draft:current.current,completion:flush()};
      departures.set(key,departing);
      void departing.completion.then(ok=>{if(ok && departures.get(key)===departing)departures.delete(key);});
    }
  };},[]);
  useEffect(()=>{if(!revision)return;const timer=setTimeout(()=>void flush(),450);return()=>clearTimeout(timer);},[revision]);
  const change=(next:Draft)=>{current.current=next;rev.current++;setDraft(next);setRevision(rev.current);};
  return {plan,draft,error,saving,change,flush,reload:load,pending:rev.current!==saved.current};
}
