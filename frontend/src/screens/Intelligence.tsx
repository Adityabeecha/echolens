import { useEffect, useState } from 'react';
import { LearnedView } from '../nav';
import { SerifHeadline, PillTabs } from '../components/casefile';
import { Patterns } from './Patterns';
import { Brain } from './Brain';
import { Calibration } from './Calibration';
import { TeamRules } from './learned/TeamRules';
import { HonestyChecks } from './learned/HonestyChecks';
import { LEARNED_SECTIONS, LearnedSection, learnedSection } from './learned/model';
import './learned/learned.css';
export interface IntelligenceProps {
  productName: string | null;
  view: LearnedView;
  onView: (view: LearnedView) => void;
  onOpenInvestigation: (id: number, status?: string) => void;
  onGoCases: () => void;
}
export function Intelligence({ productName, view, onView, onOpenInvestigation, onGoCases }: IntelligenceProps) {
  const [verifiedCount, setVerifiedCount] = useState<number | null>(null);
  const [section, setSection] = useState<LearnedSection>(() => learnedSection(window.location.search, view));
  useEffect(() => {
    const sync = () => setSection(learnedSection(window.location.search, view));
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, [view]);
  const select = (next: LearnedSection) => {
    setSection(next);
    const url = new URL(window.location.href);
    url.searchParams.set('section', next);
    window.history.replaceState(null, '', url.pathname + url.search);
  };
  const headline = verifiedCount == null ? 'Verified fixes guide the next investigation.'
    : verifiedCount === 0 ? 'Your next verified fix starts the history.'
    : `${verifiedCount} verified fix ${verifiedCount === 1 ? 'lesson' : 'lessons'} to build on.`;
  return <div className="learned-v2">
    <header className="learned-heading">
      <p className="learned-eyebrow">WHAT WE’VE LEARNED{productName ? ` · ${productName}` : ''}</p>
      <SerifHeadline>{headline}</SerifHeadline>
      <p>What worked before, what your team taught us, and how we check our own work.</p>
    </header>
    <PillTabs tabs={[...LEARNED_SECTIONS]} value={section} onChange={select} label="What we’ve learned sections" panelId="learned-panel" />
    <div id="learned-panel" role="tabpanel" aria-label={LEARNED_SECTIONS.find((tab) => tab.id === section)?.label} className="learned-panel">
      {section === 'fixes' && <>
        <Patterns embedded onPatternCount={setVerifiedCount} onOpenInvestigation={onOpenInvestigation} onGoMemory={() => onView('map')} onGoCases={onGoCases} />
        <details className="learned-history">
          <summary>Explore this product’s history & check a change</summary>
          <Brain embedded onOpenInvestigation={onOpenInvestigation} onGoCases={onGoCases} onGoPatterns={() => onView('fixes')} onBack={() => onView('map')} backLabel="" />
        </details>
      </>}
      {section === 'rules' && <TeamRules productName={productName} onOpenInvestigation={onOpenInvestigation} />}
      {section === 'accuracy' && <Calibration embedded onGoCases={onGoCases} />}
      {section === 'honesty' && <HonestyChecks onGoCases={onGoCases} />}
    </div>
  </div>;
}
