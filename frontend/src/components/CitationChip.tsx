import { useId, useState } from "react";

// [ev_001] — a citation the reader can follow.
//
// Screens wire two-way highlighting through the callbacks: hovering or
// focusing a chip calls onHover(id) (and onHover(null) on leave/blur), so the
// screen can light up the matching evidence row; choosing it (click, Enter,
// Space) calls onSelect(id). The quote shows in a small popover on hover and
// keyboard focus; pass it directly (`quote`) or look it up lazily (`getQuote`).

export interface CitationChipProps {
  /** The evidence id, e.g. "ev_001". Rendered as "[ev_001]". */
  id: string;
  /** The quoted text, if the caller already has it. */
  quote?: string | null;
  /** Lazy lookup, called when the popover opens. Wins over `quote`. */
  getQuote?: (id: string) => string | null | undefined;
  /** Where the quote came from, shown under it ("Play Store · 2★"). */
  source?: string | null;
  /** Highlighted from the other side (the evidence row is hovered). */
  active?: boolean;
  onHover?: (id: string | null) => void;
  onSelect?: (id: string) => void;
}

export function CitationChip({ id, quote, getQuote, source, active, onHover, onSelect }: CitationChipProps) {
  const [open, setOpen] = useState(false);
  const tipId = useId();
  const text = open ? (getQuote?.(id) ?? quote ?? null) : null;

  const show = () => { setOpen(true); onHover?.(id); };
  const hide = () => { setOpen(false); onHover?.(null); };

  return (
    <span className="el-cite-wrap">
      <button
        type="button"
        className={`el-cite${active ? " is-active" : ""}`}
        aria-describedby={open && text ? tipId : undefined}
        aria-pressed={active || undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(e) => { if (e.key === "Escape" && open) { e.stopPropagation(); setOpen(false); } }}
        onClick={() => onSelect?.(id)}
      >
        [{id}]
      </button>
      {open && text && (
        <span role="tooltip" id={tipId} className="el-cite-tip">
          <span className="el-cite-tip__quote">“{text}”</span>
          {source && <span className="el-cite-tip__source">{source}</span>}
        </span>
      )}
    </span>
  );
}

/**
 * Prose with inline [ev_…] tags turned into chips. Everything else is plain
 * text; the caller passes the same callbacks it would give one chip.
 */
export function CitedText({ text, ...chip }: { text: string } & Omit<CitationChipProps, "id" | "quote" | "active"> & {
  activeId?: string | null;
}) {
  const { activeId, ...rest } = chip;
  const parts = (text || "").split(/(\[ev_\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const m = part.match(/^\[(ev_\d+)\]$/);
        return m
          ? <CitationChip key={i} id={m[1]} active={activeId === m[1]} {...rest} />
          : <span key={i}>{part}</span>;
      })}
    </>
  );
}
