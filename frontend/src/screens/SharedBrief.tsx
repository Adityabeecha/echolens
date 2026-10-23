import { useEffect, useState } from "react";
import { ShareBrief, api } from "../api";
import { when } from "../format";
import { applyTheme, resolveTheme } from "../themeMode";
import { C, MEASURE, R, S, T, mono, sans } from "../theme";
import { Centered, ErrorState, Label } from "../ui";

/**
 * The public, read-only view of one shared finding (#/share/<token>).
 *
 * Rendered without login, outside the app shell: no sidebar, no product
 * switcher, no links into cases. It shows exactly what the server's public
 * endpoint returns for the token — the brief the sharer chose to share — and
 * nothing that could lead a stranger to other data or other products.
 */
export function SharedBrief({ token }: { token: string }) {
  const [brief, setBrief] = useState<ShareBrief | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { applyTheme(resolveTheme()); }, []);

  useEffect(() => {
    let alive = true;
    setBrief(null);
    setError(null);
    api.publicShare(token)
      .then((b) => { if (alive) setBrief(b); })
      .catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [token]);

  useEffect(() => {
    if (brief) document.title = `${brief.headline} · EchoLens`;
  }, [brief]);

  return (
    <main style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: sans,
                   display: "flex", flexDirection: "column", alignItems: "center",
                   padding: `${S[8]} ${S[4]}` }}>
      <div style={{ width: "100%", maxWidth: MEASURE, display: "flex", flexDirection: "column", gap: S[5] }}>
        <div style={{ display: "flex", alignItems: "center", gap: S[2], flexWrap: "wrap" }}>
          <span style={{ fontFamily: mono, fontSize: T.sm, fontWeight: 600, color: C.accent,
                         letterSpacing: ".08em" }}>ECHOLENS</span>
          <span style={{ fontSize: T.xs, color: C.dim }}>
            Shared finding{brief?.product ? ` · ${brief.product}` : ""} · read-only
          </span>
        </div>

        {!brief && !error && <Centered>Loading the shared brief…</Centered>}

        {error && (
          <ErrorState title="This link doesn't open a brief"
            detail={`${error.replace(/\.$/, "")}. The link may have been revoked — ask whoever shared it for a new one.`} />
        )}

        {brief && (
          <article style={{ display: "flex", flexDirection: "column", gap: S[5],
                            background: C.card, border: `1px solid ${C.border2}`,
                            borderRadius: R.card, padding: S[6] }}>
            <header style={{ display: "flex", flexDirection: "column", gap: S[2] }}>
              <h1 style={{ margin: 0, fontSize: T.xl, fontWeight: 650, letterSpacing: "-.01em",
                           lineHeight: 1.25, overflowWrap: "anywhere" }}>
                {brief.headline}
              </h1>
              {brief.impact && (
                <div style={{ fontSize: T.md, color: C.text2, lineHeight: 1.5 }}>{brief.impact}</div>
              )}
            </header>

            {brief.why && brief.why !== brief.headline && (
              <section>
                <Label>Why</Label>
                <p style={{ margin: `${S[2]} 0 0`, fontSize: T.base, color: C.text2, lineHeight: 1.6 }}>
                  {brief.why}
                </p>
              </section>
            )}

            {brief.quotes.length > 0 && (
              <section style={{ display: "flex", flexDirection: "column", gap: S[3] }}>
                <Label>What users said</Label>
                {brief.quotes.map((q, i) => (
                  <blockquote key={i} style={{ margin: 0, padding: `${S[2]} ${S[4]}`,
                                               borderLeft: `2px solid ${C.accent}`, background: C.card2,
                                               borderRadius: R.sm }}>
                    <div style={{ fontSize: T.base, color: C.text, lineHeight: 1.55, overflowWrap: "anywhere" }}>
                      “{q.text}”
                    </div>
                    {q.source && (
                      <div style={{ marginTop: S[1], fontFamily: mono, fontSize: T.xs, color: C.dim }}>
                        {q.source}
                      </div>
                    )}
                  </blockquote>
                ))}
              </section>
            )}

            {brief.actions.length > 0 && (
              <section>
                <Label>Recommended actions</Label>
                <ol style={{ margin: `${S[2]} 0 0`, paddingLeft: S[5], display: "flex",
                             flexDirection: "column", gap: S[2] }}>
                  {brief.actions.map((a, i) => (
                    <li key={i} style={{ fontSize: T.base, color: C.text, lineHeight: 1.5 }}>
                      {a.action}
                      {(a.impact || a.effort) && (
                        <span style={{ marginLeft: S[2], fontFamily: mono, fontSize: T.xs, color: C.dim }}>
                          {[a.impact && `${a.impact} impact`, a.effort && `${a.effort} effort`]
                            .filter(Boolean).join(" · ")}
                        </span>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </article>
        )}

        {brief?.shared_at && (
          <div style={{ fontSize: T.xs, color: C.faint, fontFamily: mono }}>
            Shared {when(brief.shared_at)}
          </div>
        )}
      </div>
    </main>
  );
}
