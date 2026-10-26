import { ReactNode, useEffect, useRef, useState } from "react";
import { OnboardStatus, Snapshot, SourcePreview, api, isAdmin, isGuest } from "../api";
import { plural } from "../format";
import { useDialog } from "../hooks";
import { C } from "../theme";
import { Button, Dot } from "../ui";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import { ReleaseChart, SerifHeadline, StatTile } from "../components/casefile";
import {
  backfillProgressView,
  emptyBackfillMessage,
  progressActivityLabel,
  sourceProgressLabel,
  sourceErrorView,
} from "../onboardingProgress";
import "./landing/public.css";

interface Props {
  onDone: () => void; // land on Today for the new product
  /** Hand off to All problems → spikes, where triage actually happens. */
  onReviewSignals: () => void;
  onManageSources: () => void;
  canSkip: boolean;
  onCancel: () => void;
  /** Dismiss the overlay. Always available — nobody is trapped here. */
  onClose: () => void;
  /** Called the moment the product exists, so it becomes the active scope
   *  immediately. Without this, anything started from this wizard was filed
   *  against the PREVIOUS product. */
  onProductCreated: (id: number, name: string) => void;
}

/**
 * First run / Add a product: three short questions (store link → GitHub →
 * anything else), then plain progress while it backfills, ending on Today.
 *
 * A LAYER over the running app, not a screen that replaces it. It used to own
 * the whole window with the nav hidden, so landing here with nothing to add —
 * an empty workspace, or no permission to create a product — was a dead end.
 * Now the app stays visible behind it and it can always be closed.
 */
export function Onboarding({
  onDone, onReviewSignals, onManageSources, canSkip, onCancel, onClose, onProductCreated,
}: Props) {
  const [phase, setPhase] = useState<"form" | "running">("form");
  const [product, setProduct] = useState("");
  // Collection continues in the background, so the dialog remains dismissible
  // and focus-contained in both phases.
  const ref = useDialog(onClose);

  const body = !isAdmin()
    ? <NoAccess guest={isGuest()} />
    : phase === "form" ? (
      <OnboardForm
        onStarted={(p, id) => {
          // Switch scope FIRST: everything started from here belongs to the
          // product being onboarded, not the one that happened to be active.
          onProductCreated(id, p);
          setProduct(p);
          setPhase("running");
        }}
        canSkip={canSkip}
        onCancel={onCancel}
      />
    ) : (
      <Backfilling product={product} onDone={onDone}
        onReviewSignals={onReviewSignals} onManageSources={onManageSources} />
    );

  return (
    <>
      <div
        className="el-onboarding-scrim"
        onClick={phase === "form" ? onClose : undefined}
        aria-hidden="true"
        style={{ position: "fixed", inset: 0, background: "var(--el-scrim)", zIndex: 40 }}
      />
      <div
        className="el-onboarding-dialog"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label="Add a product"
        style={{
          position: "fixed", inset: 0, zIndex: 41, overflow: "auto",
          display: "flex", alignItems: "flex-start", justifyContent: "center",
          padding: 24,
        }}
      >
        <div className={`el-onboarding-dossier pub-dossier${phase === "running" ? " is-running" : ""}`} style={{
          position: "relative", width: "100%", margin: "auto",
          // Scroll inside the viewport so a short screen never pushes the
          // primary action off the bottom.
          maxHeight: "calc(100dvh - 48px)", overflowY: "auto", boxShadow: "var(--el-e4)",
        }}>
          {/* The X. Onboarding is never mandatory. */}
          <button onClick={onClose} aria-label="Close" className="pub-close"
            style={{ position: "absolute", top: 16, right: 16 }}>
            <Icon name="close" size={16} />
          </button>
          {body}
        </div>
      </div>
    </>
  );
}

/** Logo, a quiet label, then the serif headline — every phase opens the same way. */
function Heading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="pub-run__head">
      <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--el-muted)", fontSize: 14 }}>
        <Logo size={24} decorative /> Add a product
      </div>
      <SerifHeadline as="h1" size="card" style={{ paddingRight: 40 }}>{title}</SerifHeadline>
      {children && <p className="pub-run__lede">{children}</p>}
    </div>
  );
}

/**
 * The screen a non-admin gets instead of the questions.
 *
 * Reached two ways: a guest exploring a demo whose workspace has no products
 * yet, or a signed-in viewer/reviewer who clicked "Add a product". Both used
 * to land on a form that 403s on submit — a dead end with no back button.
 */
function NoAccess({ guest }: { guest: boolean }) {
  return (
    <div className="pub-run">
      <Heading title={guest ? "Connecting an app needs an account" : "Only an admin can add a product"}>
        {guest
          ? "Reading 90 days of reviews and issues costs money to run, so it is kept to the workspace owner. Close this and carry on exploring — everything else in the demo is open to you."
          : "Ask an admin to connect it. Once they have, everything here works for you too."}
      </Heading>
    </div>
  );
}

// ── the three questions ─────────────────────────────────────────────────

const GITHUB_OPTIONS = [
  { source: "github", label: "Issues & releases" },
  { source: "github_discussions", label: "Discussions" },
  { source: "github_activity", label: "PRs & commits" },
] as const;

const SOURCE_LABELS: Record<string, string> = {
  play_store: "Play Store",
  github: "GitHub Issues & releases",
  github_discussions: "GitHub Discussions",
  github_activity: "GitHub PRs & commits",
  app_store: "App Store",
  chrome_web_store: "Chrome Web Store",
  hacker_news: "Hacker News",
  stack_overflow: "Stack Overflow",
};

type AdditionalSources = {
  app_store: string;
  chrome_web_store: string;
  hacker_news: string;
  stack_overflow: string;
};

/**
 * A pasted Play Store link becomes its package ("…/details?id=com.lumo.app"
 * → "com.lumo.app"); anything else is passed through trimmed, and the server
 * still validates it.
 */
function packageFrom(raw: string): string {
  const value = raw.trim();
  if (!/play\.google\.com|[?&]id=/i.test(value)) return value;
  try {
    const url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
    return url.searchParams.get("id")?.trim() || value;
  } catch {
    return value.match(/[?&]id=([^&#\s]+)/)?.[1] ?? value;
  }
}

const QUESTIONS = ["Where do people review your app?", "Is the code on GitHub?", "Anywhere else people talk about it?"];

function OnboardForm({ onStarted, canSkip, onCancel }: { onStarted: (product: string, productId: number) => void; canSkip: boolean; onCancel: () => void }) {
  const [step, setStep] = useState(0);
  const [store, setStore] = useState("");
  const [repo, setRepo] = useState("");
  const [name, setName] = useState("");
  const [githubMode, setGithubMode] = useState<"all" | "specific">("all");
  const [githubSources, setGithubSources] = useState<string[]>(["github"]);
  const [additional, setAdditional] = useState<AdditionalSources>({
    app_store: "", chrome_web_store: "", hacker_news: "", stack_overflow: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const admin = isAdmin();
  const pkg = packageFrom(store);
  // Look before you leap: the listing / repo behind what was typed, so a typo
  // shows up as "that's not my app" before a 90-day backfill starts.
  const pkgPreview = useSourcePreview("play_store", pkg, admin);
  const repoPreview = useSourcePreview("github", repo, admin);
  const storeTitle = pkgPreview.data?.ok ? pkgPreview.data.title : undefined;
  const titleRef = useRef<HTMLHeadingElement>(null);

  const selectedGithub = (): string[] => githubMode === "all"
    ? GITHUB_OPTIONS.map((option) => option.source)
    : githubSources;

  /** Each step's own check; null means it may move on. */
  const problem = (at: number): string | null => {
    if (at === 0 && !pkg) return "Paste your app's Play Store link, or its package name.";
    if (at === 1 && repo.trim() && selectedGithub().length === 0) return "Select at least one GitHub data type.";
    return null;
  };

  const go = (to: number) => {
    setError(null);
    setStep(to);
    // Move focus to the new question so keyboard and screen-reader users
    // hear it, rather than staying on a button that just changed meaning.
    requestAnimationFrame(() => titleRef.current?.focus());
  };

  const next = () => {
    const p = problem(step);
    if (p) { setError(p); return; }
    if (step < 2) go(step + 1); else void submit();
  };

  const submit = async () => {
    if (!admin) return;
    for (const at of [0, 1]) {
      const p = problem(at);
      if (p) { setStep(at); setError(p); return; }
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.onboard({
        play_store: pkg,
        github: repo.trim() || undefined,
        github_sources: repo.trim() ? selectedGithub() : undefined,
        product: name.trim() || storeTitle || undefined,
        app_store: additional.app_store.trim() || undefined,
        chrome_web_store: additional.chrome_web_store.trim() || undefined,
        hacker_news: additional.hacker_news.trim() || undefined,
        stack_overflow: additional.stack_overflow.trim() || undefined,
      });
      onStarted(r.product, r.product_id);
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  };

  const onEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") { e.preventDefault(); next(); }
  };

  return (
    <div className="pub-run">
      <Heading title="Point EchoLens at your app">
        Three quick questions. Only the first one is required.
      </Heading>

      <div className="pub-progress" aria-label={`Question ${step + 1} of 3`}>
        <span className="pub-progress__bars" aria-hidden>
          {[0, 1, 2].map((i) => <span key={i} className={i <= step ? "is-done" : ""} />)}
        </span>
        <span>STEP {step + 1} OF 3</span>
      </div>

      <form className="pub-question" noValidate onSubmit={(e) => { e.preventDefault(); next(); }}>
        <h2 ref={titleRef} tabIndex={-1} className="pub-question__title" style={{ outline: "none" }}>
          {QUESTIONS[step]}
        </h2>

        {step === 0 && (
          <Field label="Play Store link or package"
            hint="Paste the link to your app's store page, or the package name after id= (for example com.spotify.music).">
            <input autoFocus className="pub-input" value={store} onChange={(e) => { setStore(e.target.value); setError(null); }}
              onKeyDown={onEnter} placeholder="https://play.google.com/store/apps/details?id=…"
              aria-invalid={!!error} spellCheck={false} autoCapitalize="off" />
            {pkg && pkg !== store.trim() && (
              <span className="pub-field__hint">Package: <code>{pkg}</code></span>
            )}
            <PreviewLine state={pkgPreview} />
          </Field>
        )}

        {step === 1 && (
          <>
            <Field label="GitHub repo (optional)"
              hint="Issues and releases let EchoLens connect complaints to the code that shipped.">
              <input autoFocus className="pub-input" value={repo} onChange={(e) => { setRepo(e.target.value); setError(null); }}
                onKeyDown={onEnter} placeholder="e.g. signalapp/Signal-Android" spellCheck={false} autoCapitalize="off" />
              <PreviewLine state={repoPreview} />
            </Field>
            {repo.trim() && (
              <fieldset style={{ margin: 0, padding: 0, border: 0, display: "flex", flexDirection: "column", gap: 10 }}>
                <legend className="pub-field__label" style={{ padding: 0, marginBottom: 10 }}>What to read from GitHub</legend>
                <div className="pub-choices">
                  <Choice checked={githubMode === "all"} type="radio" name="github-mode" label="Everything" onChange={() => setGithubMode("all")} />
                  <Choice checked={githubMode === "specific"} type="radio" name="github-mode" label="Let me choose" onChange={() => setGithubMode("specific")} />
                </div>
                {githubMode === "specific" && (
                  <div className="pub-choices">
                    {GITHUB_OPTIONS.map((option) => (
                      <Choice key={option.source} checked={githubSources.includes(option.source)} type="checkbox" label={option.label}
                        onChange={() => setGithubSources((current) => current.includes(option.source)
                          ? current.filter((source) => source !== option.source)
                          : [...current, option.source])} />
                    ))}
                  </div>
                )}
                <span className="pub-field__hint">Everything means issues, releases, pull requests and commits. Discussions are added too once a GitHub token is set up on the server.</span>
              </fieldset>
            )}
          </>
        )}

        {step === 2 && (
          <>
            <div className="pub-grid2">
              <Field label="App Store link or ID" hint="Optional">
                <input className="pub-input" value={additional.app_store} placeholder="apps.apple.com/… or 324684580" onKeyDown={onEnter}
                  onChange={(e) => setAdditional((current) => ({ ...current, app_store: e.target.value }))} />
              </Field>
              <Field label="Hacker News search" hint="Optional">
                <input className="pub-input" value={additional.hacker_news} placeholder="your product or company name" onKeyDown={onEnter}
                  onChange={(e) => setAdditional((current) => ({ ...current, hacker_news: e.target.value }))} />
              </Field>
              <Field label="Stack Overflow tag" hint="Optional">
                <input className="pub-input" value={additional.stack_overflow} placeholder="e.g. your-product" onKeyDown={onEnter}
                  onChange={(e) => setAdditional((current) => ({ ...current, stack_overflow: e.target.value }))} />
              </Field>
            </div>
            <span className="pub-field__hint">Chrome Web Store reviews aren't available right now — Google stopped sharing them. You can import them as a CSV from Sources later.</span>
            <Field label="What should we call it?"
              hint={storeTitle ? `Optional — defaults to the store listing's name, ${storeTitle}.` : "Optional — defaults to the package name."}>
              <input className="pub-input" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={onEnter}
                placeholder={storeTitle ?? "e.g. Spotify"} />
            </Field>
          </>
        )}

        {error && <div role="alert" className="pub-error">{error}</div>}

        <div className="pub-run__nav">
          <Button type="submit" variant="primary" className="pub-btn" loading={busy} disabled={!admin}
            title={admin ? undefined : "You need admin access to connect a product."}>
            {step === 2 ? (busy ? "Starting…" : "Start reading reviews")
              : step === 1 && !repo.trim() ? "Skip — no GitHub" : "Next"}
          </Button>
          {step > 0 && (
            <Button type="button" variant="ghost" className="pub-btn" onClick={() => go(step - 1)} disabled={busy}>
              Back
            </Button>
          )}
          {canSkip && step === 0 && (
            <Button type="button" variant="quiet" onClick={onCancel}>Cancel</Button>
          )}
          {!admin && <span className="pub-field__hint">You need admin access to connect a product.</span>}
        </div>
      </form>
    </div>
  );
}

function Choice({ checked, type, name, label, onChange }: {
  checked: boolean; type: "radio" | "checkbox"; name?: string; label: string; onChange: () => void;
}) {
  return (
    <label>
      <input type={type} name={name} checked={checked} onChange={onChange} />
      {label}
    </label>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  // A real <label> wrapping the control, so every input announces its name.
  return (
    <label className="pub-field">
      <span className="pub-field__label">{label}</span>
      {hint && <span className="pub-field__hint">{hint}</span>}
      {children}
    </label>
  );
}

// ── instant preview ─────────────────────────────────────────────────────

/** 190M, not 190,123,456 — a preview is a glance. */
const compact = (n: number) => new Intl.NumberFormat("en", { notation: "compact" }).format(n);

const PKG_SHAPE = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/;
const REPO_SHAPE = /^(https?:\/\/)?(www\.)?(github\.com\/)?[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(\.git)?\/?$/;

interface PreviewState { data: SourcePreview | null; loading: boolean }

/**
 * Debounced look-up of one onboarding input. Only asks once the value has the
 * right SHAPE — a half-typed "com.sp" would otherwise flash "not found" on
 * every keystroke — and drops answers that arrive after the input changed.
 * Purely advisory: a failure leaves the form exactly as usable as before.
 */
function useSourcePreview(kind: "play_store" | "github", raw: string, enabled: boolean): PreviewState {
  const [state, setState] = useState<PreviewState>({ data: null, loading: false });
  const seq = useRef(0);
  useEffect(() => {
    const value = raw.trim();
    const id = ++seq.current;
    const shaped = kind === "play_store" ? PKG_SHAPE.test(value) : REPO_SHAPE.test(value);
    if (!enabled || !shaped) {
      setState({ data: null, loading: false });
      return;
    }
    setState((prev) => ({ data: prev.data, loading: true }));
    const timer = window.setTimeout(() => {
      api.onboardPreview({ [kind]: value })
        .then((r) => { if (seq.current === id) setState({ data: r[kind] ?? null, loading: false }); })
        .catch(() => { if (seq.current === id) setState({ data: null, loading: false }); });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [kind, raw, enabled]);
  return state;
}

function PreviewLine({ state }: { state: PreviewState }) {
  const { data, loading } = state;
  if (!data && !loading) return null;
  let tone = "";
  let icon = "search";
  let text: ReactNode = "Looking it up…";
  if (data && !loading) {
    if (data.ok) {
      tone = " is-ok";
      icon = "check";
      const facts = data.source === "play_store"
        ? [data.developer, data.ratings != null ? `${compact(data.ratings)} ratings` : null,
           data.score != null ? `${data.score.toFixed(1)}★` : null]
        : [data.open_issues != null ? `${compact(data.open_issues)} open ${plural(data.open_issues, "issue")}` : null,
           data.stars != null ? `${compact(data.stars)} stars` : null];
      text = (
        <>
          <b>{data.title}</b>
          {facts.filter(Boolean).length > 0 && <> · {facts.filter(Boolean).join(" · ")}</>}
        </>
      );
    } else {
      // Not found is worth a warning; slow or unreachable is only a note.
      const warn = data.kind === "not_found" || data.kind === "invalid";
      tone = warn ? " is-warn" : "";
      icon = warn ? "warning" : "info";
      text = data.reason ?? "Couldn't check this one — you can still continue.";
    }
  }
  return (
    <span role="status" aria-live="polite" className={`pub-preview${tone}`}>
      <Icon name={icon} size={13} style={{ flex: "none" }} />
      <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>{text}</span>
    </span>
  );
}

// ── live backfill + snapshot ────────────────────────────────────────────

function Backfilling({ product, onDone, onReviewSignals, onManageSources }: {
  product: string; onDone: () => void; onReviewSignals: () => void;
  onManageSources: () => void;
}) {
  const [status, setStatus] = useState<OnboardStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const [pollingStopped, setPollingStopped] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [lastProgressAt, setLastProgressAt] = useState(() => Date.now());
  const openedAt = useRef(Date.now());
  const progressSignature = status?.sources
    .map((source) => `${source.source}:${source.status}:${source.items_last_run}:${source.last_error || ""}`)
    .join("|") ?? "";

  useEffect(() => {
    let alive = true;
    let timer: number | null = null;
    let failures = 0;
    setPollingStopped(false);
    const schedule = () => {
      if (alive) timer = window.setTimeout(poll, 1000);
    };
    const poll = async () => {
      if (!alive) return;
      try {
        const s = await api.onboardStatus(product);
        if (!alive) return;
        setStatus(s);
        setErr(null);
        failures = 0;
        if (s.backfilling) schedule();
      } catch (e) {
        if (!alive) return;
        setErr(String(e).replace("Error: ", ""));
        // Stop after repeated failures instead of polling a dead backend
        // forever behind a frozen snapshot that still looks like progress.
        failures += 1;
        if (failures >= 5) {
          setPollingStopped(true);
        } else {
          schedule();
        }
      }
    };
    poll();
    return () => {
      alive = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [product, pollAttempt]);

  useEffect(() => {
    if (!status?.backfilling) return;
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(clock);
  }, [status?.backfilling]);

  useEffect(() => {
    if (!progressSignature) return;
    const changedAt = Date.now();
    setLastProgressAt(changedAt);
    setNow(changedAt);
  }, [progressSignature]);

  const retrySource = async (source: string, identifier: string) => {
    const key = `${source}:${identifier}`;
    setRetrying(key);
    setErr(null);
    try {
      const result = await api.collectorsRetry(source, identifier);
      if (result.error) throw new Error(result.error);
      setPollAttempt((attempt) => attempt + 1);
    } catch (e) {
      setErr(String(e).replace("Error: ", ""));
    } finally {
      setRetrying(null);
    }
  };

  // Still said "Reading Bitwarden's reviews" on the finished screen.
  const heading = (done = false) => done
    ? <Heading title={`${product} is ready`}>
        Every source has been read once. EchoLens keeps reading them on its own from now on.
      </Heading>
    : <Heading title={`Reading ${product}'s reviews`}>
        EchoLens is checking each source and learning what normal looks like. You can go to Today while it runs.
      </Heading>;

  if (err && !status) return (
    <div className="pub-run">
      {heading()}
      <div role="alert" className="pub-error">We couldn't check setup progress — {err}</div>
      <div className="pub-run__nav">
        <Button variant="primary" className="pub-btn" onClick={() => setPollAttempt((attempt) => attempt + 1)}>Check again</Button>
        <Button variant="ghost" className="pub-btn" onClick={onDone}>Continue to Today</Button>
      </div>
    </div>
  );
  if (!status) return (
    <div className="pub-run">
      {heading()}
      <div className="el-onboarding-connecting" role="status">
        <span className="el-onboarding-spinner" aria-hidden="true" />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600 }}>Checking your sources…</div>
          <div className="pub-field__hint">This normally takes only a moment.</div>
        </div>
        <Button variant="ghost" className="pub-btn" onClick={onDone}>Continue to Today</Button>
      </div>
    </div>
  );

  const snap = status.snapshot;
  const anomalies = status.anomalies.filter((a) => a.status === "pending");
  const hasReviews = snap.reviews > 0;
  // Completion is about the collectors, not specifically Play Store reviews.
  // A valid app can have no public reviews while GitHub still supplies hundreds
  // of useful items. Tying the CTA to `reviews > 0` trapped those products on
  // this screen forever even after every source had finished successfully.
  const ready = !status.backfilling;
  const githubItems = status.sources
    .filter((source) => source.source.startsWith("github"))
    .reduce((total, source) => total + source.items_last_run, 0);
  // Pending anomalies are what All problems will offer to triage as spikes.
  // `top_themes` are NOT spikes — they are the most frequent phrases, by word
  // count, and double-count paraphrases — so they are never added in here.
  const found = anomalies.length;
  const progress = status.progress ?? {
    checked_sources: status.sources.filter((source) => source.status === "healthy" || source.status === "error").length,
    failed_sources: status.sources.filter((source) => source.status === "error").length,
    timed_out_sources: 0,
    total_sources: status.sources.length,
    expected_seconds: 120,
    timeout_seconds: 180,
    started_at: new Date(openedAt.current).toISOString(),
  };
  const progressView = backfillProgressView(progress, now);
  const activityLabel = progressActivityLabel(
    progress,
    Math.max(0, Math.floor((now - lastProgressAt) / 1000)),
  );
  const activeElapsed = progressView.elapsedLabel.replace(" elapsed", "");
  // The one plain sentence: "Read 1,078 items from 7 sources — found 3 spikes".
  // It counts everything collected; "65 reviews" alone sat next to "300 items
  // pulled" with nothing saying the 65 were only the last 90 days.
  const collected = status.sources.reduce((total, source) => total + (source.items_last_run || 0), 0);
  const okSources = status.sources.filter((source) => source.status === "healthy").length;
  const itemsLine = `${collected.toLocaleString()} ${plural(collected, "item")} from ${okSources} ${plural(okSources, "source")}`;
  const spikesLine = found > 0 ? `found ${found} ${plural(found, "spike")}` : "no spikes yet";
  const plain = ready ? `Read ${itemsLine} — ${spikesLine}.` : `Reading… ${itemsLine} so far, ${spikesLine}`;
  const recentLine = `${snap.reviews.toLocaleString()} store ${plural(snap.reviews, "review")} are from the last 90 days — EchoLens watches those for spikes.`;

  return (
    <div className="pub-run">
      {heading(ready)}
      <div className="el-onboarding-backfill" style={{ display: "flex", flexDirection: "column" }}>
        <div className="pub-reading" style={{ borderTop: 0, paddingTop: 0 }}>
          <div className="pub-reading__line" aria-live="polite">{plain}</div>
          {ready && hasReviews && <div className="pub-reading__sub">{recentLine}</div>}
          {ready && found === 0 && hasReviews && (
            <div className="pub-reading__sub">
              That's normal on day one: EchoLens needs a few days of history before it can tell a surge from noise.
            </div>
          )}
        </div>

        {err && (
          <div role="alert" className="pub-error">
            We couldn't refresh setup progress — {err}. What you see below may be out of date.
            <span className="el-onboarding-alert__actions">
              <Button size="sm" variant="ghost" onClick={() => setPollAttempt((attempt) => attempt + 1)}>
                {pollingStopped ? "Check again" : "Refresh now"}
              </Button>
              <Button size="sm" variant="quiet" onClick={onDone}>Continue to Today</Button>
            </span>
          </div>
        )}

        <section className={`el-onboarding-progress${status.backfilling ? " is-active" : ""}`}
          aria-label="Backfill progress">
          <div className="el-sr-only" role="status" aria-live="polite">
            {ready
              ? progress.failed_sources > 0
                ? `Setup finished with ${progress.failed_sources} ${plural(progress.failed_sources, "source")} needing attention.`
                : "Product setup finished."
              : progressView.countLabel}
          </div>
          <div className="el-onboarding-progress__summary">
            <div>
              <div style={{ fontSize: 17, fontWeight: 600 }}>
                {ready
                  ? progress.failed_sources > 0
                    ? `Finished, with ${progress.failed_sources} ${plural(progress.failed_sources, "source")} needing attention`
                    : "Your product is ready"
                  : "Checking your sources"}
              </div>
              <div className="pub-field__hint" style={{ marginTop: 4 }}>
                {ready
                  ? progress.failed_sources > 0
                    ? "Working sources and what they collected are ready to use."
                    : "Every connected source has been checked."
                  : "Collection keeps going safely if you leave this screen."}
              </div>
            </div>
            <div className="el-onboarding-progress__measure">
              <div className="el-onboarding-progress__count">{progressView.countLabel}</div>
              <div className="el-onboarding-progress__timing">
                {progressView.elapsedLabel && <span>{progressView.elapsedLabel}</span>}
                <span>{progressView.expectedLabel}</span>
              </div>
            </div>
            {status.backfilling && (
              <div className="el-onboarding-progress__primary-action">
                <Button variant="primary" className="pub-btn" onClick={onDone}>Continue to Today</Button>
                <span>Collection keeps running</span>
              </div>
            )}
          </div>
          <div className="el-onboarding-progress__track" role="progressbar"
            aria-label={progressView.countLabel} aria-valuemin={0}
            aria-valuemax={progress.total_sources} aria-valuenow={progress.checked_sources}>
            <span style={{ width: `${progressView.percent}%` }} />
          </div>
          <div className="el-onboarding-progress__activity">
            <span className="el-onboarding-live-dot" aria-hidden="true" />
            <span>{activityLabel}</span>
            {status.backfilling && <span className="el-onboarding-progress__cutoff">
              {progressView.cutoffLabel}
            </span>}
          </div>
          <details className="el-onboarding-progress__details">
            <summary>How live collection works</summary>
            <p>Sources run independently. Each one updates as soon as it responds;
              one slow or failed connection does not hold up the others.</p>
          </details>
        </section>

        {/* source health */}
        <div className="el-onboarding-source-list" aria-label="Connected source activity">
          {status.sources.map((s) => {
            const color = s.status === "error" ? C.stampRed : s.status === "healthy" ? C.green : C.pencil;
            const label = sourceProgressLabel(s);
            const retryKey = `${s.source}:${s.identifier}`;
            const running = s.status !== "error" && s.status !== "healthy";
            return (
              <article key={s.source + s.identifier}
                className={`el-onboarding-source el-onboarding-source--${s.status}`}>
                <div className="el-onboarding-source__identity">
                  <div className="el-onboarding-source__header">
                    <Dot color={color} pulse={status.backfilling && running} />
                    <span style={{ fontSize: 15, fontWeight: 600 }}>
                      {SOURCE_LABELS[s.source] || s.source}
                    </span>
                  </div>
                  <div className="el-onboarding-source__identifier" title={s.identifier}>
                    {s.identifier}
                  </div>
                </div>
                <div className="el-onboarding-source__result">
                  <span style={{ fontSize: 14, color: s.status === "error" ? "var(--el-ink)" : "var(--el-body)" }}>
                    {running ? `Fetching and processing · ${activeElapsed}` : label}
                  </span>
                  {s.status === "error" && (() => {
                    const view = sourceErrorView(s.last_error);
                    return (
                      <>
                        <span className="el-onboarding-source__guidance">{view.guidance}</span>
                        {s.last_error && (
                          <details className="el-onboarding-source__technical">
                            <summary>Technical details</summary>
                            <code>{s.last_error}</code>
                          </details>
                        )}
                        <div className="el-onboarding-source__actions">
                          {view.canRetry && (
                            <Button size="sm" variant="ghost" onClick={() => retrySource(s.source, s.identifier)}
                              loading={retrying === retryKey}>
                              {retrying === retryKey ? "Retrying…" : "Retry source"}
                            </Button>
                          )}
                          <Button size="sm" variant="quiet" onClick={onManageSources}>
                            Review connection
                          </Button>
                        </div>
                      </>
                    );
                  })()}
                </div>
              </article>
            );
          })}
        </div>

        {hasReviews ? (
          <SnapshotView snap={snap} />
        ) : (
          <div className="pub-notice">
            {emptyBackfillMessage({
              backfilling: status.backfilling,
              failedSources: progress.failed_sources,
              githubItems,
            })}
          </div>
        )}

        {/* What people mention most — a summary and a handoff, not a third
            place to triage. Triage happens in one place: All problems. */}
        {ready && snap.top_themes.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <SerifHeadline as="h2" size="section">What people mention most</SerifHeadline>
            <div className="pub-themes">
              {snap.top_themes.slice(0, 6).map((t) => (
                <span key={t.label}>{t.label}<small>{t.count}</small></span>
              ))}
            </div>
            {found > 0 && (
              <div className="pub-field__hint">
                {found === 1 ? "The spike is" : `The ${found} spikes are`} waiting in All problems. Pick what's worth
                investigating — nothing is lost by not choosing now.
              </div>
            )}
          </div>
        )}

        {/* data-quality disclosures */}
        {(snap.data_quality.note || snap.data_quality.non_english_note) && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {snap.data_quality.note && <Notice text={snap.data_quality.note} />}
            {snap.data_quality.non_english_note && <Notice text={snap.data_quality.non_english_note} />}
          </div>
        )}

        {ready && (
          <div className="pub-run__nav">
            <Button variant="primary" className="pub-btn" onClick={onDone}>Go to Today</Button>
            {found > 0 && (
              <Button variant="ghost" className="pub-btn" onClick={onReviewSignals}>
                Review {found} {plural(found, "spike")}
              </Button>
            )}
            {/* No spike to review, but the reviews are worth exploring. */}
            {found === 0 && snap.top_themes.length > 0 && (
              <Button variant="ghost" className="pub-btn" onClick={onReviewSignals}>
                Explore the reviews
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function SnapshotView({ snap }: { snap: Snapshot }) {
  const delta = snap.rating_delta;
  // A change is only shown when both weeks had enough reviews to compare.
  const ratingCaption = delta != null
    ? `rating this week, ${delta >= 0 ? "up" : "down"} ${Math.abs(delta).toFixed(2)} on last week`
    : snap.rating_basis === "window"
      ? "average over the last 90 days — too few reviews a week to compare weeks"
      : "average rating this week";
  const weekly = snap.weekly.map((w) => ({ date: w.week_start, value: w.count }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="pub-snapshot">
        <StatTile value={snap.reviews.toLocaleString()} caption="reviews from the last 90 days" />
        <StatTile value={snap.rating_now != null ? `${snap.rating_now.toFixed(1)}★` : "—"} caption={ratingCaption} />
        <StatTile value={String(snap.avg_per_day)} caption="reviews a day, on average" />
        <StatTile value={snap.negatives.toLocaleString()}
          caption={`1–2★ reviews, ${snap.reviews ? Math.round((snap.negatives / snap.reviews) * 100) : 0}% of all`} />
      </div>
      {weekly.length > 0 && (
        <ReleaseChart points={weekly} height={84} unit="reviews" ariaLabel="Reviews per week, last 12 weeks"
          caption="Reviews per week, last 12 weeks" />
      )}
    </div>
  );
}

function Notice({ text }: { text: string }) {
  return (
    <div className="pub-notice">
      <Icon name="info" size={14} style={{ flex: "none", marginTop: 3 }} />
      {text}
    </div>
  );
}
