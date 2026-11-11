import { useEffect, useState } from "react";
import { ThemeCandidate, api, canReview } from "../../api";
import { plural } from "../../format";
import { reportAs } from "../../monitor";
import { Button } from "../../ui";
import { HighlightQuote, SerifHeadline } from "../../components/casefile";

/**
 * Day-one value. The ready screen used to end on "no spikes yet — come back in
 * a few days": spike detection needs history, so a brand-new product had
 * nothing to show for hundreds of reviews just read. Recurring complaints need
 * no history, only the reviews, so the first read can already say what hurts
 * most — with a real quote — and offer to look into it.
 *
 * Same data and the same action as All problems → "Look into it", so starting
 * here or there files the identical case.
 */
export function FirstFindings({ productId, onOpenProblems, onFallback }: {
  /** The new product. Passed explicitly: while the wizard is open the app's
   *  active product is still the one behind it. */
  productId: number;
  onOpenProblems: () => void;
  /** Rendered when there is nothing recurring to show (or it failed to load). */
  onFallback: () => React.ReactNode;
}) {
  const [items, setItems] = useState<ThemeCandidate[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [started, setStarted] = useState<Record<string, string>>({});
  const [startError, setStartError] = useState<string | null>(null);
  const reviewer = canReview();

  useEffect(() => {
    let alive = true;
    api.feedCandidates(false, productId)
      .then((r) => { if (alive) setItems(r.candidates.slice(0, 3)); })
      .catch((e) => {
        reportAs("ready screen: recurring complaints")(e);
        if (alive) setFailed(true);
      });
    return () => { alive = false; };
  }, [productId]);

  const lookInto = async (c: ThemeCandidate) => {
    setBusy(c.slug);
    setStartError(null);
    try {
      const r = await api.queueThemes([c.slug], { [c.slug]: c.statement }, "quick", productId);
      // The server's summary is a count ("1 queued"); say what happens instead.
      setStarted((s) => ({ ...s, [c.slug]: r.already.length
        ? "Already being looked at."
        : "Queued. EchoLens will look into it and show the answer on All problems." }));
    } catch (e) {
      setStartError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(null);
    }
  };

  if (failed || (items && items.length === 0)) return <>{onFallback()}</>;

  return (
    <section className="ob-findings" aria-label="Recurring complaints" aria-busy={items == null}>
      <SerifHeadline as="h2" size="section">Worth a look today</SerifHeadline>
      <p className="pub-reading__sub" style={{ margin: 0 }}>
        What people complain about most in the reviews just read. No history needed.
      </p>
      {items == null ? (
        <div className="ob-findings__list" role="status">
          {[0, 1, 2].map((i) => <div key={i} className="ob-finding ob-finding--loading" />)}
          <span className="el-sr-only">Finding the most common complaints…</span>
        </div>
      ) : (
        <ol className="ob-findings__list">
          {items.map((c) => {
            const done = started[c.slug];
            const quote = c.verbatims[0];
            return (
              <li key={c.slug} className="ob-finding">
                <div className="ob-finding__head">
                  <b>{c.statement}</b>
                  <span className="ob-finding__count">{c.count} {plural(c.count, "review")}</span>
                </div>
                {quote && <div className="ob-finding__quote"><HighlightQuote>“{quote}”</HighlightQuote></div>}
                <div className="ob-finding__action">
                  {c.existing ? (
                    <span className="pub-field__hint">Already being looked at.</span>
                  ) : done ? (
                    <span className="pub-field__hint" role="status">{done}</span>
                  ) : reviewer ? (
                    <Button size="sm" variant="ghost" loading={busy === c.slug} disabled={busy != null}
                      onClick={() => void lookInto(c)}>
                      {busy === c.slug ? "Starting…" : "Look into this"}
                    </Button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {startError && <div role="alert" className="pub-error">Couldn't start that: {startError}</div>}
      {Object.keys(started).length > 0 && (
        <Button variant="quiet" size="sm" onClick={onOpenProblems}>See it on All problems →</Button>
      )}
    </section>
  );
}
