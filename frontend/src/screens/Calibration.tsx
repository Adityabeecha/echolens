import { useState } from 'react';
import { Calibration as CalibrationData, CalibrationPoint, api } from '../api';
import { useAsync } from '../hooks';
import { EmptyState, SerifHeadline } from '../components/casefile';
import { Button, ErrorState, Panel } from '../ui';
import { C, mono } from '../theme';
import { approvalExample } from './learned/model';
import './learned/learned.css';
const DISAGREEMENTS: Record<string, { label: string; guidance: string }> = {
  wrong_cause: { label: 'The cause was wrong', guidance: 'Check whether the same problem appears where the proposed cause is absent.' },
  weak_evidence: { label: 'The proof was too weak', guidance: 'Look for detailed reports from independent sources before becoming more sure.' },
  wrong_severity: { label: 'The impact was off', guidance: 'Compare the size of the problem with the complaint counts and rating change.' },
  already_knew: { label: 'Your team already knew', guidance: 'Check the recorded history before investigating the same cause again.' },
  rec_estimate_off: { label: 'The work estimate was off', guidance: 'Compare the expected benefit with the size of the change and say when the estimate is uncertain.' },
};
export function Calibration({ onGoCases, embedded }: { onGoCases: () => void; embedded?: boolean }) {
  const { data, loading, error, reload } = useAsync(() => api.calibration(), []);
  const example = data ? approvalExample(data.n_reviewed, data.overall_approval_rate) : null;
  const objections = data?.weak_spots.spots.reduce((sum, spot) => sum + spot.count, 0) ?? 0;
  return <section className={embedded ? 'learned-stack learned-calibration' : 'learned-v2'} aria-label="How accurate it is">
    <div><SerifHeadline as={embedded ? 'h2' : 'h1'} size={embedded ? 'section' : 'page'}>Does “we’re sure” hold up?</SerifHeadline><p className="learned-intro">We compare how sure EchoLens was with your team’s verdicts. Your approval is the measure here; it is not an independent check of the cause.</p></div>
    {loading && !data ? <p role="status">Reading reviewed problems…</p> : error || !data ? <ErrorState title="We couldn’t read the accuracy history" onRetry={reload} /> : data.n_reviewed === 0 ?
      <EmptyState title="No reviewed conclusions yet." action={<Button onClick={onGoCases}>Review all problems</Button>}>Approve a conclusion or tell us why it is wrong on a problem. Those verdicts let us compare stated certainty with what your team found.</EmptyState> : <>
      {example && <p className="learned-note">About {example.approved} of {example.reviewed} reviewed conclusions were approved ({percent(data.overall_approval_rate)}). Across these conclusions, EchoLens said it was {percent(data.mean_stated_confidence)} sure on average.</p>}
      {!data.sufficient && <p className="learned-meta">Only {data.n_reviewed} conclusions reviewed so far. Early results can move a lot; the comparison becomes more useful after 20 reviews.</p>}
      {data.overconfident && <p className="learned-note">EchoLens has been more sure than your verdicts support: {percent(data.mean_stated_confidence)} stated certainty compared with {percent(data.overall_approval_rate)} approved. Future investigations receive a reminder to be more cautious.</p>}
      <div className="learned-two-columns"><CalibrationChart data={data} /><Panel title="Where your team disagreed">
        {data.weak_spots.spots.length === 0 ? <p className="learned-intro">No reasons for disagreement recorded yet. When you tell us a conclusion is wrong, choose a reason to help the next investigation.</p> : data.weak_spots.spots.map((spot) => <article key={spot.reason} className="learned-rule"><SerifHeadline as="h3" size="section">{DISAGREEMENTS[spot.reason]?.label || spot.label}</SerifHeadline><p className="learned-meta" style={{ marginTop: 8 }}>{spot.count} reviewer {spot.count === 1 ? 'objection' : 'objections'} with this reason · {objections} objections in total</p><p className="learned-intro">{DISAGREEMENTS[spot.reason]?.guidance || 'Review the linked problems to see what your team disagreed with.'}</p></article>)}
      </Panel></div>
    </>}
  </section>;
}
const percent = (value: number | null) => value == null ? 'not recorded' : `${Math.round(value * 100)}%`;
const pointLabel = (point: CalibrationPoint) => `When EchoLens said it was ${point.range} sure, your team agreed about ${Math.round((point.approval_rate ?? 0) * point.count)} times out of ${point.count} (${percent(point.approval_rate)}).`;
function CalibrationChart({ data }: { data: CalibrationData }) {
  const points = data.points.filter((point) => point.count > 0 && point.approval_rate != null).sort((a, b) => a.midpoint - b.midpoint);
  const [selected, setSelected] = useState(0);
  const px = (value: number) => 62 + value * 320;
  const py = (value: number) => 318 - value * 280;
  if (points.length === 0) return <p className="learned-note">Reviews are recorded, but no comparable certainty groups are available yet.</p>;
  return <figure className="learned-chart">
    <svg viewBox="0 0 420 385" role="group" aria-label="How sure EchoLens was compared with the share your team approved">
      <title>Stated certainty and your team’s verdicts</title><desc>The dashed diagonal is a one to one match: 80 percent sure and 80 percent approved. Points below the line mean EchoLens was too sure. Tab to a point; use arrow keys to compare groups.</desc>
      {[0, .25, .5, .75, 1].map((tick) => <g key={tick}><line x1={px(0)} y1={py(tick)} x2={px(1)} y2={py(tick)} stroke={C.line} /><text x={px(tick)} y="340" fill={C.muted} fontSize="12" fontFamily={mono} textAnchor="middle">{Math.round(tick * 100)}%</text><text x="52" y={py(tick) + 4} fill={C.muted} fontSize="12" fontFamily={mono} textAnchor="end">{Math.round(tick * 100)}%</text></g>)}
      <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} stroke={C.muted} strokeWidth="1.5" strokeDasharray="5 5" />
      {points.length > 1 && <polyline points={points.map((point) => `${px(point.midpoint)},${py(point.approval_rate!)}`).join(' ')} fill="none" stroke={C.pencil} strokeWidth="2" />}
      {points.map((point, index) => <circle key={point.range} cx={px(point.midpoint)} cy={py(point.approval_rate!)} r={selected === index ? 8 : 6} fill={C.pencil} stroke={C.paper} strokeWidth="2" tabIndex={0} role="img" aria-label={pointLabel(point)} onFocus={() => setSelected(index)} onMouseEnter={() => setSelected(index)} onKeyDown={(event) => {
        const next = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? (index + 1) % points.length : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? (index + points.length - 1) % points.length : event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : -1;
        if (next < 0) return; event.preventDefault();
        event.currentTarget.ownerSVGElement?.querySelectorAll<SVGCircleElement>('circle[tabindex]')[next]?.focus();
      }}><title>{pointLabel(point)}</title></circle>)}
      <text x="220" y="372" fill={C.muted} fontSize="13" textAnchor="middle">How sure EchoLens was</text>
      <text x="18" y="175" transform="rotate(-90 18 175)" fill={C.muted} fontSize="13" textAnchor="middle">Share your team approved</text>
    </svg>
    <figcaption><span aria-live="polite">{pointLabel(points[Math.min(selected, points.length - 1)])}</span><br />Dashed line: certainty matches approvals. Below the line: too sure. Above it: too cautious.</figcaption>
    <details style={{ marginTop: 16 }}><summary>Read the exact groups</summary><table className="learned-table"><caption className="learned-meta">Reviewed conclusions grouped by stated certainty</caption><thead><tr><th scope="col">Stated certainty</th><th scope="col">Reviewed</th><th scope="col">Approved</th></tr></thead><tbody>{points.map((point) => <tr key={point.range}><th scope="row">{point.range}</th><td>{point.count}</td><td>{percent(point.approval_rate)}</td></tr>)}</tbody></table></details>
  </figure>;
}
