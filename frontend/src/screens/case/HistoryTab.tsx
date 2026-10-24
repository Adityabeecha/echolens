import { Investigation } from "../../api";
import { when } from "../../format";
import { C, MEASURE, R, S, T, mono } from "../../theme";
import { EmptyState } from "../../ui";
import { Icon } from "../../components/Icon";

const KIND: Record<string, { color: string; icon: string }> = {
  opened: { color: C.muted, icon: "dot" },
  finding: { color: C.accent, icon: "diamond" },
  approved: { color: C.good, icon: "check" },
  challenged: { color: C.bad, icon: "close" },
  reopen: { color: C.info, icon: "retry" },
  merged: { color: C.info, icon: "arrowRight" },
  issue: { color: C.info, icon: "keyboard" },
  fix_shipped: { color: C.accent, icon: "shipped" },
  verified: { color: C.good, icon: "check" },
  regressed: { color: C.bad, icon: "warning" },
  // v15: product decisions and partial challenges
  decision: { color: C.info, icon: "diamond" },
  evidence_rejected: { color: C.bad, icon: "close" },
  rec_edited: { color: C.accent, icon: "retry" },
  needs_review: { color: C.bad, icon: "warning" },
  extended: { color: C.accent, icon: "play" },
};

/**
 * What happened to this case, and who decided it.
 *
 * Human decisions were previously invisible after the fact: challenging a
 * finding silently spawned a new case and left the old one looking as though
 * nothing had happened to it.
 */
export function HistoryTab({ inv, onOpenCase }: {
  inv: Investigation; onOpenCase: (id: number, status?: string) => void;
}) {
  const events = inv.history ?? [];
  if (events.length === 0) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: `${S[6]} ${S[6]}` }}>
        <EmptyState
          title="Nothing has happened to this case yet"
          body="Reviews, challenges, re-opens, filed issues and verified fixes all appear here as they happen."
        />
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: MEASURE, padding: `${S[6]} ${S[6]} ${S[12]}` }}>
        {events.map((e, i) => {
          const k = KIND[e.kind] ?? { color: C.muted, icon: "dot" };
          const last = i === events.length - 1;
          return (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "26px 1fr",
                                  columnGap: S[3] }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                <div style={{ width: 22, height: 22, borderRadius: "50%", flex: "none",
                              border: `1px solid ${k.color}66`, background: C.card,
                              color: k.color, display: "grid",
                              placeItems: "center" }}>
                  <Icon name={k.icon} size={12} />
                </div>
                <div style={{ width: 1, flex: 1, minHeight: 12,
                              background: last ? "transparent" : C.border2 }} />
              </div>
              <div style={{ paddingBottom: 18, minWidth: 0 }}>
                <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint,
                              letterSpacing: ".06em" }}>
                  {when(e.at)}
                  {e.by && <span style={{ color: C.dim }}> · {e.by}</span>}
                </div>
                <div style={{ fontSize: T.base, color: C.text2, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
                  {e.text}
                  {e.case_id != null && (
                    <button onClick={() => onOpenCase(e.case_id!)}
                      className="el-btn el-btn--sm"
                      style={{ color: C.accent, marginLeft: S[2],
                               fontFamily: mono, fontSize: T.sm, padding: `0 ${S[1]}` }}>
                      open case #{e.case_id}
                      <Icon name="arrowRight" size={11} />
                    </button>
                  )}
                </div>
                {e.note && (
                  <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[1], padding: `${S[2]} ${S[3]}`,
                                background: C.card, border: `1px solid ${C.border2}`,
                                borderRadius: R.control, lineHeight: "var(--el-lh-normal)", fontStyle: "italic" }}>
                    “{e.note}”
                  </div>
                )}
                {e.actual_cause && (
                  <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[2], lineHeight: "var(--el-lh-normal)" }}>
                    <strong>Human-provided cause (not evidence):</strong> {e.actual_cause}
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {(inv.related_evidence?.length ?? 0) > 0 && (
          <div style={{ marginTop: S[4], padding: S[4], border: `1px solid ${C.border2}`, borderRadius: R.card }}>
            <div style={{ fontSize: T.base, color: C.text2 }}>Related evidence from merged cases</div>
            <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[1] }}>
              Linked to the original record. This does not add support to this case's finding.
            </div>
            {inv.related_evidence!.map((e) => (
              <div key={`${e.source_case_id}:${e.id}`} style={{ marginTop: S[3] }}>
                <div style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>
                  case #{e.source_case_id} · {e.id} · {e.source} · {e.ref}
                </div>
                <div style={{ fontSize: T.sm, color: C.text3, marginTop: S[1] }}>{e.snippet}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
