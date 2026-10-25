import { useEffect, useState } from "react";
import { ProductRow, api, getRole, isAdmin, isGuest } from "../api";
import { withToast } from "../components/Toast";
import { PillTabs, SerifHeadline } from "../components/casefile";
import { money } from "../format";
import { useAsync } from "../hooks";
import { SettingsSection } from "../nav";
import { Button, Centered, ErrorState } from "../ui";
import { Calibration } from "./Calibration";
import { Costs } from "./Costs";
import { CostsSection, HonestySection, IntegrationsSection, SensitivitySection } from "./settings/Sections";
import "./settings/ps.css";

interface Props {
  product: ProductRow | null;
  onGoCosts: () => void;
  onGoSources: () => void;
  onAddProduct: () => void;
  onDeleteProduct: (p: ProductRow) => void;
  /** Which section is open; in the URL as ?section= so it can be linked. */
  section?: SettingsSection;
  onSection?: (section: SettingsSection) => void;
  onGoReview?: () => void;
}

const SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "general", label: "Limits & product" },
  { id: "costs", label: "Costs" },
  { id: "sensitivity", label: "Sensitivity" },
  { id: "honesty", label: "Honesty checks" },
  { id: "integrations", label: "Integrations" },
  { id: "calibration", label: "How often it's right" },
];

/**
 * Settings — how EchoLens runs for this product: limits, what it costs, how
 * sensitive spike detection is, the honesty checks (read-only), alerts and
 * trackers, and calibration. Each section opens with its answer in serif.
 */
export function Settings({
  product, onGoCosts, onGoSources, onAddProduct, onDeleteProduct, section = "general", onSection, onGoReview,
}: Props) {
  const guest = isGuest();
  const admin = isAdmin() && !guest;
  const why = guest ? "Sign in with an admin account to change this." : "Only admins can change this.";
  const needsCosts = section === "general" || section === "costs" || section === "sensitivity";
  const costs = useAsync(() => (needsCosts ? api.costsSummary() : Promise.resolve(null)), [needsCosts]);

  const body = () => {
    if (section === "honesty") return <HonestySection />;
    if (section === "integrations") return <IntegrationsSection admin={admin} why={why} trackers={<TrackersPanel />} />;
    if (section === "calibration") {
      return (
        <div className="ps-sections">
          <SerifHeadline as="h1" size="page">How often EchoLens is right when it says it's sure.</SerifHeadline>
          <div style={{ display: "flex", minHeight: 420 }}><Calibration embedded onGoCases={() => onGoReview?.()} /></div>
        </div>
      );
    }
    if (costs.loading && !costs.data) return <Centered>Loading settings…</Centered>;
    if (costs.error || !costs.data) return <ErrorState title="Couldn't load your settings" onRetry={costs.reload} />;
    if (section === "costs") {
      // The per-problem ledger (was the Costs screen; /costs links land here).
      return <CostsSection data={costs.data}><div style={{ display: "flex", minHeight: 360 }}><Costs embedded /></div></CostsSection>;
    }
    if (section === "sensitivity") return <SensitivitySection data={costs.data} admin={admin} why={why} onSaved={costs.reload} />;
    return (
      <GeneralSection limits={costs.data.limits} product={product} spent={costs.data.month_to_date}
        budget={costs.data.budget} admin={admin} why={why} onSaved={costs.reload} onGoCosts={onGoCosts}
        onGoSources={onGoSources} onAddProduct={onAddProduct} onDeleteProduct={onDeleteProduct} />
    );
  };

  return (
    <div className="ps-screen">
      <main className="ps-main">
        <div className="ps-head">
          <div className="ps-head__meta">
            <span>Settings{product ? <> · <b>{product.name}</b></> : null}</span>
            <span className="ps-spacer" />
            <span>{guest ? "Exploring the demo (read-only)" : `Signed in as ${getRole()}`}</span>
          </div>
          <PillTabs label="Settings sections" panelId="ps-settings" value={section}
            tabs={SECTIONS} onChange={(s) => onSection?.(s)} />
        </div>
        <div id="ps-settings" role="tabpanel" aria-label={SECTIONS.find((s) => s.id === section)?.label}>
          {body()}
        </div>
      </main>
    </div>
  );
}

type Limits = { daily_investigations: number; per_case_budget: number; per_case_wall_min: number };

function GeneralSection({ limits, product, spent, budget, admin, why, onSaved, onGoCosts, onGoSources, onAddProduct,
  onDeleteProduct }: {
  limits: Limits; product: ProductRow | null; spent: number; budget: number; admin: boolean; why: string;
  onSaved: () => void; onGoCosts: () => void; onGoSources: () => void; onAddProduct: () => void;
  onDeleteProduct: (p: ProductRow) => void;
}) {
  return (
    <div className="ps-sections">
      <SerifHeadline as="h1" size="page">
        Up to {limits.daily_investigations} problems a day, {money(limits.per_case_budget)} each at most.
      </SerifHeadline>
      <p className="ps-note">{money(spent)} of {money(budget)} spent this month.{" "}
        <button type="button" className="ps-link" onClick={onGoCosts}>See what it went on →</button></p>
      <section className="ps-section" aria-labelledby="ps-limits">
        <h2 id="ps-limits">Limits{admin ? "" : " · read-only"}</h2>
        {!admin && <span className="ps-muted">{why}</span>}
        <LimitsPanel limits={limits} onSaved={onSaved} admin={admin} />
      </section>
      <section className="ps-section" aria-labelledby="ps-product">
        <h2 id="ps-product">This product</h2>
        <div className="ps-card">
          <Field label="Name" value={product?.name ?? "—"} />
          <Field label="Google Play app" value={product?.package_name ?? "not connected"} />
          <Field label="GitHub repo" value={product?.github_repo ?? "not connected"} />
          <div className="ps-row">
            <Button variant="ghost" size="sm" onClick={onGoSources}>Manage sources</Button>
            {admin && <Button variant="ghost" size="sm" onClick={onAddProduct}>Add another product</Button>}
            {product && (
              <Button variant="danger" size="sm" disabled={!admin} title={admin ? undefined : why}
                onClick={() => admin && onDeleteProduct(product)}>Delete {product.name}</Button>
            )}
          </div>
          {!admin && product && <span className="ps-muted">Deleting a product is for admins. {why}</span>}
        </div>
      </section>
    </div>
  );
}

/** Which trackers a problem can be sent to. Set up on the server only. */
function TrackersPanel() {
  const { data, loading, error, reload } = useAsync(() => api.trackers(), []);
  const ENV: Record<string, string> = {
    github: "GITHUB_TOKEN", linear: "LINEAR_API_KEY + LINEAR_TEAM_ID",
    jira: "JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY",
  };
  return (
    <div className="ps-card">
      {loading && !data && <span className="ps-muted">Checking…</span>}
      {error && !data && <span className="ps-muted">Couldn't check. <button type="button" className="ps-link" onClick={reload}>Retry</button></span>}
      {data?.trackers.map((t) => (
        <div key={t.id} className="ps-row" style={{ justifyContent: "space-between" }}>
          <span><i className={`ps-dot ${t.configured ? "is-healthy" : ""}`} aria-hidden
            style={{ display: "inline-block", marginRight: 8, background: t.configured ? undefined : "var(--el-line-strong)" }} />{t.label}</span>
          <span className="ps-muted" title={t.configured ? undefined : `Set ${ENV[t.id]} on the server`}>
            {t.configured ? "Connected — problems can be sent here" : "Not set up on the server"}</span>
        </div>
      ))}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="ps-row" style={{ justifyContent: "space-between" }}>
      <span className="ps-muted">{label}</span>
      <span style={{ fontFamily: "var(--el-mono)", fontSize: 13, overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

function LimitsPanel({ limits, onSaved, admin }: { limits: Limits; onSaved: () => void; admin: boolean }) {
  const [state, setState] = useState(limits);
  useEffect(() => setState(limits), [limits]);
  const adjust = async (key: keyof Limits, delta: number, min: number, max: number) => {
    const before = state;
    const next = Math.min(max, Math.max(min, +(state[key] + delta).toFixed(2)));
    if (next === state[key]) return;
    setState({ ...state, [key]: next });
    const ok = await withToast(() => api.setLimits({ [key]: next }), { success: "Saved.", failure: "Couldn't save that limit" });
    if (!ok) setState(before);
    else onSaved();
  };
  const fields: { key: keyof Limits; name: string; explain: string; fmt: (v: number) => string;
                  step: number; min: number; max: number }[] = [
    { key: "daily_investigations", name: "Problems looked into per day",
      explain: "Past this, new ones wait for tomorrow — nothing is dropped.", fmt: (v) => `${v} a day`, step: 1, min: 1, max: 50 },
    { key: "per_case_budget", name: "Most one problem may cost",
      explain: "A problem that reaches this stops and says it ran out of budget.", fmt: (v) => money(v), step: 0.25, min: 0.25, max: 10 },
    { key: "per_case_wall_min", name: "Longest one problem may take",
      explain: "So nothing runs unattended forever.", fmt: (v) => `${v} min`, step: 5, min: 5, max: 240 },
  ];
  return (
    <div className="ps-checks">
      {fields.map((f) => (
        <div key={f.key} className="ps-check" style={{ gap: 10 }}>
          <span className="ps-muted">{f.name}</span>
          <div className="ps-row" style={{ justifyContent: "space-between" }}>
            <strong style={{ fontSize: 28, fontWeight: 600, letterSpacing: "-1px" }}>{f.fmt(state[f.key])}</strong>
            {admin && (
              <span className="ps-row" style={{ gap: 6 }}>
                <Button variant="ghost" size="sm" aria-label={`Decrease ${f.name}`} onClick={() => adjust(f.key, -f.step, f.min, f.max)}>−</Button>
                <Button variant="ghost" size="sm" aria-label={`Increase ${f.name}`} onClick={() => adjust(f.key, f.step, f.min, f.max)}>+</Button>
              </span>
            )}
          </div>
          <span className="ps-muted">{f.explain}</span>
        </div>
      ))}
    </div>
  );
}
