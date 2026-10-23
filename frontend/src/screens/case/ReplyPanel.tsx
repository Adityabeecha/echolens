import { useState } from "react";
import { api } from "../../api";
import { withToast } from "../../components/Toast";
import { when } from "../../format";
import { useAsync } from "../../hooks";
import { C, R, S, T, mono } from "../../theme";
import { Label } from "../../ui";

const ghost: React.CSSProperties = {
  background: "transparent", color: C.text2, border: `1px solid ${C.border3}`,
  borderRadius: R.control, padding: `${S[1]} ${S[2]}`, fontSize: T.sm
};

async function copy(text: string, ok: string) {
  await withToast(() => navigator.clipboard.writeText(text), {
    success: ok, failure: "Couldn't copy to your clipboard"
  });
}

/**
 * Draft replies for the reviewers a resolved finding affected.
 *
 * Draft only: nothing is posted anywhere. The team copies a draft and pastes it
 * into the store console themselves.
 */
export function ReplyPanel({ findingId }: { findingId: number }) {
  const { data, error, loading } = useAsync(() => api.replyDrafts(findingId), [findingId]);
  const [open, setOpen] = useState(false);

  if (loading) return null;
  if (error || !data) return null;
  // "Copy all" is for the English reviewers; a draft for someone who wrote in
  // another language needs translating first, so it is copied on its own.
  const drafted = data.drafts.filter((d) => d.draft && d.language === "en");
  const intro =
    data.mode === "fixed" ? "The fix is verified. Let the people who complained know."
    : data.mode === "shipped" ? "A fix has shipped. Let the people who complained know."
    : "These reviewers reported this problem. A holding reply tells them you saw it.";

  return (
    <>
      <Label style={{ margin: "26px 0 10px" }}>REPLY TO AFFECTED REVIEWERS</Label>
      <div style={{ padding: S[4], background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
        {data.total === 0 ? (
          <div style={{ fontSize: T.base, color: C.text3 }}>
            No matching negative reviews in the window, so there is no one to reply to.
          </div>
        ) : (
          <>
            <div style={{ fontSize: T.base, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
              {intro} {data.total} negative {data.total === 1 ? "review matches" : "reviews match"} this problem
              {data.skipped_on_fixed_version > 0 &&
                ` (${data.skipped_on_fixed_version} already on v${data.fixed_in_version}, left out)`}.
              Drafts only — nothing is sent from here.
            </div>
            <div style={{ display: "flex", gap: S[2], marginTop: S[3], flexWrap: "wrap", alignItems: "center" }}>
              <button className="el-btn" style={ghost} disabled={drafted.length === 0}
                onClick={() => copy(drafted.map((d) => d.draft).join("\n\n"),
                  `Copied ${drafted.length} drafts.`)}>
                Copy all
              </button>
              {data.console_url && (
                <a href={data.console_url} target="_blank" rel="noreferrer"
                  style={{ fontFamily: mono, fontSize: T.sm, color: C.info, textDecoration: "none" }}>
                  Open in {data.console_name}
                </a>
              )}
              <button className="el-btn" style={{ ...ghost, border: "none", color: C.dim }}
                aria-expanded={open} onClick={() => setOpen((o) => !o)}>
                {open ? "Hide drafts" : `Show ${data.shown} drafts`}
              </button>
            </div>
            <div style={{ fontSize: T.xs, color: C.dim, marginTop: S[2] }}>{data.translation_note}</div>
            {open && (
              <ul style={{ listStyle: "none", margin: `${S[3]} 0 0`, padding: 0, display: "grid", gap: S[3] }}>
                {data.drafts.map((d) => (
                  <li key={d.review_id} style={{ borderTop: `1px solid ${C.border2}`, paddingTop: S[3] }}>
                    <div style={{ fontFamily: mono, fontSize: T.xs, color: C.faint }}>
                      {d.rating}★{d.version ? ` · v${d.version}` : ""}{d.created_at ? ` · ${when(d.created_at)}` : ""}
                    </div>
                    <div style={{ fontSize: T.sm, color: C.muted, margin: `${S[1]} 0`, fontStyle: "italic" }}>
                      “{d.excerpt}”
                    </div>
                    {d.excerpt_en && (
                      <div style={{ fontSize: T.sm, color: C.dim, margin: `0 0 ${S[1]}` }}>
                        <span style={{ fontFamily: mono, fontSize: T.micro, color: C.faint }}>
                          TRANSLATED FROM {(d.lang_name ?? "").toUpperCase()}
                        </span>{" "}
                        {d.excerpt_en}
                      </div>
                    )}
                    {d.draft && (
                      <div style={{ display: "flex", gap: S[2], alignItems: "flex-start" }}>
                        <div style={{ flex: 1, fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-normal)" }}>
                          {d.draft}
                        </div>
                        <button className="el-btn" style={ghost} onClick={() => copy(d.draft!, "Draft copied.")}>
                          Copy
                        </button>
                      </div>
                    )}
                    {d.draft_translated && (
                      <div style={{ display: "flex", gap: S[2], alignItems: "flex-start", marginTop: S[2] }}>
                        <div style={{ flex: 1, fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-normal)" }}>
                          <div style={{ fontFamily: mono, fontSize: T.micro, color: C.accent, marginBottom: S[1] }}>
                            MACHINE-TRANSLATED · {(d.lang_name ?? "").toUpperCase()}
                          </div>
                          {d.draft_translated}
                        </div>
                        <button className="el-btn" style={ghost}
                          onClick={() => copy(d.draft_translated!, "Translated draft copied — check it before posting.")}>
                          Copy
                        </button>
                      </div>
                    )}
                    {d.note && <div style={{ fontSize: T.sm, color: C.accent, marginTop: S[1] }}>{d.note}</div>}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </>
  );
}

/**
 * Questions the team could put to affected users when a case ended on thin
 * evidence (in-app prompt or reply text). Hidden when there are none.
 */
export function FollowupPanel({ findingId }: { findingId: number }) {
  const { data } = useAsync(() => api.followupQuestions(findingId), [findingId]);
  if (!data || data.questions.length === 0) return null;
  return (
    <>
      <Label style={{ margin: "26px 0 10px" }}>QUESTIONS TO ASK AFFECTED USERS</Label>
      <div style={{ padding: S[4], background: C.card, border: `1px solid ${C.border2}`, borderRadius: R.card }}>
        <div style={{ fontSize: T.base, color: C.text3, lineHeight: "var(--el-lh-normal)" }}>
          The evidence was too thin to name a cause. These would help settle it.
        </div>
        <ul style={{ listStyle: "none", margin: `${S[3]} 0 0`, padding: 0, display: "grid", gap: S[3] }}>
          {data.questions.map((q) => (
            <li key={q.question} style={{ display: "flex", gap: S[2], alignItems: "flex-start" }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: T.base, color: C.text2, lineHeight: "var(--el-lh-normal)" }}>{q.question}</div>
                <div style={{ fontSize: T.xs, color: C.dim, marginTop: S[1] }}>{q.why}</div>
              </div>
              <button className="el-btn" style={ghost} onClick={() => copy(q.question, "Question copied.")}>
                Copy
              </button>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
