import { useEffect, useState } from "react";
import { Investigation, api, canReview, getActiveProduct } from "../../api";
import { useAsync } from "../../hooks";
import { withToast } from "../../components/Toast";
import { when } from "../../format";
import { C, MEASURE, R, S, T, mono } from "../../theme";
import { BeforeAfterChart, EmptyState, Label } from "../../ui";
import { FollowupPanel, ReplyPanel } from "./ReplyPanel";
import { TrackerMenu } from "../../components/TrackerMenu";

interface Props {
  inv: Investigation;
  onReload: () => Promise<unknown> | void;
  onGoPatterns: () => void;
}

const FIX_META: Record<string, { label: string; color: string; body: string }> = {
  issue_open: {
    label: "Issue open", color: C.info,
    body: "The issue is filed and open. When it closes, EchoLens starts a 14-day watch on the complaints it was meant to stop."
  },
  waiting_for_release: {
    label: "Waiting for release", color: C.info,
    body: "The fix isn't judged until the fixed version reaches users — the watch starts at the first review on it."
  },
  watching: {
    label: "In verification", color: C.accent,
    body: "The fix shipped. EchoLens is watching complaint volume for 14 days to see whether the fix actually worked."
  },
  confirmed: {
    label: "Verified fixed", color: C.good,
    body: "Complaints dropped and stayed down after the fix shipped. This is what earns a pattern."
  },
  inconclusive: {
    label: "Inconclusive", color: C.accent,
    body: "Complaints fell after the fix, but not far enough to call it fixed. This is a partial improvement, not a verified one — your call on whether it worked."
  },
  persists_reopened: {
    label: "Fix didn't hold", color: C.bad,
    body: "The issue closed but the complaints continued at the same rate. The case was re-opened."
  },
  regressed: {
    label: "Regressed", color: C.bad,
    body: "The complaints stopped, then came back. Something re-introduced the cause."
  }
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
  // Is a GitHub repo connected to this product? Only a clearly-known "no"
  // disables the button; while loading or on error we leave it to the server.
  const prods = useAsync(() => api.products(), []);
  const activeId = getActiveProduct() ?? prods.data?.active_product_id ?? null;
  const activeProduct = prods.data?.products.find((p) => p.id === activeId);
  const noRepo = !!activeProduct && !activeProduct.github_repo;
  const fix = f?.fix;
  const [version, setVersion] = useState(fix?.fixed_in_version ?? "");
  const [shipOpen, setShipOpen] = useState(false);
  const [shipDate, setShipDate] = useState(fix?.shipped_at?.slice(0, 10) ?? new Date().toISOString().slice(0, 10));
  const [shipNote, setShipNote] = useState(fix?.shipped_note ?? "");
  useEffect(() => { setVersion(fix?.fixed_in_version ?? ""); }, [f?.id, fix?.fixed_in_version]);
  useEffect(() => {
    setShipDate(fix?.shipped_at?.slice(0, 10) ?? new Date().toISOString().slice(0, 10));
    setShipNote(fix?.shipped_note ?? "");
  }, [f?.id, fix?.shipped_at, fix?.shipped_note]);
  const repliesRequested = typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("replies") === "1";

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

  const meta = fix ? FIX_META[fix.status] : null;
  const canCreate = canReview() && inv.status === "resolved";
  const thin = ["insufficient_evidence", "needs_human", "budget_exhausted"].includes(inv.status);
  const versionOpen = !!fix && ["issue_open", "waiting_for_release", "watching"].includes(fix.status);

  const saveVersion = async () => {
    setBusy("version");
    const r = await withToast(() => api.setFixedVersion(f.id, version.trim() || null), {
      success: (res) => res.fixed_in_version
        ? `Watching for v${res.fixed_in_version} to reach users.` : "Version cleared.",
      failure: "Couldn't save the version"
    });
    setBusy(null);
    if (r) await onReload();
  };

  const markShipped = async () => {
    setBusy("shipped");
    const result = await withToast(() => api.markFixShipped(f.id, {
      version: version.trim() || null, date: shipDate, note: shipNote.trim()
    }), { success: "Fix marked shipped — verification started.", failure: "Couldn't mark the fix shipped" });
    setBusy(null);
    if (result) { setShipOpen(false); await onReload(); }
  };

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
      failure: "Couldn't open the GitHub issue"
    });
    setBusy(null);
    if (r) await onReload();
  };

  const notify = async () => {
    setBusy("notify");
    await withToast(() => api.notifyFinding(f.id), {
      success: (res) => `Sent to ${res.routed}.`,
      failure: "Couldn't send that notification"
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
              open on GitHub
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
              File a ticket to track the work, or mark the fix shipped below to start verification.
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: S[2], marginTop: S[3],
                          flexWrap: "wrap" }}>
              <button onClick={copyIssue} disabled={!!busy} className="el-btn" style={ghost}>
                {busy === "copy" ? "Copying…" : "Copy as issue"}
              </button>
              {canCreate && (
                <button onClick={createIssue} disabled={!!busy || noRepo}
                  title={noRepo ? "No GitHub repo is connected to this product. Connect one in Sources first." : undefined}
                  className="el-btn el-btn--primary"
                  style={{ background: C.accent, color: C.onAccent, border: "none",
                           borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, fontWeight: 600 }}>
                  {busy === "create" ? "Creating…" : "Create GitHub issue"}
                </button>
              )}
              {canCreate && noRepo && (
                <span style={{ fontSize: T.xs, color: C.dim }}>
                  Connect a GitHub repo in Sources to file issues from here.
                </span>
              )}
              {/* Linear / Jira, when configured. */}
              {canCreate && (
                <TrackerMenu findingId={f.id} exclude={["github"]} disabled={!!busy}
                  onFiled={() => { void onReload(); }} />
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
        {canCreate && (
          <div style={{ marginBottom: S[3] }}>
            <button className="el-btn" style={ghost} aria-expanded={shipOpen}
              onClick={() => setShipOpen((open) => !open)} disabled={!!busy}>
              {fix?.shipped_at ? "Update shipped fix" : "Mark fix shipped"}
            </button>
            {shipOpen && (
              <div style={{ marginTop: S[2], padding: S[4], background: C.card,
                            border: `1px solid ${C.border2}`, borderRadius: R.card }}>
                <div style={{ fontSize: T.sm, color: C.muted, marginBottom: S[3] }}>
                  Start verification without a GitHub issue. Set a version to wait until it reaches users.
                  {fix && fix.status !== "issue_open" && " Saving restarts verification for this release."}
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: S[3] }}>
                  <label style={{ fontSize: T.sm, color: C.muted }}>
                    Version (optional)
                    <input aria-label="Shipped version" value={version} maxLength={32} placeholder="e.g. 3.2.1"
                      onChange={(e) => setVersion(e.target.value)} style={{ ...input, width: 150 }} />
                  </label>
                  <label style={{ fontSize: T.sm, color: C.muted }}>
                    Shipped date
                    <input type="date" value={shipDate} max={new Date().toISOString().slice(0, 10)}
                      onChange={(e) => setShipDate(e.target.value)} style={input} />
                  </label>
                </div>
                <label htmlFor="shipped-note" style={{ display: "block", fontSize: T.sm, color: C.muted, marginTop: S[3] }}>
                  Note (optional)
                </label>
                <textarea id="shipped-note" value={shipNote} maxLength={4000}
                  onChange={(e) => setShipNote(e.target.value)}
                  style={{ ...input, width: "100%", minHeight: 64, resize: "vertical", boxSizing: "border-box" }} />
                <button className="el-btn el-btn--primary" style={{ ...ghost, marginTop: S[3] }}
                  onClick={markShipped} disabled={!!busy || !shipDate}>
                  {busy === "shipped" ? "Saving…" : "Save shipped fix"}
                </button>
              </div>
            )}
          </div>
        )}
        {!fix || !meta ? (
          <EmptyState
            title="Verification hasn't started"
            body="Mark the fix shipped, or close a linked issue. EchoLens watches the complaints it should stop and reports back here — verified, or not."
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
              {fix.status === "waiting_for_release" && fix.fixed_in_version && (
                <div style={{ fontSize: T.sm, color: C.text2, marginTop: S[2] }}>
                  Waiting for v{fix.fixed_in_version} to reach users
                  {fix.release && fix.release.state !== "not_seen"
                    ? ` — ${fix.release.review_count} of ${fix.release.needed_reviews} reviews so far (or ${fix.release.needed_days} days after the first).`
                    : " — no reviews on it yet."}
                </div>
              )}
              {versionOpen && canReview() && (
                <div style={{ marginTop: S[3] }}>
                  <label style={{ fontSize: T.sm, color: C.muted, display: "block", marginBottom: S[1] }}
                    htmlFor="fixed-in-version">Fixed in version</label>
                  <div style={{ display: "flex", gap: S[2], flexWrap: "wrap" }}>
                    <input id="fixed-in-version" value={version} placeholder="e.g. 3.2.1"
                      onChange={(e) => setVersion(e.target.value)}
                      style={{ background: C.bg, color: C.text2, border: `1px solid ${C.border3}`,
                               borderRadius: R.control, padding: `${S[1]} ${S[2]}`, fontSize: T.base,
                               fontFamily: mono, width: 130 }} />
                    <button className="el-btn" style={ghost} onClick={saveVersion}
                      disabled={!!busy || version.trim() === (fix.fixed_in_version ?? "")}>
                      {busy === "version" ? "Saving…" : "Save"}
                    </button>
                  </div>
                  {fix.version_hint && (
                    <div style={{ fontSize: T.xs, color: C.dim, marginTop: S[1], lineHeight: "var(--el-lh-normal)" }}>
                      Mobile fixes reach users days after the issue closes. Set the version and the
                      watch starts when it does, instead of judging the fix too early.
                    </div>
                  )}
                </div>
              )}
              {fix.chart && <BeforeAfterChart chart={fix.chart} />}
            </div>
            {fix.status === "confirmed" && (
              <button onClick={onGoPatterns} className="el-btn"
                style={{ marginTop: S[3], fontSize: T.sm, color: C.dim }}>
                This confirmed fix taught EchoLens a pattern — see Patterns →
              </button>
            )}
          </>
        )}

        {thin && <FollowupPanel findingId={f.id} />}
        {inv.status === "resolved" && <ReplyPanel findingId={f.id} expand={repliesRequested} />}
      </div>
    </div>
  );
}

const ghost: React.CSSProperties = {
  background: "transparent", color: C.text2, border: `1px solid ${C.border3}`,
  borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base
};

const input: React.CSSProperties = {
  display: "block", marginTop: S[1], background: C.bg, color: C.text2,
  border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`,
  fontSize: T.base, fontFamily: "inherit"
};
