import { CSSProperties, ReactNode, useEffect, useState } from "react";
import { AlertSettings, CostsSummary, api } from "../../api";
import { withToast } from "../../components/Toast";
import { Dropdown, SerifHeadline } from "../../components/casefile";
import "../../components/casefile/casefile.css";
import { money } from "../../format";
import { useAsync } from "../../hooks";
import { Button, Centered, ErrorState } from "../../ui";

// Settings sections that read like the rest of the app: a serif answer first,
// then the one panel that changes it. Admin-only writes say why when disabled.

const pctOf = (a: number, b: number) => (b > 0 ? Math.min(100, (a / b) * 100) : 0);

/** Settings → Costs: this month against the budget, per problem, per product. */
export function CostsSection({ data, children }: { data: CostsSummary; children?: ReactNode }) {
  const over = data.month_to_date > data.budget;
  const rows = [...(data.by_product ?? [])].sort((a, b) => b.month_to_date - a.month_to_date);
  const top = Math.max(0.0001, ...rows.map((r) => r.month_to_date));
  return (
    <div className="ps-sections">
      {/* The budget is per product; the breakdown below is every product. Said
          outright, since the two side by side read as one number disagreeing. */}
      <SerifHeadline as="h1" size="page">{data.product ? `${data.product}: ` : ""}{money(data.month_to_date)} of {money(data.budget)} this month.</SerifHeadline>
      <div className="ps-panel">
        <div className="ps-row" style={{ justifyContent: "space-between" }}>
          <span>
            {data.per_problem != null
              ? <>About <b>{money(data.per_problem)}</b> per problem looked into ({data.investigations_this_month} this month)</>
              : "No problem has been looked into this month yet."}
          </span>
          <span className="ps-muted">{over ? `${money(data.month_to_date - data.budget)} over budget`
            : `${money(data.budget - data.month_to_date)} left`}</span>
        </div>
        <div className={`ps-meter${over ? " is-over" : ""}`} role="meter" aria-label="Spent this month"
          aria-valuemin={0} aria-valuemax={data.budget} aria-valuenow={data.month_to_date}>
          <span style={{ width: `${pctOf(data.month_to_date, data.budget)}%` }} />
        </div>
        <span className="ps-muted">Each problem stops at its own spending cap (in Limits), so one runaway case can't use up the month.</span>
      </div>
      {rows.length > 1 && (
        <section className="ps-section" aria-labelledby="ps-by-product">
          <h2 id="ps-by-product">Every product, this month</h2>
          <span className="ps-muted">Each product has its own monthly budget; the line above is {data.product || "this product"} only.</span>
          <div className="ps-breakdown">
            {rows.map((r) => (
              <div key={r.product_id}>
                <span>{r.product} <span className="ps-muted">· {r.investigations} {r.investigations === 1 ? "problem" : "problems"}</span></span>
                <div className="ps-meter" aria-hidden><span style={{ width: `${pctOf(r.month_to_date, top)}%` }} /></div>
                <span>{money(r.month_to_date)}</span>
              </div>
            ))}
          </div>
        </section>
      )}
      {children}
    </div>
  );
}

const Z_STEPS = [1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3];
function sensitivityWords(z: number): string {
  if (z <= 1) return "Showing every spike EchoLens finds.";
  if (z < 2) return "Hiding the weakest spikes.";
  if (z < 3) return "Showing medium and strong spikes only.";
  return "Showing only the strongest spikes.";
}

/** Settings → Sensitivity: how strong a spike must be to show up. */
export function SensitivitySection({ data, admin, why, onSaved }: {
  data: CostsSummary; admin: boolean; why: string; onSaved: () => void;
}) {
  const saved = data.limits.detector_min_z ?? 1;
  const [z, setZ] = useState(saved);
  const [busy, setBusy] = useState(false);
  useEffect(() => setZ(saved), [saved]);
  const save = async () => {
    setBusy(true);
    const ok = await withToast(() => api.setLimits({ detector_min_z: z }), {
      success: `Saved — ${sensitivityWords(z).toLowerCase()} New scans use it.`, failure: "Couldn't save the sensitivity",
    });
    setBusy(false);
    if (ok) onSaved();
  };
  return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">{sensitivityWords(saved)}</SerifHeadline>
      <div className="ps-panel">
        <div className="ps-slider">
          <label htmlFor="ps-sensitivity" className="ps-h2" style={{ fontSize: 22 }}>How strong must a spike be?</label>
          <input id="ps-sensitivity" type="range" min={1} max={3} step={0.25} value={z} disabled={!admin}
            onChange={(e) => setZ(Number(e.target.value))} list="ps-z-steps"
            aria-valuetext={`${sensitivityWords(z)} Strength ${z.toFixed(2)}`}
            title={`Strength ${z.toFixed(2)}: how many standard deviations above its usual level a spike must be (the detector's z-score). The default is 1.00.`} />
          <datalist id="ps-z-steps">{Z_STEPS.map((v) => <option key={v} value={v} />)}</datalist>
          <div className="ps-slider__ends"><span>← More, weaker spikes</span><span>Fewer, stronger spikes →</span></div>
          <span className="ps-muted">{sensitivityWords(z)} {z === 1 ? "(default)" : ""} <span title="The detector's z-score">· strength {z.toFixed(2)}</span></span>
        </div>
        <span className="ps-muted">GitHub issue bursts and “a few people say it” watches are counted differently and always show.
          Changing this never touches problems already found.</span>
        <div className="ps-row">
          <Button variant="primary" loading={busy} disabled={!admin || z === saved} title={admin ? undefined : why}
            onClick={save}>Save sensitivity</Button>
          {z !== 1 && admin && <Button variant="quiet" onClick={() => setZ(1)}>Back to the default</Button>}
          {!admin && <span className="ps-muted">{why}</span>}
        </div>
      </div>
    </div>
  );
}

function CheckStamp({ children, color, dashed, rotation }: {
  children: ReactNode; color: string; dashed?: boolean; rotation: number;
}) {
  // A stamp with its own words (the shared Stamp prints only verdicts): the
  // same cf-stamp look, as on the landing page's honesty checks.
  return <span className="cf-stamp is-compact" style={{ color, borderStyle: dashed ? "dashed" : undefined,
    "--stamp-rotation": `${rotation}deg` } as CSSProperties}>{children}</span>;
}

/** Settings → Honesty checks: read-only, from GET /guards/config. */
export function HonestySection() {
  const cfg = useAsync(() => api.guardsConfig(), []);
  if (cfg.loading && !cfg.data) return <Centered>Reading the checks…</Centered>;
  if (cfg.error || !cfg.data) return <ErrorState title="Couldn't read the honesty checks" onRetry={cfg.reload} />;
  const c = cfg.data;
  const cap = Math.round(c.single_source_cap * 100);
  const tech = (key: string) => c.guards.find((g) => g.key === key)?.label;
  const checks = [
    { stamp: <CheckStamp color="var(--el-ink)" rotation={-4}>EVERY CLAIM CITED</CheckStamp>, tip: tech("citation"),
      on: c.claim_grounding, text: "A sentence without proof is taken out of the answer and shown separately as a hunch." },
    { stamp: <CheckStamp color="var(--el-amber)" dashed rotation={3}>TWO WITNESSES</CheckStamp>,
      tip: `${tech("two_source")} · ${tech("single_source_cap")}`, on: true,
      text: `One kind of source is only a hunch, capped at ${cap}% sure. Confirming needs ${c.two_source.min_items} pieces of proof from ${c.two_source.min_sources} independent kinds.` },
    { stamp: <CheckStamp color="var(--el-pencil-blue)" rotation={-2}>CAUSE CAME FIRST</CheckStamp>, tip: tech("temporal_order"),
      on: c.temporal_order, text: "A release can't be blamed for complaints that started before it shipped." },
    { stamp: <CheckStamp color="var(--el-stamp-red)" rotation={4}>TRIED TO DISPROVE IT</CheckStamp>, tip: "Counter-evidence pass",
      on: true, text: "Before confirming, EchoLens looks for evidence against its own answer." },
  ];
  return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">Four checks every answer must pass.</SerifHeadline>
      <p className="ps-note">They are written in code, not in a prompt, and can't be loosened here — or anywhere in settings.
        When the proof isn't there, EchoLens says “not sure”.</p>
      <div className="ps-checks">
        {checks.map((x) => (
          <div key={x.tip} className="ps-check" title={x.tip}>
            {x.stamp}
            <div>{x.text}</div>
            {!x.on && <span className="ps-muted">Turned off on this server.</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

const SEVERITY_CHOICES: { v: number; label: string }[] = [
  { v: 0.3, label: "Most problems" },
  { v: 0.5, label: "Medium and serious problems" },
  { v: 0.7, label: "Only serious problems" },
  { v: 0.9, label: "Only the most serious" },
];

/** Settings → Integrations: Slack and GitHub alerts, from the existing settings. */
export function IntegrationsSection({ admin, why, trackers }: { admin: boolean; why: string; trackers: ReactNode }) {
  const res = useAsync(() => api.alertSettings(), []);
  const [busy, setBusy] = useState<string | null>(null);
  if (res.loading && !res.data) return <Centered>Reading your alerts…</Centered>;
  if (res.error || !res.data) return <ErrorState title="Couldn't read your alert settings" onRetry={res.reload} />;
  const a: AlertSettings = res.data;
  const save = async (key: string, body: Parameters<typeof api.setAlertSettings>[0]) => {
    setBusy(key);
    await withToast(() => api.setAlertSettings(body), { success: "Saved.", failure: "Couldn't save that setting" });
    setBusy(null);
    res.reload();
  };
  const choices = SEVERITY_CHOICES.some((c) => c.v === a.alert_instant_min_severity) ? SEVERITY_CHOICES
    : [...SEVERITY_CHOICES, { v: a.alert_instant_min_severity, label: `Custom (${a.alert_instant_min_severity})` }];
  const answer = !a.alerts_enabled ? "Alerts are off."
    : a.slack_connected ? "Alerts are on, and go to Slack." : "Alerts are on — Slack isn't connected yet.";
  return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">{answer}</SerifHeadline>
      <section className="ps-section" aria-labelledby="ps-alerts">
        <h2 id="ps-alerts">Alerts</h2>
        <div>
          <label className="ps-toggle">
            <input type="checkbox" checked={a.alerts_enabled} disabled={!admin || !!busy}
              onChange={(e) => save("on", { alerts_enabled: e.target.checked })} />
            <div>
              <strong>Send alerts when a new problem is found</strong>
              <span title="ALERTS_ENABLED · SLACK_WEBHOOK_URL">
                {a.slack_connected ? "Slack is connected." : "Slack isn't connected — the server needs a Slack webhook."}
                {" "}Less serious problems wait for the daily digest.</span>
            </div>
          </label>
          <div className="ps-toggle">
            <span style={{ width: 20 }} aria-hidden />
            <label className="ps-field" style={{ flex: 1 }}>
              <span>How serious before an instant alert?</span>
              <Dropdown block label="How serious before an instant alert?" value={String(a.alert_instant_min_severity)}
                disabled={!admin || !!busy || !a.alerts_enabled} title="ALERT_INSTANT_MIN_SEVERITY (0–1)"
                options={choices.map((c) => ({ value: String(c.v), label: c.label }))}
                onChange={(v) => save("sev", { alert_instant_min_severity: Number(v) })} />
            </label>
          </div>
          <label className="ps-toggle">
            <input type="checkbox" checked={a.auto_create_issue_on_approve} disabled={!admin || !!busy}
              onChange={(e) => save("auto", { auto_create_issue_on_approve: e.target.checked })} />
            <div>
              <strong>Open a GitHub issue when a problem is approved from Slack</strong>
              <span title="AUTO_CREATE_ISSUE_ON_APPROVE · GITHUB_TOKEN">
                {a.github_connected ? "GitHub is connected." : "GitHub isn't connected — the server needs a GitHub token."}
              </span>
            </div>
          </label>
        </div>
        {!admin && <span className="ps-muted">{why}</span>}
      </section>
      <section className="ps-section" aria-labelledby="ps-trackers">
        <h2 id="ps-trackers">Where problems can be sent</h2>
        {trackers}
      </section>
    </div>
  );
}
