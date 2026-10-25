import type { Pattern } from '../../api';
export const LEARNED_SECTIONS = [
  { id: 'fixes', label: 'What fixed things before' },
  { id: 'rules', label: "Rules you’ve taught it" },
  { id: 'accuracy', label: 'How accurate it is' },
  { id: 'honesty', label: 'Honesty checks at work' },
] as const;
export type LearnedSection = typeof LEARNED_SECTIONS[number]['id'];
export function learnedSection(location: string, _view: 'map' | 'fixes'): LearnedSection {
  const section = new URLSearchParams(location.split('?')[1] ?? '').get('section');
  return LEARNED_SECTIONS.find((tab) => tab.id === section)?.id ?? 'fixes';
}
export function approvalExample(reviewed: number, rate: number | null) {
  if (reviewed <= 0 || rate == null || !Number.isFinite(rate)) return null;
  return { reviewed, approved: Math.round(reviewed * rate) };
}
export function patternProblemIds(pattern: Pick<Pattern, 'cross_product' | 'cases'>): number[] {
  return pattern.cross_product ? [] : pattern.cases;
}
export function patternTrigger(trigger: string): string {
  const labels: Record<string, string> = {
    negative_review_spike: 'Negative reviews started rising',
    rating_drop: 'The rating started falling',
    theme_volume_surge: 'Complaints about the same problem spiked',
    issue_velocity_surge: 'GitHub reports started arriving faster',
    low_volume_watch: 'A few reviews raised the same concern',
  };
  return labels[trigger] ?? 'A review spike needed a closer look';
}
export function friendlyDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date unavailable' : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}
