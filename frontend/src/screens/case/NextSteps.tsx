import { ReactNode, useEffect, useState } from "react";
import { Investigation, TrackerId, api, canReview, errorMessage, isGuest } from "../../api";
import { toast, withToast } from "../../components/Toast";
import { NumberedSteps, SerifHeadline } from "../../components/casefile";
import { Icon } from "../../components/Icon";
import { useAsync, useDialog } from "../../hooks";
import { Button } from "../../ui";

/** Why the main actions are unavailable, or null when they are not. */
export function blockedReason(inv: Investigation): string | null {
  if (isGuest()) return "Sign in to send problems or mark fixes — the demo is read-only.";
  if (!canReview()) return "Sending and marking fixes needs reviewer access.";
  if (!inv.finding) return "There is no answer to send yet.";
  if (inv.finding.status === "challenged") return "This answer was challenged — the new investigation takes over.";
  if (inv.status !== "resolved") return "Only a confirmed problem can be sent — this one isn't proven yet.";
  return null;
}

function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useDialog(onClose);
  return (
    <>
      <div className="cv-scrim" onClick={onClose} aria-hidden="true" />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className="cv-dialog">
        <div className="cv-dialog__head">
          <SerifHeadline as="h2" size="section">{title}</SerifHeadline>
          <button type="button" className="cv-close" onClick={onClose} aria-label="Close"><Icon name="close" size={15} /></button>
        </div>
        {children}
      </div>
    </>
  );
}

/**
 * The GitHub issue, already written from the case (exporting.finding_ticket),
 * editable before it goes. Whatever is edited, the server re-attaches the
 * evidence section, so every exhibit travels with it.
 */
export function IssuePreview({ inv, onClose, onFiled }: {
  inv: Investigation; onClose: () => void; onFiled: () => Promise<unknown> | void;
}) {
  const f = inv.finding!;
  const ticket = useAsync(() => api.findingIssue(f.id), [f.id]);
  const trackers = useAsync(() => api.trackers(), []);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<TrackerId | "copy" | null>(null);
  useEffect(() => {
    if (ticket.data) { setTitle(ticket.data.title); setBody(ticket.data.body); }
  }, [ticket.data]);
  // Already filed: offer the text again, never a second issue.
  const filed = f.fix?.issue_url ? `Already sent as GitHub issue #${f.fix.issue_number}.` : null;
  const blocked = filed ?? blockedReason(inv);
  const configured = new Map((trackers.data?.trackers ?? []).map((t) => [t.id, t]));
  const repo = ticket.data?.repo;

  const file = async (tracker: TrackerId) => {
    setBusy(tracker);
    const r = await withToast(() => api.createTicket(f.id, tracker, { title, body }), {
      success: (res) => `Sent — ${res.tracker === "github" ? `GitHub issue #${res.number}` : `${res.tracker} ${res.number}`}.`,
      failure: "Couldn't send it",
    });
    setBusy(null);
    if (r) { await onFiled(); onClose(); }
  };
  const copy = async () => {
    setBusy("copy");
    try {
      await navigator.clipboard.writeText(`# ${title}\n\n${body}`);
      toast.ok("Copied — paste it into any tracker.");
    } catch {
      toast.fail("Your browser blocked the clipboard. Select the text and copy it instead.");
    }
    setBusy(null);
  };

  return (
    <Dialog title="Send it to your developers" onClose={onClose}>
      <p style={{ margin: 0, fontSize: 15, color: "var(--el-body)", lineHeight: 1.55 }}>
        The issue is already written from this problem, with every exhibit attached. Edit anything before it goes —
        the exhibits stay attached even if you trim the text.
      </p>
      {ticket.error && <div role="alert" className="cv-banner">Couldn't build the issue — {errorMessage(ticket.error)}</div>}
      {ticket.loading && !ticket.data && <div className="cv-banner" role="status">Writing the issue…</div>}
      {ticket.data && (
        <>
          <label className="cv-field"><span>Title</span>
            <input className="cv-input" value={title} maxLength={256} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="cv-field"><span>Description</span>
            <textarea className="cv-input cv-mono" rows={14} value={body} onChange={(e) => setBody(e.target.value)} />
          </label>
          <div className="cv-row">
            <Button variant="primary" loading={busy === "github"} disabled={!!blocked || !!busy || !repo || !configured.get("github")?.configured || !title.trim()}
              title={blocked ?? (!repo ? "No GitHub repo is connected to this product — connect one in Sources."
                : !configured.get("github")?.configured ? "GitHub isn't set up on this server — copy the issue instead." : undefined)}
              onClick={() => file("github")}>Create GitHub issue</Button>
            {(["linear", "jira"] as const).filter((t) => configured.get(t)?.configured).map((t) => (
              <Button key={t} variant="ghost" loading={busy === t} disabled={!!blocked || !!busy} onClick={() => file(t)}>
                Create {configured.get(t)!.label} issue</Button>
            ))}
            <Button variant="ghost" loading={busy === "copy"} disabled={!!busy} onClick={copy}>Copy</Button>
          </div>
          {(blocked || !repo) && <div style={{ fontSize: 13, color: "var(--el-muted)" }}>
            {blocked ?? "No GitHub repo is connected to this product — connect one in Sources, or copy the issue."}</div>}
        </>
      )}
    </Dialog>
  );
}

/** "Fix shipped": the version (and day) the fix reached users; starts the 14-day watch. */
export function FixShippedDialog({ inv, onClose, onSaved }: {
  inv: Investigation; onClose: () => void; onSaved: () => Promise<unknown> | void;
}) {
  const f = inv.finding!;
  const fix = f.fix;
  const today = new Date().toISOString().slice(0, 10);
  const [version, setVersion] = useState(fix?.fixed_in_version ?? "");
  const [date, setDate] = useState(fix?.shipped_at?.slice(0, 10) ?? today);
  const [note, setNote] = useState(fix?.shipped_note ?? "");
  const [busy, setBusy] = useState(false);
  const blocked = blockedReason(inv);
  const save = async () => {
    setBusy(true);
    const r = await withToast(() => api.markFixShipped(f.id, { version: version.trim() || null, date, note: note.trim() }), {
      success: "Fix marked shipped — EchoLens is watching the reviews now.", failure: "Couldn't mark the fix shipped",
    });
    setBusy(false);
    if (r) { await onSaved(); onClose(); }
  };
  return (
    <Dialog title="When did the fix ship?" onClose={onClose}>
      <p style={{ margin: 0, fontSize: 15, color: "var(--el-body)", lineHeight: 1.55 }}>
        Tell EchoLens the version and it waits until that version reaches users, then watches the reviews for 14 days.
        {fix && fix.status !== "issue_open" ? " Saving again restarts the watch for this release." : ""}
      </p>
      <div className="cv-row" style={{ alignItems: "flex-end" }}>
        <label className="cv-field" style={{ flex: "1 1 160px" }}><span>Version (optional)</span>
          <input className="cv-input cv-mono" value={version} maxLength={32} placeholder="e.g. 3.2.1"
            onChange={(e) => setVersion(e.target.value)} aria-label="Shipped version" />
        </label>
        <label className="cv-field" style={{ flex: "1 1 160px" }}><span>Shipped on</span>
          <input className="cv-input" type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} />
        </label>
      </div>
      <label className="cv-field"><span>Note (optional)</span>
        <textarea className="cv-input" rows={3} value={note} maxLength={4000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="cv-row">
        <Button variant="primary" loading={busy} disabled={!!blocked || !date} title={blocked ?? undefined} onClick={save}>
          Save — start watching</Button>
        <Button variant="quiet" onClick={onClose}>Cancel</Button>
      </div>
      {blocked && <div style={{ fontSize: 13, color: "var(--el-muted)" }}>{blocked}</div>}
    </Dialog>
  );
}

const FIX_LINE: Record<string, string> = {
  issue_open: "Waiting for the fix — EchoLens starts watching when the issue closes or you mark it shipped.",
  waiting_for_release: "Waiting for the fixed version to reach users.",
  watching: "Watching the reviews now.",
  confirmed: "Done — complaints fell after the fix.",
  inconclusive: "Complaints fell, but not far enough to call it fixed.",
  persists_reopened: "The fix didn't hold — the problem was reopened.",
  regressed: "It came back after the fix.",
};

/** What to do next: send it, say when the fix shipped, and the automatic watch. */
export function NextStepsBlock({ inv, onSend, onShipped }: {
  inv: Investigation; onSend: () => void; onShipped: () => void;
}) {
  const f = inv.finding;
  const blocked = blockedReason(inv);
  const fix = f?.fix;
  const filed = !!fix?.issue_url;
  return (
    <div className="cv-steps">
      <NumberedSteps steps={[
        { id: "send",
          text: filed
            ? <>Sent to your developers as <a href={fix!.issue_url} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>
                GitHub issue #{fix!.issue_number}</a></>
            : inv.status !== "resolved"
              ? "Once it's confirmed, send it to your developers — the issue will already be written, with every exhibit attached"
              : "Send it to your developers — the GitHub issue is already written, with every exhibit attached",
          action: filed
            ? <Button variant="ghost" onClick={onSend}>Copy the issue again</Button>
            : <Button variant="primary" disabled={!!blocked} title={blocked ?? undefined} onClick={onSend}>Review &amp; send</Button> },
        { id: "ship",
          text: fix?.shipped_at || fix?.fixed_in_version
            ? `Fix shipped${fix.fixed_in_version ? ` in ${fix.fixed_in_version}` : ""} — ${FIX_LINE[fix.status] ?? "watching"}`
            : "When the fix ships, tell EchoLens the version",
          action: <Button variant="ghost" disabled={!!blocked} title={blocked ?? undefined} onClick={onShipped}>
            {fix?.shipped_at ? "Update" : "Fix shipped"}</Button> },
        { id: "watch", automatic: true,
          text: <>We watch the reviews for 14 days, then stamp it <b style={{ color: "var(--el-green)" }}>FIX WORKED</b> — or reopen it</> },
      ]} />
      {blocked && <div style={{ fontSize: 13, color: "var(--el-muted)", marginTop: 8 }}>{blocked}</div>}
    </div>
  );
}

const CHALLENGE_REASONS: [string, string][] = [
  ["wrong_cause", "Wrong cause"], ["weak_evidence", "The proof is too weak"],
  ["wrong_severity", "It's not that bad"], ["already_knew", "We already knew"],
];

/** "Think this is wrong?" and "Looks right" — the reviewer's verdict on the answer. */
export function VerdictActions({ inv, onReload, onReviewed, onOpenCase }: {
  inv: Investigation; onReload: () => Promise<unknown> | void; onReviewed: () => void;
  onOpenCase: (id: number, status?: string) => void;
}) {
  const f = inv.finding;
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [actualCause, setActualCause] = useState("");
  const [busy, setBusy] = useState<"approve" | "challenge" | null>(null);
  if (!f || f.status === "challenged") {
    return f?.status === "challenged"
      ? <div className="cv-banner">You said this was wrong. A fresh investigation is working on it — see History for the link.</div>
      : null;
  }
  const reviewer = canReview();
  const approved = f.status === "approved";

  const approve = async () => {
    setBusy("approve");
    const ok = await withToast(() => api.review(f.id, "approve"), {
      success: "Approved — it stays here until a fix is confirmed.", failure: "Couldn't approve it",
    });
    setBusy(null);
    if (ok) { await onReload(); onReviewed(); }
  };
  const challenge = async () => {
    if (!note.trim()) return;
    setBusy("challenge");
    const r = await withToast(
      () => api.review(f.id, "challenge", note.trim(), reason || undefined, actualCause.trim() || undefined),
      { success: "Thanks — a fresh investigation is starting with your note.", failure: "Couldn't send that" });
    setBusy(null);
    if (!r) return;
    setOpen(false); setNote(""); setReason(""); setActualCause("");
    onReviewed();
    await onReload();
    if (r.reopened_investigation_id) onOpenCase(r.reopened_investigation_id, "running");
  };

  // The reviewer's verdict is the first decision on the page, so it is a pair of
  // real buttons above the steps — it used to be two underlined text links
  // below them, and after approving, disagreeing looked like a footnote.
  const canApprove = reviewer && !approved && !(inv.finding?.grounding_violations?.length);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className={`cv-verdict${approved ? " is-approved" : ""}`} role="group" aria-label="Your verdict">
        <div className="cv-verdict__text">
          {approved
            ? <><span className="cv-verdict__title">✓ You approved this answer.</span>
                <span className="cv-verdict__sub">It stays open until a fix is confirmed. Changed your mind? Reopen it.</span></>
            : <><span className="cv-verdict__title">Is this right?</span>
                <span className="cv-verdict__sub">{reviewer
                  ? "Approve it to keep it, or tell EchoLens what it got wrong and it looks again."
                  : "A reviewer approves the answer or sends it back."}</span></>}
        </div>
        <div className="cv-verdict__actions">
          {canApprove && (
            <Button variant="primary" loading={busy === "approve"} onClick={approve}
              title="Approving records that the answer is right; it stays until a fix is confirmed">
              Yes, approve it</Button>
          )}
          <Button variant="ghost" aria-expanded={open} disabled={!reviewer}
            title={reviewer ? undefined : "Needs reviewer access"} onClick={() => setOpen((o) => !o)}>
            {approved ? "Reopen, it isn't right" : "No, it isn't right"}</Button>
        </div>
      </div>
      {open && (
        <div className="cv-card">
          <div className="cv-row" role="group" aria-label="What's wrong">
            {CHALLENGE_REASONS.map(([v, label]) => (
              <button key={v} type="button" className="cv-chip-btn" aria-pressed={reason === v}
                onClick={() => setReason((r) => (r === v ? "" : v))}>{label}</button>
            ))}
          </div>
          <label className="cv-field"><span>What's wrong with it?</span>
            <textarea className="cv-input" rows={3} value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Battery complaints also mention charging — check those before blaming sync." />
          </label>
          <label className="cv-field"><span>What really caused it? (optional)</span>
            <textarea className="cv-input" rows={2} value={actualCause} maxLength={4000}
              onChange={(e) => setActualCause(e.target.value)} placeholder="Your team's explanation, if you know it" />
          </label>
          <div style={{ fontSize: 13, color: "var(--el-muted)" }}>
            Your note starts a fresh investigation, and your explanation is kept for next time.
          </div>
          <div className="cv-row">
            <Button variant="primary" loading={busy === "challenge"} disabled={!note.trim()} onClick={challenge}>
              Send and look again</Button>
            <Button variant="quiet" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      )}
    </div>
  );
}
