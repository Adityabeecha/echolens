import { useEffect, useMemo, useRef, useState } from "react";
import { DemoRefreshedError, Evidence, Investigation, api, errorMessage } from "../api";
import { CaseTab, currentLocation, formatRoute, parseRoute } from "../nav";
import { Centered, ErrorState } from "../ui";
import { Button } from "../ui";
import { CitationLetter, LiveDot, PillTabs, ReasonRow, SerifHeadline, Stamp } from "../components/casefile";
import { EvidenceSheet } from "../components/EvidenceSheet";
import { useAsync, useDialog, useMediaQuery } from "../hooks";
import { DecisionChip, ExtendCard } from "./case/CaseActions";
import { DiscussionTab } from "./case/DiscussionTab";
import { HistoryTab } from "./case/HistoryTab";
import { TraceTab } from "./case/TraceTab";
import { EvidenceDetail } from "./case/Inspector";
import { ExhibitsRail } from "./case/ExhibitsRail";
import { MoreTab } from "./case/MoreTab";
import { FixShippedDialog, IssuePreview, NextStepsBlock, VerdictActions, blockedReason } from "./case/NextSteps";
import {
  Exhibit, afterUpdate, buildExhibits, isBlockedDraft, missingFor, notProven, reasonsFor, verdictOf,
} from "./case/caseFile";
import "./case/case.css";

interface Props {
  caseId: number;
  tab: CaseTab;
  productName: string | null;
  onTab: (tab: CaseTab) => void;
  onBack: () => void;
  backLabel: string;
  onOpenCase: (id: number, status?: string) => void;
  onReviewed: () => void;
  onGoCalibration: () => void;
  onGoPatterns: () => void;
}

/** Below the fold: the pill tabs, and the URL tab each one keeps alive. */
type Lower = "steps" | "discussion" | "history" | "more";
const LOWER_TO_ROUTE: Record<Lower, CaseTab> = { steps: "trace", discussion: "discussion", history: "history", more: "engineering" };
const ROUTE_TO_LOWER: Partial<Record<CaseTab, Lower>> = { trace: "steps", discussion: "discussion", history: "history", engineering: "more" };

/** Wide enough for the story and the exhibits rail side by side. */
const RAIL_QUERY = "(min-width: 1024px)";

type Lit = { kind: "ex"; id: string } | { kind: "reason"; id: string } | null;

/**
 * One problem, as a case file (design/approved/case.html): the verdict, what
 * happened with lettered proof, why we're sure, what to do next, and the
 * exhibits beside it. Letters, reasons and exhibits light each other up.
 * Everything else — every step, discussion, history, and the rest — sits in
 * quiet tabs below, each still reachable by its old URL (/trace, /history…).
 */
export function CaseDetail({
  caseId, tab, productName, onTab, onBack, backLabel, onOpenCase, onReviewed, onGoCalibration, onGoPatterns,
}: Props) {
  const [inv, setInv] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [demoRefreshed, setDemoRefreshed] = useState(false);
  const [pollGeneration, setPollGeneration] = useState(0);
  useEffect(() => {
    if (inv?.id !== caseId || !inv.merged_into_id) return;
    const route = parseRoute(currentLocation());
    if (!route || route.screen !== "case") return;
    window.location.replace(formatRoute({ ...route, id: inv.merged_into_id }));
  }, [inv?.id, inv?.merged_into_id, caseId]);

  // Monotonic sequence guard shared by load() and the poller: a slow response
  // can never land after a newer one and overwrite it.
  const loadSeq = useRef(0);
  const load = () => {
    const mine = ++loadSeq.current;
    return api.investigation(caseId)
      .then((d) => { if (mine === loadSeq.current) { setInv(d); setError(null); } })
      .catch((e) => { if (mine === loadSeq.current) { setError(errorMessage(e)); setDemoRefreshed(e instanceof DemoRefreshedError); } });
  };
  const retry = () => { setError(null); setPollGeneration((n) => n + 1); };

  // Poll while the case is LIVE (running, or queued and about to start); stop
  // after repeated failures instead of hammering a down backend. One request at
  // a time: the next is scheduled only after this one settles.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const settled = (d: Investigation) => d.status !== "running" && d.case_status !== "queued";
    const MAX_FAILURES = 4;
    let failures = 0;
    let finished = false;
    const stop = () => { finished = true; if (timer) { clearTimeout(timer); timer = null; } };
    const schedule = () => { if (alive && !finished) timer = setTimeout(() => { void tick(); }, 1500); };
    const tick = async () => {
      const mine = ++loadSeq.current;
      try {
        const d = await api.investigation(caseId);
        if (!alive || mine !== loadSeq.current) return;
        failures = 0;
        setInv(d); setError(null); setDemoRefreshed(false);
        if (settled(d)) stop();
      } catch (e) {
        if (!alive || mine !== loadSeq.current) return;
        setError(errorMessage(e)); setDemoRefreshed(e instanceof DemoRefreshedError);
        if (++failures >= MAX_FAILURES) stop();
      } finally {
        if (alive && !finished) schedule();
      }
    };
    void tick();
    return () => { alive = false; stop(); };
  }, [caseId, pollGeneration]);

  // The citation map follows the finding: refetch when it, or a struck exhibit, changes.
  const proofKey = inv ? `${inv.finding?.id ?? 0}:${inv.evidence.length}:${inv.evidence.filter((e) => e.rejected).length}:${inv.status}` : "";
  const cites = useAsync(() => (inv?.finding ? api.citations(caseId) : Promise.resolve(null)), [caseId, proofKey]);
  const cfg = useAsync(() => api.guardsConfig(), []);
  const [retrying, setRetrying] = useState(false);
  const tryAgain = async () => {
    if (!inv) return;
    setRetrying(true);
    try {
      const r = await api.startInvestigation({ description: inv.title });
      onOpenCase?.(r.investigation_id);
    } catch (e) { setError(errorMessage(e)); }
    finally { setRetrying(false); }
  };
  // The same per-problem numbers Today shows. The page used the WHOLE app's
  // rating fall (−0.89★) where Today said this problem costs −0.23★.
  const measured = useAsync(() => api.overview(caseId).then((o) => o.focus ?? null), [caseId, proofKey]);
  const wide = useMediaQuery(RAIL_QUERY);
  const [lit, setLit] = useState<Lit>(null);
  const [issueOpen, setIssueOpen] = useState(false);
  const [shipOpen, setShipOpen] = useState(false);
  const [detail, setDetail] = useState<Evidence | null>(null);
  const [railSheet, setRailSheet] = useState(false);
  const lower: Lower = ROUTE_TO_LOWER[tab] ?? "steps";
  const lowerRef = useRef<HTMLElement | null>(null);
  // The sticky exhibits rail sits just under the sticky header. The header
  // wraps to two lines on narrower screens (and when it explains a disabled
  // button), so a fixed offset let the rail's top slide underneath it.
  const screenRef = useRef<HTMLDivElement | null>(null);
  const barRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const bar = barRef.current, screen = screenRef.current;
    if (!bar || !screen || typeof ResizeObserver === "undefined") return;
    const set = () => screen.style.setProperty("--cv-bar-h", `${Math.ceil(bar.getBoundingClientRect().height)}px`);
    set();
    const ro = new ResizeObserver(set);
    ro.observe(bar);
    return () => ro.disconnect();
  });
  // A deep link to a lower tab (or /evidence) scrolls there once the case is in.
  const jumped = useRef(false);
  useEffect(() => {
    if (jumped.current || !inv) return;
    jumped.current = true;
    if (tab in ROUTE_TO_LOWER && (inv.finding || tab !== "trace")) {
      requestAnimationFrame(() => lowerRef.current?.scrollIntoView({ block: "start" }));
    } else if (tab === "evidence") {
      if (wide) requestAnimationFrame(() => document.querySelector(".cv-rail")?.scrollIntoView({ block: "start" }));
      else setRailSheet(true);
    }
  }, [inv, tab, wide]);

  const built = useMemo(() => inv ? buildExhibits(inv, cites.data ?? null) : { exhibits: [], sentences: [] },
    [inv, cites.data]);
  const { exhibits, sentences } = built;

  if (error && (!inv || demoRefreshed)) {
    return (
      <div style={{ padding: 24 }}>
        <ErrorState title={`Couldn't load problem #${caseId}`} detail={error} onRetry={retry} />
        {demoRefreshed && <Button variant="ghost" onClick={() => {
          const route = parseRoute(currentLocation());
          window.location.assign(formatRoute({ screen: "cases", productId: route?.productId }));
        }}>Go to all problems</Button>}
      </div>
    );
  }
  if (!inv) return <Centered>Opening problem #{caseId}…</Centered>;
  if (inv.merged_into_id) return <Centered>Opening problem #{inv.merged_into_id}…</Centered>;

  const f = inv.finding;
  const verdict = verdictOf(inv);
  const hunch = verdict === "hunch";
  const blockedDraft = isBlockedDraft(inv);
  const reasons = reasonsFor(inv, exhibits);
  const missing = hunch ? missingFor(inv, exhibits, cfg.data?.two_source.min_items ?? 2) : [];
  const unproven = notProven(inv);
  const current: Lit = lit ?? (reasons[0] ? { kind: "reason", id: reasons[0].id } : null);
  const litLetters = new Set(current?.kind === "ex" ? [current.id]
    : current?.kind === "reason" ? reasons.find((r) => r.id === current.id)?.letters ?? [] : []);
  const order = afterUpdate(inv, exhibits);
  const impact = f?.impact;
  const didntRun = !f && ["failed", "insufficient_evidence"].includes(inv.status)
    && (inv.data_notes?.[inv.data_notes.length - 1] ?? "").startsWith("Investigation could not run");
  const drag = measured.data?.rating_drag ?? null;
  const sharePct = measured.data?.one_star_share?.pct ?? null;
  const sure = f ? Math.round(f.confidence * 100) : null;
  const blocked = blockedReason(inv);

  const pickLetter = (letter: string) => {
    setLit({ kind: "ex", id: letter });
    if (!wide) setRailSheet(true);
  };
  const openDetails = (x: Exhibit) => setDetail(x.evidence);
  const openEvidence = (e: Evidence) => {
    const x = exhibits.find((y) => y.id === e.id);
    if (x) pickLetter(x.letter); else setDetail(e);
  };
  const onMerged = (id: number) => { onReviewed(); onOpenCase(id); };

  const rail = (inline: boolean) => (
    <ExhibitsRail inv={inv} exhibits={exhibits} lit={litLetters} onPick={(l) => setLit({ kind: "ex", id: l })}
      onDetails={openDetails} onReload={load} className={inline ? "is-inline" : ""} heading={inline} />
  );

  return (
    <div className="cv-screen" ref={screenRef}>
      <header className="cv-bar" ref={barRef}>
        <div className="cv-bar__inner">
          <button type="button" className="cv-back" onClick={onBack}>← {backLabel}</button>
          <div className="cv-meta">
            Problem #{inv.id}{productName ? ` · ${productName}` : ""}
            {sure != null && !blockedDraft && (
              <> · <button type="button" onClick={onGoCalibration}
                title="How well EchoLens's stated certainty has matched your verdicts">we're <b>{sure}% sure</b></button></>
            )}
          </div>
          <DecisionChip decision={inv.product_decision} />
          <span className="cv-bar__spacer" />
          {/* Nothing to send or ship when the run never produced an answer. */}
          {!didntRun && <>
            <Button variant="primary" disabled={!!blocked} title={blocked ?? undefined} onClick={() => setIssueOpen(true)}>
              Send to GitHub</Button>
            <Button variant="ghost" disabled={!!blocked} title={blocked ?? undefined} onClick={() => setShipOpen(true)}>Fix shipped</Button>
          </>}
          {blocked && f && <span className="cv-why-disabled">{blocked}</span>}
        </div>
      </header>

      {error && (
        <div className="cv-banner" role="alert" style={{ maxWidth: 1136, margin: "12px auto 0" }}>
          Couldn't refresh this problem — {error}{" "}
          <button type="button" className="cv-link" onClick={retry}>Try again</button>
        </div>
      )}

      <main className="cv-main">
        <div className="cv-col">
          {blockedDraft && <div className="cv-eyebrow">Drafted, not proven — kept apart from the answer</div>}
          <div className="cv-titlerow">
            <SerifHeadline as="h1" size="case">{inv.title}</SerifHeadline>
            {didntRun ? <span className="cv-didnt-run">Didn't finish</span>
              : verdict === "live" ? <LiveDot label={inv.case_status === "queued" ? "WAITING" : "LIVE"} />
              : <Stamp variant={verdict} rotation={-6}
                  title={hunch ? "Hunch: not proven by two independent kinds of source yet" : undefined} />}
          </div>

          {f?.needs_review && f.status !== "challenged" && (
            <div className="cv-banner"><b>Needs another look.</b> {f.needs_review.reason}</div>
          )}
          {inv.data_notes?.length > 0 && (
            <div className="cv-banner">{didntRun
              ? <div>{inv.case_why || "This investigation didn't finish."}</div>
              : inv.data_notes.map((n, i) => <div key={i}>{n}</div>)}</div>
          )}

          {didntRun ? (
            <section className="cv-section">
              <h2 className="cv-label">What happened</h2>
              <p className="cv-story">
                This investigation stopped before it could weigh any evidence, so there is no answer to judge
                and nothing here counts as proof. Running it again usually works once the reason above is sorted out.
              </p>
              <Button variant="primary" loading={retrying} onClick={() => void tryAgain()}>Try again</Button>
            </section>
          ) : !f ? (
            <section className="cv-section">
              <h2 className="cv-label">What's happening</h2>
              <p className="cv-story">
                {inv.status === "running" || inv.case_status === "queued"
                  ? "EchoLens is looking into this now. Every step it takes appears below as it happens."
                  : `${inv.case_why || "This ended without an answer."} Every step it took is below.`}
              </p>
              <ExtendCard inv={inv} onReload={load} />
            </section>
          ) : (
            <>
              <section className="cv-section" aria-labelledby="cv-what">
                <h2 id="cv-what" className="cv-label">What happened <span>· tap a letter to see the exhibit</span></h2>
                <p className="cv-story">
                  {sentences.map((s, i) => {
                    const on = s.letters.some((l) => litLetters.has(l));
                    return (
                      <span key={i}>
                        {i > 0 && " "}
                        <span className={`cv-sentence${on ? " is-lit" : ""}`}>{s.text}</span>
                        {s.letters.map((l) => (
                          <CitationLetter key={l} letter={l} selected={current?.kind === "ex" && current.id === l}
                            onSelect={pickLetter} />
                        ))}
                      </span>
                    );
                  })}
                </p>
                {((drag && !hunch) || sharePct || order) ? (
                  <div className="cv-chips">
                    {/* A rating loss is only pinned on a proven cause, never on a hunch. */}
                    {drag != null && drag > 0 && !hunch && (
                      <span title="This problem's pull on the rating: last 7 days against the 28 before"><b className="is-bad">−{drag.toFixed(2)}★</b> estimated rating loss</span>
                    )}
                    {sharePct != null && sharePct > 0 && (
                      <span title="One-star reviews in the last 30 days that describe this problem"><b>{Math.round(sharePct)}%</b> of one-star reviews in 30 days</span>
                    )}
                    {order && (
                      <span title={`Release ${order.release.letter} on ${order.release.date}; first complaint ${order.first.letter} on ${order.first.date}`}>
                        started <b>{order.days === 0 ? "the same day as" : `${order.days} ${order.days === 1 ? "day" : "days"} after`}</b> the update</span>
                    )}
                  </div>
                ) : null}
              </section>

              {hunch && (
                <section className="cv-missing" aria-labelledby="cv-missing">
                  <h2 id="cv-missing">What's missing</h2>
                  <p>{blockedDraft
                    ? "EchoLens drafted a cause but couldn't point to proof for all of it, so it isn't shown as the answer. To confirm it, it needs:"
                    : "This is a hunch, not a confirmed problem. To confirm it, EchoLens needs:"}</p>
                  {missing.length > 0 ? <ul>{missing.map((m) => <li key={m}>{m}</li>)}</ul>
                    : <p>{inv.case_why}</p>}
                  <ExtendCard inv={inv} onReload={load} />
                </section>
              )}

              {unproven.length > 0 && (
                <section className="cv-unproven" aria-labelledby="cv-unproven">
                  <h2 id="cv-unproven" className="cv-label">Not proven yet <span>· no exhibit backs these, so they are not part of the answer</span></h2>
                  {unproven.map((u, i) => <p key={i}>{u}</p>)}
                </section>
              )}

              {reasons.length > 0 && (
                <section className="cv-section" aria-labelledby="cv-why">
                  <h2 id="cv-why" className="cv-label">
                    {hunch ? "What we have so far" : <>Why we're sure <span>· our honesty checks</span></>}
                  </h2>
                  <div className="cv-reasons">
                    {reasons.map((r) => (
                      <ReasonRow key={r.id} letters={r.letters}
                        selected={current?.kind === "reason" && current.id === r.id}
                        onSelect={() => setLit({ kind: "reason", id: r.id })}>
                        <span title={r.tip}>{r.text}</span>
                      </ReasonRow>
                    ))}
                  </div>
                </section>
              )}

              <section className="cv-section" aria-labelledby="cv-next">
                <h2 id="cv-next" className="cv-label">What to do next</h2>
                <VerdictActions inv={inv} onReload={load} onReviewed={onReviewed} onOpenCase={onOpenCase} />
                <NextStepsBlock inv={inv} onSend={() => setIssueOpen(true)} onShipped={() => setShipOpen(true)} />
              </section>
            </>
          )}

          {!wide && exhibits.length > 0 && (
            <Button variant="ghost" className="cv-exhibits-btn" onClick={() => setRailSheet(true)}>
              See the {exhibits.length} {exhibits.length === 1 ? "exhibit" : "exhibits"}</Button>
          )}
        </div>
        {wide && rail(true)}
      </main>

      <section ref={lowerRef} className="cv-more" aria-label="More about this problem" style={{ scrollMarginTop: 80 }}>
        {/* The raw trace (tool calls, token budget) is for the curious, not the
            answer: it stays folded until asked for, a deep link opens it, and a
            case that is running or has no answer yet shows it straight away. */}
        {!(tab in ROUTE_TO_LOWER || inv.status === "running" || !inv.finding) ? (
          <button type="button" className="cv-more__open" onClick={() => onTab("trace")}>
            <span>
              <span className="cv-more__title">How EchoLens worked this out</span>
              <span className="cv-more__sub">Every step it took, the discussion and the history</span>
            </span>
            <span aria-hidden="true">›</span>
          </button>
        ) : <>
        <PillTabs label="More about this problem" panelId="cv-lower" value={lower}
          tabs={[{ id: "steps", label: inv.status === "running" ? "Every step · live" : "Every step" },
                 { id: "discussion", label: "Discussion" },
                 { id: "history", label: `History${inv.history?.length ? ` ${inv.history.length}` : ""}` },
                 { id: "more", label: "More" }]}
          onChange={(t) => onTab(LOWER_TO_ROUTE[t])} />
        <div id="cv-lower" role="tabpanel" aria-label={lower} className="cv-more__panel">
          {lower === "steps" && <div className="cv-trace-frame"><TraceTab inv={inv} onOpenEvidence={openEvidence} onReload={load} /></div>}
          {lower === "discussion" && <div style={{ display: "flex", minHeight: 320 }}><DiscussionTab caseId={caseId} /></div>}
          {lower === "history" && <div style={{ display: "flex" }}><HistoryTab inv={inv} onOpenCase={onOpenCase} /></div>}
          {lower === "more" && <MoreTab inv={inv} onReload={load} onGoPatterns={onGoPatterns}
            onOpenEvidence={openEvidence} onMerged={onMerged} />}
        </div>
        </>}
      </section>

      {issueOpen && f && <IssuePreview inv={inv} onClose={() => setIssueOpen(false)} onFiled={load} />}
      {shipOpen && f && <FixShippedDialog inv={inv} onClose={() => setShipOpen(false)} onSaved={load} />}
      {railSheet && !wide && <RailSheet onClose={() => setRailSheet(false)} count={exhibits.length}>{rail(false)}</RailSheet>}
      <EvidenceSheet evidence={detail} onClose={() => setDetail(null)}>
        {detail && <EvidenceDetail evidence={detail} inv={inv} onReload={load} />}
      </EvidenceSheet>
    </div>
  );
}

/** Phones: the exhibits rail as a bottom sheet. */
function RailSheet({ onClose, count, children }: { onClose: () => void; count: number; children: React.ReactNode }) {
  const ref = useDialog(onClose);
  return (
    <>
      <div className="cv-scrim" onClick={onClose} aria-hidden="true" />
      <div ref={ref} role="dialog" aria-modal="true" aria-label="Exhibits" className="cv-sheet">
        <div className="cv-rail__head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <SerifHeadline as="h2" size="section">Exhibits</SerifHeadline>
          <span style={{ fontSize: 13, color: "var(--el-muted)" }}>{count} {count === 1 ? "piece" : "pieces"}</span>
          <button type="button" className="cv-close" onClick={onClose} aria-label="Close exhibits">✕</button>
        </div>
        {children}
      </div>
    </>
  );
}
