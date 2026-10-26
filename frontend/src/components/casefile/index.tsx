import { ComponentProps, CSSProperties, HTMLAttributes, ReactNode, useId } from "react";
import { TimelineChart } from "../charts/TimelineChart";
import { StampVariant } from "./stampFor";
import "./casefile.css";
export { stampFor } from "./stampFor";
export { Dropdown } from "./Dropdown";
export type { DropdownOption } from "./Dropdown";
export type { StampInput, StampVariant } from "./stampFor";

const VERDICT: Record<StampVariant, string> = {
  confirmed: "CONFIRMED", hunch: "HUNCH", request: "REQUEST", fixWorked: "FIX WORKED",
  reopened: "REOPENED", live: "LIVE",
};

/** Mount once per verdict; press-in motion never repeats on ordinary renders. */
export function Stamp({ variant, rotation = -6, compact = false, title }: {
  variant: StampVariant; rotation?: number; compact?: boolean; title?: string;
}) {
  if (variant === "live") return <LiveDot label="LIVE" />;
  return <span className={`cf-stamp cf-stamp--${variant}${compact ? " is-compact" : ""}`}
    style={{ "--stamp-rotation": `${rotation}deg` } as CSSProperties} title={title}>
    {VERDICT[variant]}
  </span>;
}

export function LiveDot({ label = "Investigating now" }: { label?: string }) {
  return <span className="cf-live"><span className="cf-live__dot" aria-hidden />{label}</span>;
}

export function SerifHeadline({ as: Tag = "h1", size = "page", children, className = "", ...rest }: {
  as?: "h1" | "h2" | "h3"; size?: "hero" | "page" | "case" | "card" | "section";
} & HTMLAttributes<HTMLHeadingElement>) {
  return <Tag {...rest} className={`cf-headline cf-headline--${size} ${className}`}>{children}</Tag>;
}

/** One focus card per screen. Pass story/actions and stats/chart as two regions. */
export function FocusCard({ children, aside, stamp, ...rest }: {
  children: ReactNode; aside: ReactNode; stamp?: ReactNode;
} & HTMLAttributes<HTMLElement>) {
  return <article {...rest} className={`cf-focus ${rest.className ?? ""}`}>
    {stamp && <div className="cf-focus__stamp">{stamp}</div>}
    <div className="cf-focus__story">{children}</div><div className="cf-focus__aside">{aside}</div>
  </article>;
}

/** The caption must include the unit, direction and comparison for the value. */
export function StatTile({ value, caption, tone = "neutral" }: {
  value: ReactNode; caption: ReactNode; tone?: "neutral" | "problem" | "good";
}) {
  return <div className={`cf-stat cf-stat--${tone}`}><div className="cf-stat__value">{value}</div>
    <div className="cf-stat__caption">{caption}</div></div>;
}

export function ReleaseChart({ caption, height = 104, minimal = true, ...props }: ComponentProps<typeof TimelineChart> & { caption?: ReactNode }) {
  return <figure className="cf-release-chart"><TimelineChart {...props} height={height} minimal={minimal} />
    {caption && <figcaption>{caption}</figcaption>}</figure>;
}

export function HighlightQuote({ children, active = true }: { children: ReactNode; active?: boolean }) {
  return active ? <mark className="cf-highlight">{children}</mark> : <span>{children}</span>;
}

export interface ExhibitProps {
  letter: string; kind: string; date: string; quote: ReactNode;
  selected?: boolean; tilt?: number; onSelect: (letter: string) => void;
}
export function Exhibit({ letter, kind, date, quote, selected = false, tilt = -0.5, onSelect }: ExhibitProps) {
  return <button type="button" className={`cf-exhibit${selected ? " is-selected" : ""}`}
    style={{ "--exhibit-tilt": `${tilt}deg` } as CSSProperties} aria-pressed={selected}
    aria-label={`Exhibit ${letter}: ${kind}, ${date}`} onClick={() => onSelect(letter)}>
    <span className="cf-exhibit__letter">{letter}</span><span className="cf-exhibit__body">
      <span className="cf-exhibit__meta">{kind} · {date}</span>
      <span className="cf-exhibit__quote"><HighlightQuote active={selected}>{quote}</HighlightQuote></span>
    </span></button>;
}

export function CitationLetter({ letter, selected = false, onSelect }: {
  letter: string; selected?: boolean; onSelect: (letter: string) => void;
}) {
  return <button type="button" className={`cf-citation${selected ? " is-selected" : ""}`}
    aria-label={`Show exhibit ${letter}`} aria-pressed={selected} onClick={() => onSelect(letter)}>{letter}</button>;
}

export function ReasonRow({ children, letters, selected = false, onSelect }: {
  children: ReactNode; letters: string[]; selected?: boolean; onSelect: () => void;
}) {
  return <button type="button" className={`cf-reason${selected ? " is-selected" : ""}`}
    aria-pressed={selected} onClick={onSelect}>
    <span className="cf-reason__check" aria-hidden>✓</span><span className="cf-reason__text">{children}</span>
    <span className="cf-reason__letters" aria-label={`Exhibits ${letters.join(", ")}`}>{letters.join(" · ")}</span>
  </button>;
}

export interface NextStep { id: string; text: ReactNode; action?: ReactNode; automatic?: boolean }
export function NumberedSteps({ steps, label = "What to do next" }: { steps: NextStep[]; label?: string }) {
  return <ol className="cf-steps" aria-label={label}>{steps.map((step, i) =>
    <li key={step.id} className={`cf-step${i === 0 && !step.automatic ? " is-first" : ""}${step.automatic ? " is-automatic" : ""}`}>
      <span className="cf-step__number" aria-hidden>{i + 1}</span><span className="cf-step__text">{step.text}</span>{step.action}
    </li>)}</ol>;
}

export function ListRow({ variant, title, detail, onClick }: {
  variant: StampVariant; title: string; detail: ReactNode; onClick: () => void;
}) {
  return <button type="button" className="cf-list-row" onClick={onClick}>
    <span className="cf-list-row__stamp"><Stamp variant={variant} compact rotation={variant === "request" ? 2 : -3} /></span>
    <span className="cf-list-row__body"><strong>{title}</strong><span>{detail}</span></span><span aria-hidden>›</span>
  </button>;
}

export function GoodNewsCard({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <article className="cf-good-news"><Stamp variant="fixWorked" compact rotation={-5} />
    <SerifHeadline as="h3" size="section">{title}</SerifHeadline><div>{children}</div>{action}</article>;
}

export interface PillTab<T extends string> { id: T; label: string; disabled?: boolean }
/** Arrow keys, Home and End move focus and select. The caller owns the panel. */
export function PillTabs<T extends string>({ tabs, value, onChange, label, panelId }: {
  tabs: PillTab<T>[]; value: T; onChange: (value: T) => void; label: string; panelId?: string;
}) {
  const uid = useId();
  return <div className="cf-tabs" role="tablist" aria-label={label}>{tabs.map((tab) =>
    <button type="button" role="tab" key={tab.id} id={`${uid}-${tab.id}`} disabled={tab.disabled}
      aria-selected={value === tab.id} aria-controls={panelId} tabIndex={value === tab.id ? 0 : -1}
      onClick={() => onChange(tab.id)} onKeyDown={(event) => {
        const enabled = tabs.filter((t) => !t.disabled);
        const index = enabled.findIndex((t) => t.id === tab.id);
        const next = event.key === "Home" ? 0 : event.key === "End" ? enabled.length - 1
          : event.key === "ArrowRight" ? (index + 1) % enabled.length
          : event.key === "ArrowLeft" ? (index - 1 + enabled.length) % enabled.length : -1;
        if (next < 0) return;
        event.preventDefault(); onChange(enabled[next].id);
        document.getElementById(`${uid}-${enabled[next].id}`)?.focus();
      }}>{tab.label}</button>)}</div>;
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return <section className="cf-empty"><SerifHeadline as="h2" size="section">{title}</SerifHeadline>
    <p>{children}</p>{action}</section>;
}
