import { useEffect, useState } from "react";
import { ShareBrief, api } from "../api";
import { when } from "../format";
import { applyTheme, resolveTheme } from "../themeMode";
import { Exhibit, NumberedSteps, SerifHeadline, Stamp, stampFor } from "../components/casefile";
import { LogoLockup } from "../components/Logo";
import "./landing/public.css";

const LETTERS = "ABCDEFGH";
const TILTS = [-0.5, 0.4, -0.3, 0.6, -0.6, 0.3, -0.4, 0.5];

/**
 * The public, read-only view of one shared problem (#/share/<token>), laid out
 * like a small case file: verdict stamp, serif title, what happened, exhibits.
 *
 * Rendered without login, outside the app shell: no navigation, no product
 * switcher, no links into cases. It shows exactly what the server's public
 * endpoint returns for the token — the brief the sharer chose to share — and
 * nothing that could lead a stranger to other data or other products.
 */
export function SharedBrief({ token }: { token: string }) {
  const [brief, setBrief] = useState<ShareBrief | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState("A");

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

  // A stamp only when the server said how well this is proven; an older
  // server without the verdict gets none rather than a guessed one.
  const verdict = brief?.verdict;
  const stamp = verdict ? stampFor({ support_level: verdict.support_level, needs_review: verdict.needs_review,
                                     fix: verdict.fix }) : null;
  const sure = verdict && verdict.confidence > 0 ? Math.round(verdict.confidence * 100) : null;

  return (
    <main className="pub-share">
      <div className="pub-share__inner">
        <header className="pub-share__top">
          <LogoLockup size={28} />
          <span className="pub-share__meta">
            Shared problem{brief?.product ? ` · ${brief.product}` : ""} · read-only
          </span>
        </header>

        {!brief && !error && <div role="status" className="pub-share__state"><p>Opening the shared problem…</p></div>}

        {error && (
          <div role="alert" className="pub-share__state">
            <SerifHeadline as="h1" size="section">This link doesn't open a problem.</SerifHeadline>
            <p>It may have been turned off, or copied only in part. Ask whoever shared it to send a new link.</p>
            <p className="pub-share__sure" title={error}>The server said: {error.replace(/\.$/, "")}.</p>
          </div>
        )}

        {brief && (
          <article className="pub-share__grid" aria-labelledby="pub-share-title">
            <div className="pub-share__story">
              <div className="pub-share__titlerow">
                <SerifHeadline as="h1" size="case" id="pub-share-title" style={{ overflowWrap: "anywhere" }}>
                  {brief.headline}
                </SerifHeadline>
                {stamp && stamp !== "live" && <Stamp variant={stamp} rotation={-6} />}
              </div>
              {brief.impact && <p className="pub-share__impact">{brief.impact}</p>}
              {sure != null && (
                <div className="pub-share__sure"
                  title={stamp === "hunch" ? "Hunch: one kind of source, or a reviewer flagged it — capped below confirmed." : undefined}>
                  We're {sure}% sure{stamp === "hunch" ? " — a hunch, not yet confirmed by two kinds of source" : ""}.
                </div>
              )}

              {brief.why && brief.why !== brief.headline && (
                <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <SerifHeadline as="h2" size="section">What happened</SerifHeadline>
                  <p className="pub-share__prose">{brief.why}</p>
                </section>
              )}

              {brief.actions.length > 0 && (
                <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <SerifHeadline as="h2" size="section">What to do next</SerifHeadline>
                  <NumberedSteps label="Recommended actions" steps={brief.actions.map((a, i) => ({
                    id: String(i),
                    text: (
                      <>
                        {a.action}
                        {(a.impact || a.effort) && (
                          <span style={{ display: "block", marginTop: 4, fontSize: 13, opacity: 0.75 }}>
                            {[a.impact && `${a.impact} impact`, a.effort && `${a.effort} effort`].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </>
                    ),
                  }))} />
                </section>
              )}
            </div>

            <aside className="pub-share__rail" aria-label="Exhibits">
              <SerifHeadline as="h2" size="section">Exhibits</SerifHeadline>
              {brief.quotes.length === 0 ? (
                <p style={{ margin: 0, color: "var(--el-muted)", fontSize: 15, lineHeight: 1.5 }}>
                  No quotes were shared with this problem.
                </p>
              ) : brief.quotes.slice(0, LETTERS.length).map((q, i) => (
                <Exhibit key={i} letter={LETTERS[i]} kind={`Exhibit ${LETTERS[i]}`} date={q.source || "source not named"}
                  quote={`“${q.text}”`} tilt={TILTS[i]} selected={selected === LETTERS[i]} onSelect={setSelected} />
              ))}
            </aside>
          </article>
        )}

        {brief && (
          <footer className="pub-share__foot">
            {brief.shared_at ? `Shared ${when(brief.shared_at)}. ` : ""}
            This page shows only what was shared, and stops working if the link is turned off.
          </footer>
        )}
      </div>
    </main>
  );
}
