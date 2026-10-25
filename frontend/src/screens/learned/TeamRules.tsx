import { useEffect, useState } from 'react';
import { api, canReview, isGuest, TeamRule } from '../../api';
import { useAsync } from '../../hooks';
import { Button, ErrorState, Panel } from '../../ui';
import { EmptyState, SerifHeadline } from '../../components/casefile';
import { friendlyDate } from './model';
export function TeamRules({ productName, onOpenInvestigation }: { productName: string | null; onOpenInvestigation: (id: number, status?: string) => void }) {
  const { data, loading, error, reload } = useAsync(() => api.teamRules(), []);
  const [rules, setRules] = useState<TeamRule[]>([]);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [showRetired, setShowRetired] = useState(false);
  const [undoId, setUndoId] = useState<number | null>(null);
  const editable = canReview() && !isGuest();
  useEffect(() => { if (data) setRules(data.rules); }, [data]);
  const update = async (id: number, change: { text?: string; status?: 'active' | 'retired' }) => {
    if (!editable || busy) return;
    setBusy(true); setSaveError(null);
    try {
      const rule = await api.editTeamRule(id, change);
      setRules((current) => current.map((row) => row.id === id ? rule : row));
      if (change.status === 'retired') setUndoId(id);
      else if (change.status === 'active') setUndoId(null);
      if (change.text != null) { setEditing(null); setDraft(''); }
      reload();
    } catch { setSaveError('We couldn’t save this rule. Your text is still here; try again.'); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!editable || busy || !draft.trim()) return;
    if (editing != null) { await update(editing, { text: draft.trim() }); return; }
    setBusy(true); setSaveError(null);
    try {
      const rule = await api.addTeamRule(draft.trim());
      setRules((current) => [...current, rule]); setDraft(''); setAdding(false); reload();
    } catch { setSaveError('We couldn’t add this rule. Your text is still here; try again.'); }
    finally { setBusy(false); }
  };
  const form = <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
    <label className="learned-field" htmlFor="learned-rule-text">{editing != null ? 'Edit the rule' : 'What should EchoLens remember?'}<textarea id="learned-rule-text" value={draft} onChange={(event) => setDraft(event.target.value)} rows={3} maxLength={2000} autoFocus /></label>
    <div className="learned-row"><Button variant="primary" type="submit" loading={busy} disabled={!draft.trim()}>{editing != null ? 'Save rule' : 'Add rule'}</Button><Button type="button" disabled={busy} onClick={() => { setAdding(false); setEditing(null); setDraft(''); setSaveError(null); }}>Cancel</Button></div>
  </form>;
  return <section className="learned-stack" aria-label="Rules you’ve taught it">
    <div><SerifHeadline as="h2" size="section">Your team’s hints, kept in view.</SerifHeadline><p className="learned-intro">Rules and corrections guide investigations for {productName || 'this product'}. They are human hints, never proof. EchoLens still has to find exhibits that support a conclusion.</p></div>
    {!editable && <p className="learned-meta">{isGuest() ? 'Sign in as a reviewer to add, edit or retire rules.' : 'A reviewer or admin can add, edit or retire rules.'}</p>}
    {editable && !adding && editing == null && <div><Button variant="primary" onClick={() => { setAdding(true); setDraft(''); setSaveError(null); }}>Add a rule</Button></div>}
    {adding && <Panel title="Teach it a rule" tone="inset">{form}</Panel>}
    {saveError && <p className="learned-error" role="alert">{saveError}</p>}
    {undoId != null && <div role="status" className="learned-row"><span>Rule retired. It will no longer guide investigations.</span><Button disabled={busy} onClick={() => void update(undoId, { status: 'active' })}>Undo</Button></div>}
    {loading && !data ? <p role="status">Reading your team’s rules…</p> : error || !data ? <ErrorState title="We couldn’t read your team’s rules" onRetry={reload} /> : <>
      {rules.filter((rule) => rule.status === 'active').length === 0 && <EmptyState title="No active rules yet.">When a reviewer corrects a problem or adds a rule, the lesson appears here. Add the context your team wishes every investigation knew.</EmptyState>}
      {rules.filter((rule) => showRetired || rule.status === 'active').map((rule) => <article key={rule.id} className="learned-rule">
        <div className="learned-row"><span className="learned-hint">{rule.origin === 'correction' ? 'Human correction · hint only' : 'Team rule · hint only'}</span>{rule.status === 'retired' && <span className="learned-meta">Retired</span>}</div>
        {editing === rule.id ? form : <p className="learned-rule-text">{rule.text}</p>}
        <p className="learned-meta">{rule.author || 'Author not recorded'} · Added {friendlyDate(rule.created_at)}{rule.updated_at !== rule.created_at ? ` · Updated ${friendlyDate(rule.updated_at)}` : ''} · {productName || 'This product'}</p>
        <div className="learned-row" style={{ marginTop: 12 }}>
          {rule.case_id != null && <Button size="sm" onClick={() => onOpenInvestigation(rule.case_id!)}>Problem #{rule.case_id}</Button>}
          {editable && editing == null && !adding && <><Button size="sm" disabled={busy} onClick={() => { setEditing(rule.id); setDraft(rule.text); setSaveError(null); }}>Edit</Button><Button size="sm" disabled={busy} onClick={() => void update(rule.id, { status: rule.status === 'active' ? 'retired' : 'active' })}>{rule.status === 'active' ? 'Retire rule' : 'Restore rule'}</Button></>}
        </div>
      </article>)}
      {rules.some((rule) => rule.status === 'retired') && <label className="learned-meta learned-row"><input type="checkbox" checked={showRetired} onChange={(event) => setShowRetired(event.target.checked)} />Show retired rules</label>}
    </>}
  </section>;
}
