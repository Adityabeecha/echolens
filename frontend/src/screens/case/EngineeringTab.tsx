import { useState } from "react";
import { FixStatus, Investigation, api, canReview } from "../../api";
import { withToast } from "../../components/Toast";
import { when } from "../../format";
import { C, MEASURE, R, S, T, mono } from "../../theme";
import { EmptyState, Label } from "../../ui";

interface Props {
  inv: Investigation;
  onReload: () => Promise<unknown> | void;
  onGoPatterns: () => void;
}

const FIX_META: Record<string, { label: string; color: string; body: string }> = {
  issue_open: {
    label: "Issue open", color: C.info,
    body: "The issue is filed and open. When it closes, EchoLens starts a 14-day watch on the complaints it was meant to stop.",
  },
  watching: {
    label: "In verification", color: C.accent,
    body: "The issue closed. EchoLens is watching complaint volume for 14 days to see whether the fix actually worked.",
  },
  confirmed: {
    label: "Verified fixed", color: C.good,
    body: "Complaints dropped and stayed down after the fix shipped. This is what earns a pattern.",
  },
  inconclusive: {
    label: "Inconclusive", color: C.accent,
    body: "Complaints fell after the fix, but not far enough to call it fixed. This is a partial improvement, not a verified one — your call on whether it worked.",
  },
  persists_reopened: {
    label: "Fix didn't hold", color: C.bad,
    body: "The issue closed but the complaints continued at the same rate. The case was re-opened.",
  },
  regressed: {
    label: "Regressed", color: C.bad,
    body: "The complaints stopped, then came back. Something re-introduced the cause.",
  },
};

/**
 * Where a finding becomes work: the ticket, and whether it worked.
 *
 * These controls used to sit on the finding itself, mixing "is this true?" with
 * "who is fixing it?" — two different decisions made by two different people.
 */
export function EngineeringTab({ inv, onReload, onGoPatterns }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const f = inv.finding;

  if (!f) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: `${S[6]} ${S[6]}` }}>
        <EmptyState
          title="Nothing to file yet"
          body="A case needs a finding before it can become a ticket. Check the Investigation trace to see where this one stands."
        />
      </div>
    );
  }

  const fix = f.fix;
  const meta = fix ? FIX_META[fix.status] : null;
  const canCreate = canReview() && inv.status === "resolved";

  const copyIssue = async () => {
    setBusy("copy");
    await withToast(
      async () => {
        const t = await api.findingIssue(f.id);
        await navigator.clipboard.writeText(`# ${t.title}\n\n${t.body}`);
        return t;
      },
      { success: "Ticket markdown copied to your clipboard.",
        failure: "Couldn't copy the ticket" });
    setBusy(null);
  };

  const createIssue = async () => {
    setBusy("create");
    const r = await withToast(() => api.createGithubIssue(f.id), {
      success: (res) => `Opened GitHub issue #${res.number} in ${res.repo}.`,
      failure: "Couldn't open the GitHub issue",
    });
    setBusy(null);
    if (r) await onReload();
  };

  const notify = async () => {
    setBusy("notify");
    await withToast(() => api.notifyFinding(f.id), {
      success: (res) => `Sent to ${res.routed}.`,
      failure: "Couldn't send that notification",
    });
    setBusy(null);
  };

  return (
    <div style={{ flex: 1, overflow: "auto" }}>
      <div style={{ maxWidth: MEASURE, padding: `${S[6]} ${S[6]} ${S[12]}` }}>
        <Label style={{ marginBottom: S[2] }}>THE TICKET</Label>
        {fix?.issue_url ? (
          <div style={{ padding: `${S[4]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`,
                        borderRadius: R.card, display: "flex", alignItems: "center", gap: S[3],
                        flexWrap: "wrap" }}>
            <span style={{ fontSize: T.base, color: C.text2 }}>
              Filed as issue #{fix.issue_number}
            </span>
            <a href={fix.issue_url} target="_blank" rel="noreferrer"
              style={{ fontFamily: mono, fontSize: T.sm, color: C.info, textDecoration: "none" }}>
              open on GitHub ↗
            </a>
            <div style={{ flex: 1 }} />
            <button onClick={copyIssue} disabled={!!busy} className="el-btn"
              style={ghost}>{busy === "copy" ? "Copying…" : "Copy as issue"}</button>
          </div>
        ) : (
          <div style={{ padding: `${S[4]} ${S[4]}`, background: C.card, border: `1px solid ${C.border2}`,
                        borderRadius: R.card }}>
            <div style={{ fontSize: T.base, color: C.text3 }}>Not filed yet.</div>
            <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
              Filing it links the fix to the complaints it should stop, so EchoLens can tell you
              later whether it actually worked.
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[3],
                          flexWrap: "wrap" }}>
              <button onClick={copyIssue} disabled={!!busy} className="el-btn" style={ghost}>
                {busy === "copy" ? "Copying…" : "Copy as issue"}
              </button>
              {canCreate && (
                <button onClick={createIssue} disabled={!!busy} className="el-btn"
                  style={{ background: C.accent, color: C.onAccent, border: "none",
                           borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontWeight: 600,
                           cursor: "pointer" }}>
                  {busy === "create" ? "Creating…" : "Create GitHub issue"}
                </button>
              )}
              {canReview() && (
                <button onClick={notify} disabled={!!busy} className="el-btn" style={ghost}>
                  {busy === "notify" ? "Sending…" : "Notify the team"}
                </button>
              )}
            </div>
          </div>
        )}

        <Label style={{ margin: "26px 0 10px" }}>DID THE FIX WORK?</Label>
        {!fix || !meta ? (
          <EmptyState
            title="Verification hasn't started"
            body="Once a linked issue closes, EchoLens watches the complaints it was meant to stop and reports back here — verified, or not."
          />
        ) : (
          <>
            <div style={{ padding: `${S[4]} ${S[4]}`, background: C.card,
                          border: `1px solid ${meta.color}55`, borderRadius: R.card }}>
              <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
                <span style={{ fontFamily: mono, fontSize: T.xs, padding: `${S[1]} ${S[2]}`,
                               borderRadius: R.pill, background: `${meta.color}1f`,
                               border: `1px solid ${meta.color}66`, color: meta.color }}>
                  {meta.label}
                </span>
                {fix.chart?.fix_date && (
                  <span style={{ fontSize: T.sm, color: C.muted }}>
                    fix shipped {when(fix.chart.fix_date)}
                  </span>
                )}
              </div>
              <div style={{ fontSize: T.base, color: C.text3, marginTop: S[2], lineHeight: "var(--el-lh-normal)" }}>
                {meta.body}
              </div>
              {fix.chart && (fix.chart.before.length > 0 || fix.chart.after.length > 0) && (
                <BeforeAfterChart chart={fix.chart} />
              )}
            </div>
            {fix.status === "confirmed" && (
              <div onClick={onGoPatterns} className="el-btn" role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onGoPatterns(); }}
                style={{ marginTop: S[3], fontSize: T.sm, color: C.dim, cursor: "pointer" }}>
                This confirmed fix taught EchoLens a pattern — see Patterns →
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const ghost: React.CSSProperties = {
  background: "transparent", color: C.text2, border: `1px solid ${C.border3}`,
  borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, cursor: "pointer",
};

function BeforeAfterChart({ chart }: { chart: NonNullable<FixStatus["chart"]> }) {
  const max = Math.max(1, ...chart.before.map((p) => p.count), ...chart.after.map((p) => p.count));
  const Bars = ({ points, color }: { points: { date: string; count: number }[]; color: string }) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 0, height: 60 }}>
        {points.map((p) => (
          <div key={p.date} title={`${p.date}: ${p.count}`}
            style={{ flex: 1, height: `${Math.max(2, (p.count / max) * 100)}%`, background: color,
                     borderRadius: "2px 2px 0 0", opacity: 0.85 }} />
        ))}
      </div>
    </div>
  );
  const rate = (r: number | null) => (r == null ? "—" : `${r.toFixed(1)}/day`);
  return (
    <div style={{ marginTop: S[3] }}>
      <div style={{ fontSize: T.sm, color: C.muted, marginBottom: S[2] }}>
        Complaint volume for “{chart.terms.join(", ")}” around the fix.
      </div>
      <div style={{ display: "flex", gap: S[4], alignItems: "stretch" }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginBottom: S[1] }}>
            BEFORE · {rate(chart.before_rate)}
          </div>
          <Bars points={chart.before} color={C.bad} />
        </div>
        <div style={{ width: 1, background: C.border3, alignSelf: "stretch" }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: mono, fontSize: T.micro, color: C.faint, marginBottom: S[1] }}>
            AFTER · {rate(chart.after_rate)}
          </div>
          <Bars points={chart.after} color={C.good} />
        </div>
      </div>
    </div>
  );
}
