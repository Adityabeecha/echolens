import { useState } from 'react';
import { BrainEdge, ChangeReview, api } from '../api';
import { useAsync } from '../hooks';
import { EmptyState, SerifHeadline } from '../components/casefile';
import { Button, ErrorState, Panel } from '../ui';
import './learned/learned.css';
interface Props {
  onOpenInvestigation: (id: number, status?: string) => void;
  onBack: () => void;
  backLabel: string;
  onGoCases: () => void;
  onGoPatterns?: () => void;
  embedded?: boolean;
}
export function Brain({ onOpenInvestigation, onBack, backLabel, onGoCases, embedded }: Props) {
  const [retired, setRetired] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api.brain(retired), [retired]);
  return <section className={embedded ? 'learned-stack' : 'learned-v2'} aria-label="Product history and change checks">
    {!embedded && <><Button onClick={onBack}>{backLabel || 'Back'}</Button><SerifHeadline>Learn from this product’s history.</SerifHeadline></>}
    <div className="learned-two-columns"><ReviewBox /><HistoryQuestion /></div>
    <Panel title="How this product tends to break" actions={<label className="learned-meta learned-row"><input type="checkbox" checked={retired} onChange={(event) => setRetired(event.target.checked)} />Include retired lessons</label>}>
      <p className="learned-intro">Lessons connect a part of the product with a recurring symptom. Their track record changes as later problems support or contradict them. A lesson is a lead to check, not a verdict on a new problem.</p>
      {loading && !data ? <p role="status">Reading this product’s history…</p> : error || !data ? <ErrorState title="We couldn’t read this product’s history" onRetry={reload} /> : data.edges.length === 0 ? <EmptyState title="No lessons recorded yet." action={<Button onClick={onGoCases}>Open all problems</Button>}>Finished investigations build this map. You can still ask about the history or check a proposed change above.</EmptyState> : <div>{data.edges.map((edge) => <EdgeCard key={`${edge.subsystem}-${edge.symptom}`} edge={edge} onOpen={onOpenInvestigation} />)}</div>}
    </Panel>
  </section>;
}
function EdgeCard({ edge, onOpen }: { edge: BrainEdge; onOpen: (id: number, status?: string) => void }) {
  return <article className="learned-rule">
    <div className="learned-row"><span className="learned-hint">{edge.subsystem}</span><span className="learned-meta">{edge.status === 'retired' ? 'Retired lesson' : edge.trend === 'weakening' ? 'Holding up less often' : 'Active lesson'}</span></div>
    <SerifHeadline as="h3" size="section" style={{ marginTop: 12 }}>{edge.symptom.replace(/-/g, ' ')}</SerifHeadline>
    {edge.statement && <p className="learned-intro">{edge.statement}</p>}
    <p className="learned-meta" style={{ margin: '12px 0' }}>{Math.round(edge.confidence * 100)}% sure of this lesson · Verified {edge.verified_count} {edge.verified_count === 1 ? 'time' : 'times'} · {edge.supports} later problems supported it · {edge.refutes} contradicted it</p>
    <div className="learned-row">{edge.case_ids.map((id) => <Button key={id} size="sm" onClick={() => onOpen(id, 'resolved')}>Problem #{id}</Button>)}</div>
  </article>;
}
function ReviewBox() {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<ChangeReview | null>(null);
  const [error, setError] = useState(false);
  const run = async () => {
    if (!text.trim() || busy) return;
    setBusy(true); setError(false); setReview(null);
    try { setReview(await api.brainReview(text.trim())); }
    catch { setError(true); }
    finally { setBusy(false); }
  };
  return <Panel title="Check a change before it ships" tone="inset">
    <p className="learned-intro">Compare a spec or change description with this product’s past problems.</p>
    <form style={{ marginTop: 20 }} onSubmit={(event) => { event.preventDefault(); void run(); }}>
      <label className="learned-field" htmlFor="learned-change">Describe the proposed change<textarea id="learned-change" value={text} onChange={(event) => setText(event.target.value)} rows={4} /></label>
      <Button variant="primary" type="submit" loading={busy} disabled={!text.trim()}>Check this change</Button>
    </form>
    {error && <p className="learned-error" role="alert">We couldn’t check that change. Your description is still here; try again.</p>}
    {review && <div className="learned-rule" role="status" style={{ marginTop: 20 }}><p className="learned-meta">{review.risk === 'high' ? 'Past problems suggest a risk' : review.risk === 'elevated' ? 'Worth a closer check' : 'No known problem in the recorded history'}</p><p>{review.summary}</p>{review.flags.map((flag, index) => <div key={index} className="learned-rule"><p>{flag.why}</p><p className="learned-meta">Try next: {flag.recommendation}</p></div>)}<p className="learned-meta">This is a history check, not proof that a change is safe.</p></div>}
  </Panel>;
}
function HistoryQuestion() {
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [response, setResponse] = useState<{ answer: string; grounded: boolean } | null>(null);
  const [error, setError] = useState(false);
  const ask = async () => {
    if (!question.trim() || busy) return;
    setBusy(true); setError(false); setResponse(null);
    try { setResponse(await api.brainAsk(question.trim())); }
    catch { setError(true); }
    finally { setBusy(false); }
  };
  return <Panel title="Ask this product’s history" tone="inset">
    <p className="learned-intro">Ask what went wrong before and what the team learned.</p>
    <form style={{ marginTop: 20 }} onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label className="learned-field" htmlFor="learned-history-question">Your question<textarea id="learned-history-question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={4} /></label>
      <Button type="submit" loading={busy} disabled={!question.trim()}>Ask the history</Button>
    </form>
    {error && <p className="learned-error" role="alert">We couldn’t reach the product history. Your question is still here; try again.</p>}
    {response && <div className="learned-rule" role="status" style={{ marginTop: 20 }}><p className="learned-meta">{response.grounded ? 'Based on recorded product history' : 'There is not enough recorded history to ground this answer.'}</p><p style={{ whiteSpace: 'pre-wrap' }}>{response.answer}</p></div>}
  </Panel>;
}
