import { useState } from "react";
import { CommentNode, api, canReview } from "../../api";
import { useAsync } from "../../hooks";
import { C, MEASURE, R, S, T, mono, sans } from "../../theme";
import { Centered, EmptyState, ErrorState, Label } from "../../ui";
import { Icon } from "../../components/Icon";

// The discussion on one case. Anyone who can read the case can read the thread;
// posting needs a reviewer, because a comment on a review thread has to be
// attributable to a real person.
export function DiscussionTab({ caseId }: { caseId: number }) {
  const { data, loading, error, reload } = useAsync(() => api.comments(caseId), [caseId]);
  const [draft, setDraft] = useState("");
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const mayPost = canReview();

  const submit = async () => {
    const body = draft.trim();
    if (!body || busy) return;
    setBusy(true);
    setPostError(null);
    try {
      await api.postComment(caseId, body, replyTo ?? undefined);
      setDraft("");
      setReplyTo(null);
      reload();
    } catch (e) {
      setPostError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  if (loading && !data) return <Centered>Loading discussion…</Centered>;
  if (error) return <ErrorState title="Couldn't load the discussion" onRetry={reload} />;

  const comments = data?.comments ?? [];

  return (
    <div style={{ padding: `${S[5]} ${S[6]}`, maxWidth: MEASURE }}>
      <Label style={{ marginBottom: S[3] }}>
        DISCUSSION{comments.length ? ` · ${comments.length}` : ""}
      </Label>

      {comments.length === 0 && (
        <EmptyState
          title="No discussion yet"
          body={mayPost
            ? "Add a comment to record what you think of this conclusion. Mention a teammate with @their-name to pull them in."
            : "Nobody has commented on this case yet."}
        />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: S[4] }}>
        {comments.map((c) => (
          <Thread key={c.id} node={c} onReply={mayPost ? setReplyTo : undefined}
            activeReply={replyTo} />
        ))}
      </div>

      {mayPost ? (
        <div style={{ marginTop: S[5], borderTop: `1px solid ${C.border}`, paddingTop: S[4] }}>
          {replyTo != null && (
            <div style={{ display: "flex", alignItems: "center", gap: S[2], marginBottom: S[2] }}>
              <span style={{ fontSize: T.sm, color: C.muted }}>
                Replying to comment #{replyTo}
              </span>
              <button onClick={() => setReplyTo(null)} className="el-btn el-btn--inline"
                style={{ fontSize: T.sm, color: C.accent }}>
                Cancel
              </button>
            </div>
          )}
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Write a comment"
            placeholder="What do you make of this conclusion? Use @name to mention someone."
            rows={3}
            style={{
              width: "100%", background: C.bgRaised, border: `1px solid ${C.border3}`,
              borderRadius: R.control, color: C.text, fontFamily: sans, fontSize: T.md,
              padding: S[3], resize: "vertical"
            }}
          />
          {postError && (
            <div style={{ color: C.bad, fontSize: T.sm, marginTop: S[2] }}>{postError}</div>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: S[2] }}>
            <button onClick={submit} disabled={!draft.trim() || busy}
              className="el-btn el-btn--primary"
              style={{
                borderRadius: R.control, padding: `${S[2]} ${S[4]}`, fontWeight: 600,
                cursor: draft.trim() && !busy ? "pointer" : "not-allowed",
                opacity: draft.trim() && !busy ? 1 : 0.5
              }}>
              {busy ? "Posting…" : "Comment"}
            </button>
          </div>
        </div>
      ) : (
        <div style={{ marginTop: S[5], borderTop: `1px solid ${C.border}`, paddingTop: S[4],
                      fontSize: T.sm, color: C.muted }}>
          Sign in as a reviewer to join the discussion.
        </div>
      )}
    </div>
  );
}

function Thread({ node, onReply, activeReply }: {
  node: CommentNode;
  onReply?: (id: number) => void;
  activeReply: number | null;
}) {
  return (
    <div>
      <Bubble node={node} onReply={onReply} activeReply={activeReply} />
      {node.replies.length > 0 && (
        <div style={{ marginLeft: S[5], marginTop: S[3], borderLeft: `2px solid ${C.border2}`,
                      paddingLeft: S[4], display: "flex", flexDirection: "column", gap: S[3] }}>
          {node.replies.map((r) => (
            <Bubble key={r.id} node={r} activeReply={activeReply} />
          ))}
        </div>
      )}
    </div>
  );
}

function Bubble({ node, onReply, activeReply }: {
  node: CommentNode;
  onReply?: (id: number) => void;
  activeReply?: number | null;
}) {
  const when = node.created_at
    ? new Date(node.created_at).toLocaleString(undefined,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "";
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: S[2], marginBottom: S[1] }}>
        <span style={{ fontFamily: mono, fontSize: T.sm, color: C.text3, fontWeight: 600 }}>
          {node.author}
        </span>
        <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>{when}</span>
        {node.edited && (
          <span style={{ fontSize: T.micro, color: C.faint }}>· edited</span>
        )}
      </div>
      {node.deleted ? (
        // The row stays so replies keep their anchor and the record of a
        // conversation having happened is not quietly rewritten.
        <div style={{ fontSize: T.base, color: C.faint, fontStyle: "italic" }}>
          This comment was deleted.
        </div>
      ) : (
        <div style={{ fontSize: T.md, color: C.text2, lineHeight: "var(--el-lh-normal)",
                      whiteSpace: "pre-wrap" }}>
          {renderMentions(node.body ?? "")}
        </div>
      )}
      {onReply && !node.deleted && (
        <button onClick={() => onReply(node.id)} className="el-btn el-btn--inline"
          aria-label={`Reply to ${node.author}`}
          style={{
            marginTop: S[1], fontSize: T.sm,
            color: activeReply === node.id ? C.accent : C.dim
          }}>
          <Icon name="reply" size={12} /> Reply
        </button>
      )}
    </div>
  );
}

// @handles are highlighted so a mention reads as one, without turning the body
// into HTML — the text stays text.
function renderMentions(body: string) {
  const parts = body.split(/(@[A-Za-z0-9._%+-]+)/g);
  return parts.map((p, i) =>
    p.startsWith("@")
      ? <span key={i} style={{ color: C.accent, fontWeight: 600 }}>{p}</span>
      : <span key={i}>{p}</span>
  );
}
