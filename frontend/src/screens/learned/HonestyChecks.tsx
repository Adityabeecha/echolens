import { useState } from 'react';
import { api, GuardKey } from '../../api';
import { useAsync } from '../../hooks';
import { EmptyState, PillTabs, SerifHeadline } from '../../components/casefile';
import { Button, ErrorState } from '../../ui';
import { friendlyDate } from './model';
const CHECKS: Record<GuardKey, { title: string; description: string }> = {
  citation: { title: 'Keep claims tied to proof', description: 'Claims without supporting exhibits are removed or held back.' },
  two_source: { title: 'Look for independent sources', description: 'A conclusion needs support from different kinds of sources before it can be treated as confirmed.' },
  single_source_cap: { title: 'Keep one-source leads as hunches', description: 'When only one source supports a lead, certainty is held back.' },
  temporal_order: { title: 'Check that the cause came first', description: 'A change that happened after the complaints cannot explain their beginning.' },
  speculation: { title: 'Say when it is a guess', description: 'Ideas that go beyond the recorded proof are labelled as uncertain.' },
};
export function HonestyChecks({ onGoCases }: { onGoCases: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.guardsStats(), []);
  const [window, setWindow] = useState<'d30' | 'd90'>('d30');
  return <section className="learned-stack" aria-label="Honesty checks at work">
    <div><SerifHeadline as="h2" size="section">The checks that hold a conclusion back.</SerifHeadline><p className="learned-intro">Before a problem is presented, EchoLens checks the sources, the timing and the claims. These counts show where a check intervened.</p></div>
    <PillTabs tabs={[{ id: 'd30', label: 'Last 30 days' }, { id: 'd90', label: 'Last 90 days' }]} value={window} onChange={setWindow} label="Honesty check period" panelId="learned-check-counts" />
    {loading && !data ? <p role="status">Reading honesty checks…</p> : error || !data ? <ErrorState title="We couldn’t read the honesty checks" onRetry={reload} /> : <div id="learned-check-counts" role="tabpanel" aria-label={window === 'd30' ? 'Last 30 days' : 'Last 90 days'}>
      <p className="learned-note">{data.cases_checked[window]} completed {data.cases_checked[window] === 1 ? 'problem' : 'problems'} checked in this window. Each count below is the number of problems where that check intervened, once per problem. A problem can appear under several checks; these are not counts of individual claims.</p>
      {data.cases_checked[window] === 0 && <EmptyState title="No completed problems to check yet." action={<Button onClick={onGoCases}>Open all problems</Button>}>These checks run during an investigation. Their results appear here when work finishes.</EmptyState>}
      {data.guards.map((guard) => <article className="learned-check" key={guard.key}><div><h3>{CHECKS[guard.key]?.title || guard.label}</h3><p>{CHECKS[guard.key]?.description || 'This check intervenes when the proof needs another look.'}</p></div><div><span className="learned-check-count">{guard.interventions[window]}</span><p className="learned-meta">of {data.cases_checked[window]} problems</p></div></article>)}
      <p className="learned-meta">As of {friendlyDate(data.as_of)}. A zero means no recorded intervention in this window; it does not establish that every conclusion was right.</p>
    </div>}
  </section>;
}
