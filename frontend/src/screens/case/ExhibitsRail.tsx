import { ReactNode, useEffect, useRef, useState } from "react";
import { Investigation, api, canReview } from "../../api";
import { withToast } from "../../components/Toast";
import { Exhibit as ExhibitCard } from "../../components/casefile";
import { Icon } from "../../components/Icon";
import { Button } from "../../ui";
import type { Exhibit } from "./caseFile";

const TILTS = [-0.5, 0.4, -0.3, 0.6, -0.4, 0.3];

/** The quote with only the exact words the finding quotes marked, when known. */
function quoteWith(x: Exhibit): { node: ReactNode; exact: boolean } {
  const text = `“${x.quote}”`;
  const h = x.highlight?.trim();
  const at = h ? text.toLowerCase().indexOf(h.toLowerCase()) : -1;
  if (!h || at < 0) return { node: text, exact: false };
  return {
    exact: true,
    node: <>{text.slice(0, at)}<mark className="cv-exact-mark">{text.slice(at, at + h.length)}</mark>{text.slice(at + h.length)}</>,
  };
}

/**
 * The proof, as exhibits: letter, kind · date, the quote. Picking one lights
 * its sentences in the story; the picked one opens its source, its details and
 * — for reviewers — "This doesn't prove it". The shared Exhibit marks the whole
 * quote when selected; a small wrapper (`cv-exact`) narrows that to the exact
 * quoted words when the citation map knows them.
 */
export function ExhibitsRail({ inv, exhibits, lit, onPick, onDetails, onReload, className = "", heading = true }: {
  inv: Investigation;
  exhibits: Exhibit[];
  lit: Set<string>;
  onPick: (letter: string) => void;
  onDetails: (x: Exhibit) => void;
  onReload: () => Promise<unknown> | void;
  className?: string;
  heading?: boolean;
}) {
  const kinds = new Set(exhibits.map((x) => x.kind.replace(/ ★\d| #\d+/g, ""))).size;
  const firstLit = exhibits.find((x) => lit.has(x.letter))?.letter;
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  // Bring the first lit exhibit into view inside the rail when it changes.
  useEffect(() => {
    if (firstLit) refs.current[firstLit]?.scrollIntoView({ block: "nearest" });
  }, [firstLit]);

  return (
    <aside aria-label="Exhibits" className={`cv-rail ${className}`}>
      {heading && (
        <div className="cv-rail__head">
          <h2>Exhibits</h2>
          <span>{exhibits.length} {exhibits.length === 1 ? "piece" : "pieces"} · {kinds} {kinds === 1 ? "kind" : "kinds"}</span>
        </div>
      )}
      {exhibits.length === 0 && (
        <p style={{ margin: 0, fontSize: 15, color: "var(--el-muted)", lineHeight: 1.5 }}>
          {inv.status === "running" ? "Proof appears here as EchoLens finds it." : "No proof was recorded for this problem."}
        </p>
      )}
      {exhibits.map((x, i) => {
        const selected = lit.has(x.letter);
        const q = quoteWith(x);
        return (
          <div key={x.id} ref={(el) => { refs.current[x.letter] = el; }}
            className={`cv-exhibit-wrap${q.exact ? " cv-exact" : ""}${x.evidence.rejected ? " cv-struck" : ""}`}>
            <ExhibitCard letter={x.letter} kind={x.kind} date={x.date} quote={q.node} selected={selected}
              tilt={TILTS[i % TILTS.length]} onSelect={onPick} />
            {x.evidence.rejected && (
              <div className="cv-exhibit-note">
                Struck by a reviewer{x.evidence.rejected.note ? `: “${x.evidence.rejected.note}”` : ""} — not counted as proof.
              </div>
            )}
            {selected && <ExhibitActions x={x} inv={inv} onDetails={() => onDetails(x)} onReload={onReload} />}
          </div>
        );
      })}
    </aside>
  );
}

function ExhibitActions({ x, inv, onDetails, onReload }: {
  x: Exhibit; inv: Investigation; onDetails: () => void; onReload: () => Promise<unknown> | void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const f = inv.finding;
  const canStrike = canReview() && !!f && f.status !== "challenged" && !x.evidence.rejected;

  const strike = async () => {
    if (!f) return;
    setBusy(true);
    const r = await withToast(() => api.rejectEvidence(f.id, x.id, note.trim()), {
      success: (res) => res.message || "Struck — EchoLens re-checked whether the rest still proves it.",
      failure: "Couldn't strike that exhibit",
    });
    setBusy(false);
    if (r) { setOpen(false); setNote(""); await onReload(); }
  };

  return (
    <>
      <div className="cv-exhibit-actions">
        {x.url && (
          <a href={x.url} target="_blank" rel="noreferrer noopener">
            Open the source <Icon name="external" size={11} style={{ display: "inline" }} />
          </a>
        )}
        <button type="button" className="cv-link" onClick={onDetails}>Details</button>
        {canStrike && !open && (
          <button type="button" className="cv-link" onClick={() => setOpen(true)}
            title="Strike it from the proof; EchoLens re-checks whether two independent sources still agree">
            This doesn't prove it
          </button>
        )}
      </div>
      {open && (
        <div className="cv-reject">
          <label className="cv-field">
            <span>Why doesn't it prove it? (optional)</span>
            <textarea className="cv-input" rows={2} value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. it's about charging, not battery drain" />
          </label>
          <div className="cv-row">
            <Button variant="primary" size="sm" loading={busy} onClick={strike}>Strike exhibit {x.letter}</Button>
            <Button variant="quiet" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      )}
    </>
  );
}
