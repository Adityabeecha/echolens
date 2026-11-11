import { FormEvent, useState } from "react";
import { AuthUser, TeamMember, api, errorMessage, isGuest, startSession } from "../../api";
import { toast, withToast } from "../../components/Toast";
import { Dropdown, SerifHeadline } from "../../components/casefile";
import { useAsync } from "../../hooks";
import { Button, ErrorState, Skeleton } from "../../ui";

// Phase 3: accounts that work without the operator. "Your account" is for
// everyone signed in; "Team" is for admins.

const ROLE_OPTIONS = [
  { value: "viewer", label: "Viewer", hint: "Reads everything" },
  { value: "reviewer", label: "Reviewer", hint: "Also starts and approves investigations" },
  { value: "admin", label: "Admin", hint: "Also manages sources, limits and the team" },
] as const;
type Role = (typeof ROLE_OPTIONS)[number]["value"];
const roleLabel = (r: string) => ROLE_OPTIONS.find((o) => o.value === r)?.label ?? r;

const SIGN_IN_LABEL: Record<TeamMember["sign_in"], string> = {
  password: "Password",
  google: "Google",
  invited: "Invited — hasn't set a password yet",
};

const plainError = (err: unknown) => {
  const raw = errorMessage(err);
  return /→ \d{3}$/.test(raw) ? "That didn't work. Try again." : raw;
};

/** Settings → Your account: who you are signed in as, and your password. */
export function AccountSection() {
  const me = useAsync<AuthUser>(() => api.me(), []);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (isGuest()) return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">You're exploring the demo.</SerifHeadline>
      <p className="ps-note">Sign in with your own account to see and change its details.</p>
    </div>
  );
  if (me.loading && !me.data) return <div className="ps-sections"><Skeleton rows={2} height={84} /></div>;
  if (me.error || !me.data) return <ErrorState title="Couldn't load your account" onRetry={me.reload} />;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (next.length < 10) return setError("Use at least 10 characters for the new password.");
    if (next !== again) return setError("The two new passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      const r = await api.changePassword(current, next);
      startSession(r.csrf_token);  // this session continues under the new password
      setCurrent(""); setNext(""); setAgain("");
      toast.ok("Password changed. Any other device signed in to this account has been signed out.");
    } catch (err) {
      setError(plainError(err));
    } finally {
      setBusy(false);
    }
  };

  const google = me.data.sign_in === "google";
  return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">Signed in as {me.data.email ?? "this workspace's admin"}.</SerifHeadline>
      <p className="ps-note">Your role is <b>{roleLabel(me.data.role)}</b>. An admin can change it in Team.</p>
      <section className="ps-section" aria-labelledby="ps-password">
        <h2 id="ps-password">Password</h2>
        {google ? (
          <p className="ps-note">You sign in with Google, so there is no EchoLens password to change.</p>
        ) : me.data.id == null ? (
          <p className="ps-note">This local development workspace has no accounts, so there's no password to change.</p>
        ) : (
          <form className="ps-panel" onSubmit={save} noValidate>
            <label className="ps-field"><span>Current password</span>
              <input className="ps-input" type="password" autoComplete="current-password" value={current}
                onChange={(e) => setCurrent(e.target.value)} />
            </label>
            <label className="ps-field"><span>New password</span>
              <input className="ps-input" type="password" autoComplete="new-password" value={next}
                onChange={(e) => setNext(e.target.value)} />
              <span className="ps-muted">At least 10 characters.</span>
            </label>
            <label className="ps-field"><span>Type the new one again</span>
              <input className="ps-input" type="password" autoComplete="new-password" value={again}
                onChange={(e) => setAgain(e.target.value)} />
            </label>
            {error && <div role="alert" className="pub-error">{error}</div>}
            <div className="ps-row">
              <Button type="submit" variant="primary" loading={busy}>{busy ? "Saving…" : "Change password"}</Button>
              <span className="ps-muted">Other devices signed in to this account will be signed out.</span>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

/** A link the admin may need to pass on by hand, with a copy button. */
function LinkToSend({ email, link, why }: { email: string; link: string; why: string }) {
  const full = link.startsWith("http") ? link : `${window.location.origin}${link}`;
  return (
    <div className="ps-banner" role="status" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <span>{why} Send this link to <b>{email}</b>. It works once.</span>
      <code style={{ overflowWrap: "anywhere", fontSize: 13 }}>{full}</code>
      <div>
        <Button size="sm" variant="ghost" onClick={() => {
          void navigator.clipboard?.writeText(full).then(() => toast.ok("Link copied."), () => toast.fail("Couldn't copy. Select the link and copy it."));
        }}>Copy link</Button>
      </div>
    </div>
  );
}

/** Settings → Team: who can use this workspace, invites, roles, removal. */
export function TeamSection({ admin }: { admin: boolean }) {
  const team = useAsync(() => (admin ? api.teamMembers() : Promise.resolve(null)), [admin]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("reviewer");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<{ email: string; link: string; why: string } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<number | null>(null);

  if (!admin) return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">Your workspace admin manages the team.</SerifHeadline>
      <p className="ps-note">Ask them to add someone or change a role.</p>
    </div>
  );
  if (team.loading && !team.data) return <div className="ps-sections"><Skeleton rows={3} height={64} /></div>;
  if (team.error || !team.data) return <ErrorState title="Couldn't load the team" onRetry={team.reload} />;
  const { users, access_requests: requests, email_enabled: emailOn } = team.data;
  const noEmail = "Email isn't set up on this workspace, so nothing was sent.";

  const invite = async (address: string, as: Role, e?: FormEvent) => {
    e?.preventDefault();
    if (!address.trim()) return setError("Enter their email address.");
    setBusy("invite");
    setError(null);
    setLink(null);
    try {
      const r = await api.inviteUser(address.trim(), as);
      if (r.emailed) toast.ok(`Invite emailed to ${r.email}.`);
      else setLink({ email: r.email, link: r.link, why: noEmail });
      setEmail("");
      team.reload();
    } catch (err) {
      setError(plainError(err));
    } finally {
      setBusy(null);
    }
  };

  const resetLink = async (u: TeamMember) => {
    setBusy(`link-${u.id}`);
    setLink(null);
    try {
      const r = await api.resetLink(u.id);
      setLink({ email: r.email, link: r.link,
        why: r.purpose === "invite" ? "A fresh invite link; the old one no longer works." : "A reset link; their old links no longer work." });
    } catch (err) {
      toast.fail(plainError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">{users.length} {users.length === 1 ? "person" : "people"} on this team.</SerifHeadline>

      <section className="ps-section" aria-labelledby="ps-invite">
        <h2 id="ps-invite">Add someone</h2>
        <form className="ps-panel" onSubmit={(e) => void invite(email, role, e)} noValidate>
          <div className="ps-row" style={{ alignItems: "flex-end" }}>
            <label className="ps-field" style={{ flex: "1 1 240px" }}><span>Email</span>
              <input className="ps-input" type="email" autoComplete="off" value={email} placeholder="name@company.com"
                onChange={(e) => { setEmail(e.target.value); setError(null); }} style={{ maxWidth: "none" }} />
            </label>
            <div className="ps-field"><span>Role</span>
              <Dropdown label="Role" value={role} onChange={(v) => setRole(v as Role)}
                options={ROLE_OPTIONS.map((o) => ({ value: o.value, label: o.label, hint: o.hint }))} />
            </div>
            <Button type="submit" variant="primary" loading={busy === "invite"}>{busy === "invite" ? "Adding…" : "Add and send invite"}</Button>
          </div>
          <span className="ps-muted">
            They choose their own password from the invite link. {emailOn ? "It's emailed to them." : "Email isn't set up here, so you'll get the link to send yourself."}
          </span>
          {error && <div role="alert" className="pub-error">{error}</div>}
        </form>
        {link && <LinkToSend {...link} />}
      </section>

      {requests.length > 0 && (
        <section className="ps-section" aria-labelledby="ps-requests">
          <h2 id="ps-requests">Asking for access</h2>
          {requests.map((r) => (
            <div key={r.id} className="ps-card">
              <div className="ps-row" style={{ justifyContent: "space-between" }}>
                <span><b>{r.email}</b>{r.app && <span className="ps-muted"> · {r.app}</span>}</span>
                <div className="ps-row">
                  <Button size="sm" variant="ghost" loading={busy === "invite"} onClick={() => void invite(r.email, "viewer")}>Add as viewer</Button>
                  <Button size="sm" variant="quiet" onClick={() => void withToast(() => api.dismissAccessRequest(r.id),
                    { success: "Request dismissed.", failure: "Couldn't dismiss it" }).then(() => team.reload())}>Dismiss</Button>
                </div>
              </div>
              {r.note && <span className="ps-note">{r.note}</span>}
            </div>
          ))}
        </section>
      )}

      <section className="ps-section" aria-labelledby="ps-members">
        <h2 id="ps-members">Members</h2>
        {users.map((u) => (
          <div key={u.id} className="ps-card">
            <div className="ps-row" style={{ justifyContent: "space-between" }}>
              <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                <b>{u.email}</b>{u.you && <span className="ps-muted"> · you</span>}
                <br /><span className="ps-muted">{SIGN_IN_LABEL[u.sign_in]}</span>
              </span>
              <div className="ps-row">
                <Dropdown label={`Role for ${u.email}`} value={u.role as Role}
                  options={ROLE_OPTIONS.map((o) => ({ value: o.value, label: o.label, hint: o.hint }))}
                  onChange={(v) => void withToast(() => api.setUserRole(u.id, v), {
                    success: `${u.email} is now ${roleLabel(v).toLowerCase()}.`, failure: "Couldn't change the role",
                  }).then(() => team.reload())} />
                {u.sign_in !== "google" && (
                  <Button size="sm" variant="ghost" loading={busy === `link-${u.id}`} onClick={() => void resetLink(u)}>
                    {u.sign_in === "invited" ? "New invite link" : "Reset link"}
                  </Button>
                )}
                {!u.you && (confirmRemove === u.id ? (
                  <>
                    <Button size="sm" variant="danger" onClick={() => void withToast(() => api.removeUser(u.id), {
                      success: `${u.email} removed. Their comments stay.`, failure: "Couldn't remove them",
                    }).then(() => { setConfirmRemove(null); team.reload(); })}>Remove {u.email.split("@")[0]}</Button>
                    <Button size="sm" variant="quiet" onClick={() => setConfirmRemove(null)}>Keep</Button>
                  </>
                ) : (
                  <Button size="sm" variant="quiet" onClick={() => setConfirmRemove(u.id)}>Remove…</Button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
