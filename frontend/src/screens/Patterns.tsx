import { useEffect } from 'react';
import { api } from '../api';
import { useAsync } from '../hooks';
import { EmptyState, SerifHeadline, Stamp } from '../components/casefile';
import { Button, ErrorState, Panel } from '../ui';
import { patternProblemIds, patternTrigger } from './learned/model';
import './learned/learned.css';
interface Props {
  onGoMemory: () => void;
  onGoCases: () => void;
  onOpenInvestigation?: (id: number, status?: string) => void;
  embedded?: boolean;
  onPatternCount?: (count: number) => void;
}
export function Patterns({ onGoCases, onOpenInvestigation, embedded, onPatternCount }: Props) {
  const { data, loading, error, reload } = useAsync(() => api.patterns(), []);
  useEffect(() => { if (data) onPatternCount?.(data.patterns.length); }, [data, onPatternCount]);
  return <section className={embedded ? 'learned-stack' : 'learned-v2'} aria-label="What fixed things before">
    {!embedded && <SerifHeadline>Every fix leaves a lesson.</SerifHeadline>}
    <div><SerifHeadline as="h2" size="section">What fixed things before</SerifHeadline>
      <p className="learned-intro">A fix earns its place here when the follow-up shows it worked. It gives the next investigation a starting point; a new problem still needs its own proof.</p></div>
    {loading && !data ? <p role="status">Reading verified fixes…</p> : error || !data ? <ErrorState title="We couldn’t read the fix history" onRetry={reload} /> : data.patterns.length === 0 ?
      <EmptyState title="No verified fixes yet." action={<Button onClick={onGoCases}>Open all problems</Button>}>When a fix ships, mark it on the problem. EchoLens watches what happens next and saves a lesson when the fix works.</EmptyState> :
      <div className="learned-stack">{data.patterns.map((pattern, index) => <Panel tone="inset" key={`${pattern.trigger}-${index}`}>
        <header className="learned-row"><Stamp variant="fixWorked" compact /><span className="learned-meta">Verified {pattern.verified_count} {pattern.verified_count === 1 ? 'time' : 'times'}{pattern.cross_product ? ` · From ${pattern.from_product || 'another product'}` : ` · ${data.product || 'This product'}`}</span></header>
        <dl className="learned-flow">{[['When this happens', patternTrigger(pattern.trigger)], ['Watch out for', pattern.cause], ['What fixed it', pattern.fix]].map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{text || 'No detail recorded.'}</dd></div>)}</dl>
        {pattern.terms.length > 0 && <p className="learned-meta">Related to {pattern.terms.join(', ')}</p>}
        <footer className="learned-row learned-proof">
          {pattern.cross_product ? <p className="learned-meta">Problem history belongs to {pattern.from_product || 'another product'}{pattern.cases.length ? `: ${pattern.cases.map((id) => `#${id}`).join(', ')}` : '.'} It is a lead for this product, not proof.</p> : patternProblemIds(pattern).length > 0 ? <><span className="learned-meta">Problems behind this lesson</span>{patternProblemIds(pattern).map((id) => onOpenInvestigation ? <Button key={id} size="sm" onClick={() => onOpenInvestigation(id, 'resolved')}>Problem #{id}</Button> : <span className="learned-meta" key={id}>Problem #{id}</span>)}</> : <span className="learned-meta">No linked problems were recorded.</span>}
        </footer>
      </Panel>)}</div>}
  </section>;
}
