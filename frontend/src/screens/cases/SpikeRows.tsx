import { Dropdown } from "../../components/casefile";
import { ReactNode, useEffect, useRef, useState } from "react";
import type { Incident, IntentCounts, SignalRow, SpikeStrength, ThemeCandidate, ThemeOverride } from "../../api";
import { plural, when } from "../../format";
import { Button } from "../../ui";

// The rows of "New spikes": a detected spike, an incident (related spikes in
// the same window), a recurring complaint, and a request from users. Same
// rhythm as a ListRow — top rule, 92px left column, title + one muted line —
// with a checkbox for the batch actions and a "Look into it" button.
//
// No API import here: the screen passes every action in, so these stay plain.

const TYPE_LABEL: Record<string, string> = {
  manual: "Opened by you", manual_theme: "Theme you picked", anomaly: "Detected spike",
  theme_volume_surge: "Rising complaint", negative_review_spike: "1★ spike", rating_drop: "Rating drop",
  issue_velocity_surge: "GitHub issues", regression: "Came back", fix_regression: "Came back",
  challenge: "Re-opened", low_volume_watch: "A few people say it",
};
export const typeLabel = (t: string) => TYPE_LABEL[t] ?? t.replace(/_/g, " ");

/** Signals carry no severity field; the detector's z bands give one. */
export function strengthOf(s: { z: number; strength?: SpikeStrength }): SpikeStrength {
  if (s.strength) return s.strength;
  const z = Math.abs(s.z);
  return z >= 3 ? "strong" : z >= 2 ? "medium" : "weak";
}

const INTENT_NAMES: [keyof IntentCounts, string][] = [
  ["bug", "bugs"], ["feature_request", "requests"], ["ux_confusion", "confusion"],
  ["praise", "praise"], ["other", "other"],
];
/** "Reviews behind it: bugs 5 · requests 2" — kept as a tooltip. */
export function intentTip(counts?: IntentCounts | null): string | undefined {
  if (!counts) return undefined;
  const parts = INTENT_NAMES.filter(([k]) => (counts[k] ?? 0) > 0).map(([k, n]) => `${n} ${counts[k]}`);
  return parts.length ? `Reviews behind it: ${parts.join(" · ")}` : undefined;
}

function noticed(ageDays: number | null): string | null {
  if (ageDays == null || !Number.isFinite(ageDays)) return null;
  const d = new Date();
  d.setDate(d.getDate() - Math.max(0, Math.round(ageDays)));
  return `noticed ${when(d.toISOString())}`;
}

function Strength({ value, z, label }: { value: SpikeStrength | null; z?: number; label?: string }) {
  return (
    <span className={`pr-strength${value ? ` is-${value}` : ""}`}
      title={z != null ? `Strength ${value}: z-score ${z.toFixed(1)} against the usual level` : label}>
      {value && <span className="pr-strength__bars" aria-hidden><i /><i /><i /></span>}
      <span>{value ?? label}</span>
    </span>
  );
}

function Shell({ selected, check, left, title, meta, extra, actions, tip }: {
  selected?: boolean; check?: ReactNode; left: ReactNode; title: string; meta: ReactNode;
  extra?: ReactNode; actions?: ReactNode; tip?: string;
}) {
  return (
    <div className={`pr-spike${selected ? " is-selected" : ""}`}>
      {check ?? <span className="pr-spike__check-gap" aria-hidden />}
      {left}
      <div className="pr-spike__body" title={tip}>
        <span className="pr-spike__title">{title}</span>
        <span className="pr-spike__meta">{meta}</span>
        {extra}
      </div>
      {actions && <div className="pr-spike__actions">{actions}</div>}
    </div>
  );
}

function LookInto({ onLook, busy }: { onLook?: () => void; busy?: boolean }) {
  if (!onLook) return null;
  return <Button variant="ghost" size="sm" onClick={onLook} loading={busy}>Look into it</Button>;
}

export function SpikeRow({ signal, selected, onToggle, onLook, busy }: {
  signal: SignalRow; selected: boolean; onToggle: () => void; onLook?: () => void; busy?: boolean;
}) {
  const strength = strengthOf(signal);
  return (
    <Shell selected={selected} tip={intentTip(signal.intents)}
      check={<input type="checkbox" className="pr-spike__check" checked={selected} onChange={onToggle}
        aria-label={`Select: ${signal.title}`} />}
      left={<Strength value={strength} z={signal.z} />}
      title={signal.title}
      // The sentence says what happened; "GitHub issues · 7d window" did not.
      meta={<>{signal.summary
        ? [signal.summary, noticed(signal.age_days)].filter(Boolean).join(" · ")
        : [typeLabel(signal.type), `${signal.window} window`, noticed(signal.age_days)].filter(Boolean).join(" · ")}</>}
      actions={<LookInto onLook={onLook} busy={busy} />} />
  );
}

export function IncidentRow({ incident, members, selected, onToggle, onLook, busy }: {
  incident: Incident; members: SignalRow[]; selected: boolean; onToggle: () => void;
  onLook?: () => void; busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const others = members.length - 1;
  return (
    <Shell selected={selected} tip={intentTip(incident.intents)}
      check={<input type="checkbox" className="pr-spike__check" checked={selected} onChange={onToggle}
        aria-label={`Select incident: ${incident.title}`} />}
      left={<Strength value={strengthOf(incident)} z={incident.z} />}
      title={incident.title}
      meta={<>
        {/* The strongest spike's plain sentence, then the grouping. */}
        {(members.find((m) => m.slug === incident.lead) ?? members[0])?.summary &&
          <span>{(members.find((m) => m.slug === incident.lead) ?? members[0]).summary} · </span>}
        <span>{members.length} related spikes in the same window</span>
        <button type="button" className="pr-link" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "hide them" : "show them"}
        </button>
      </>}
      extra={<>
        {open && (
          <ul className="pr-members">
            {members.map((m, i) => (
              <li key={m.slug}>{m.title} <span style={{ color: "var(--el-muted)" }}>
                · {typeLabel(m.type)} · {strengthOf(m)}{i === 0 ? " · strongest" : ""}</span></li>
            ))}
          </ul>
        )}
        {selected && others > 0 && (
          <span className="pr-spike__meta">Looks into the strongest; the other {others}{" "}
            {plural(others, "is", "are")} noted on the problem.</span>
        )}
      </>}
      actions={<LookInto onLook={onLook} busy={busy} />} />
  );
}

/** A recurring complaint (selectable) or a request from users (display only). */
export function ThemeRow({ theme, request, selected, onToggle, onLook, busy, menu }: {
  theme: ThemeCandidate; request?: boolean; selected?: boolean; onToggle?: () => void;
  onLook?: () => void; busy?: boolean; menu?: ReactNode;
}) {
  // The statement IS the first quote when it fell back to verbatim, so one
  // quote is nothing new to show; otherwise even a single example is worth it.
  const quotesToShow = theme.label_source === "verbatim" ? 1 : 0;
  const [open, setOpen] = useState(false);
  const meta = [
    request ? `${theme.count} ${plural(theme.count, "person asks", "people ask")} for this`
      : `${theme.count} ${plural(theme.count, "review")}`,
    theme.trend === "up" ? "rising" : theme.trend === "down" ? "falling" : null,
    theme.avg_rating != null ? `avg ${theme.avg_rating.toFixed(1)}★` : null,
    theme.renamed ? "renamed" : null,
    (theme.merged_from?.length ?? 0) > 0 ? `${theme.merged_from!.length} merged in` : null,
  ].filter(Boolean).join(" · ");
  return (
    <Shell selected={!!selected} tip={intentTip(theme.intents)}
      check={onToggle ? <input type="checkbox" className="pr-spike__check" checked={!!selected}
        onChange={onToggle} aria-label={`Select: ${theme.statement}`} /> : undefined}
      left={<Strength value={null} label={request ? "Asked for" : "Recurring"} />}
      title={theme.statement}
      meta={<>
        <span title={theme.label_source === "verbatim"
          ? "Named in a customer's own words — the generated name wasn't confident enough." : undefined}>{meta}</span>
        {theme.verbatims.length > quotesToShow && (
          <button type="button" className="pr-link" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "hide examples"
              : `show ${theme.verbatims.length} example ${plural(theme.verbatims.length, "review")}`}
          </button>
        )}
      </>}
      extra={open && (
        <ul className="pr-quotes">{theme.verbatims.map((v, i) => <li key={i}>“{v}”</li>)}</ul>
      )}
      actions={<>{!request && <LookInto onLook={onLook} busy={busy} />}{menu}</>} />
  );
}

// ── rename / merge / mute a theme ───────────────────────────────────────

export type OverrideBody = { slug: string; action: "rename" | "merge" | "mute" | "unmute" | "reset";
                             label?: string; into?: string };

export function ThemeMenu({ theme, others, onEdit }: {
  theme: ThemeCandidate; others: ThemeCandidate[];
  onEdit: (body: OverrideBody, success: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"menu" | "rename" | "merge">("menu");
  const [label, setLabel] = useState(theme.statement);
  const [into, setInto] = useState("");
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const targets = others.filter((o) => o.slug !== theme.slug);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [open]);

  const save = async (body: OverrideBody, success: string) => {
    setSaving(true);
    await onEdit(body, success);
    setSaving(false);
    setOpen(false);
  };
  const item = (text: string, onClick: () => void, disabled = false) => (
    <button type="button" role="menuitem" className="pr-menu__item" onClick={onClick} disabled={disabled || saving}>{text}</button>
  );

  return (
    <div ref={ref} className="pr-menu">
      <Button variant="quiet" size="sm" aria-haspopup="menu" aria-expanded={open}
        aria-label={`Edit: ${theme.statement}`} title="Rename, merge or mute"
        onClick={() => { setOpen((o) => !o); setMode("menu"); setLabel(theme.statement); }}>⋯</Button>
      {open && (
        <div role="menu" className="pr-menu__panel">
          {mode === "menu" && (
            <>
              {item("Rename…", () => setMode("rename"))}
              {item(targets.length ? "Merge into…" : "Merge into… (nothing to merge with)", () => setMode("merge"), targets.length === 0)}
              {item("Mute — hide it and stop new spikes about it", () =>
                save({ slug: theme.slug, action: "mute" }, "Muted. It's hidden and won't raise new spikes."))}
              {theme.renamed && item("Restore the generated name", () =>
                save({ slug: theme.slug, action: "rename", label: "" }, "Generated name restored."))}
            </>
          )}
          {mode === "rename" && (
            <form onSubmit={(e) => { e.preventDefault(); save({ slug: theme.slug, action: "rename", label }, "Renamed."); }}>
              <input className="pr-input" value={label} onChange={(e) => setLabel(e.target.value)} autoFocus
                aria-label="New name" maxLength={120} />
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <Button variant="quiet" size="sm" type="button" onClick={() => setMode("menu")}>Back</Button>
                <Button variant="primary" size="sm" type="submit" disabled={saving || !label.trim()}>
                  {saving ? "Saving…" : "Rename"}
                </Button>
              </div>
            </form>
          )}
          {mode === "merge" && (
            <div className="pr-menu__merge">
              <Dropdown block label="Merge into" value={into} placeholder="Choose one…"
                options={targets.map((t) => ({ value: t.slug, label: t.statement }))} onChange={setInto} />
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <Button variant="quiet" size="sm" type="button" onClick={() => setMode("menu")}>Back</Button>
                <Button variant="primary" size="sm" disabled={saving || !into}
                  onClick={() => save({ slug: theme.slug, action: "merge", into },
                    "Merged — its reviews now count toward the other one.")}>
                  {saving ? "Merging…" : "Merge"}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** "3 muted topics" — each with who muted it, and Unmute for reviewers. */
export function MutedTopics({ count, reviewer, load, onUnmute }: {
  count: number; reviewer: boolean; load: () => Promise<ThemeOverride[]>;
  onUnmute: (slug: string) => Promise<void>;
}) {
  const [rows, setRows] = useState<ThemeOverride[] | null>(null);
  return (
    <details className="pr-disclosure" onToggle={async (e) => {
      if (!(e.currentTarget as HTMLDetailsElement).open || rows) return;
      try { setRows((await load()).filter((o) => o.muted)); } catch { setRows([]); }
    }}>
      <summary>{count} muted {plural(count, "topic")}</summary>
      <div className="pr-dismissed">
        {rows == null ? <div className="pr-dismissed__row">Loading…</div>
          : rows.length === 0 ? <div className="pr-dismissed__row">Nothing is muted.</div>
          : rows.map((o) => (
            <div key={o.slug} className="pr-dismissed__row" style={{ alignItems: "center" }}>
              <span className="pr-dismissed__title">
                {o.label || o.slug.replace(/^(theme|request)-p\d+-/, "").replace(/-/g, " ")}
              </span>
              {o.updated_by && <span>muted by {o.updated_by}</span>}
              {reviewer && (
                <Button variant="ghost" size="sm" onClick={async () => {
                  await onUnmute(o.slug);
                  setRows((r) => (r ?? []).filter((x) => x.slug !== o.slug));
                }}>Unmute</Button>
              )}
            </div>
          ))}
      </div>
    </details>
  );
}
