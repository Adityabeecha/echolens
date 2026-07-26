import { useEffect, useState } from "react";
import { ProductRow, api, getRole, isAdmin } from "../api";
import { withToast } from "../components/Toast";
import { money } from "../format";
import { useAsync } from "../hooks";
import { C, MEASURE, R, S, T, mono } from "../theme";
import { Bar, Centered, ErrorState, Label, ScreenHeader } from "../ui";

interface Props {
  product: ProductRow | null;
  onGoCosts: () => void;
  onGoSources: () => void;
  onAddProduct: () => void;
  onDeleteProduct: (p: ProductRow) => void;
}

/**
 * Settings — the parts of "how EchoLens runs" that are a product decision.
 *
 * Budgets and limits used to live on the Costs screen, wedged between a token
 * table and a per-case cost breakdown: a PM who wanted to spend less had to go
 * looking through a developer's page to do it. The deep accounting stays on
 * Costs; the levers are here.
 */
export function Settings({
  product, onGoCosts, onGoSources, onAddProduct, onDeleteProduct,
}: Props) {
  const { data, loading, error, reload } = useAsync(() => api.costsSummary(), []);
  const admin = isAdmin();

  if (loading && !data) return <Centered>Loading settings…</Centered>;
  if (error || !data) {
    return (
      <div style={{ padding: 28 }}>
        <ErrorState title="Couldn't load your settings" onRetry={reload} />
      </div>
    );
  }

  const spentPct = data.budget ? (data.month_to_date / data.budget) * 100 : 0;
  const over = data.month_to_date > data.budget;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Settings"
        product={product?.name ?? data.product}
        subtitle="BUDGETS, LIMITS AND THIS PRODUCT"
        right={
          <span style={{ fontFamily: mono, fontSize: T.xs, color: C.muted }}>
            SIGNED IN AS {getRole().toUpperCase()}
          </span>
        }
      />

      <div style={{ flex: 1, overflow: "auto", padding: `${S[5]} ${S[6]} ${S[12]}` }}>
        <Label style={{ marginBottom: S[2] }}>SPEND THIS MONTH</Label>
        <div style={{ maxWidth: MEASURE, padding: `${S[4]} ${S[5]}`, background: C.card,
                      border: `1px solid ${over ? `${C.bad}55` : C.border2}`, borderRadius: R.card }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline",
                        marginBottom: S[3], flexWrap: "wrap", gap: S[2] }}>
            <span style={{ fontSize: T.base, color: C.text2 }}>
              {money(data.month_to_date)} of {money(data.budget)} used
            </span>
            <span style={{ fontFamily: mono, fontSize: T.sm,
                           color: over ? C.bad : C.muted }}>
              {over
                ? `${money(data.month_to_date - data.budget)} over budget`
                : `${money(data.budget - data.month_to_date)} left`}
            </span>
          </div>
          <Bar pct={Math.min(100, spentPct)} color={over ? C.bad : C.accent} height={8} />
          <div style={{ fontSize: T.sm, color: C.dim, marginTop: S[3], lineHeight: "var(--el-lh-normal)" }}>
            Investigations stop at the per-case caps below, so a runaway case cannot spend the
            month.{" "}
            <span onClick={onGoCosts} className="el-btn" role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") onGoCosts(); }}
              style={{ color: C.accent, cursor: "pointer" }}>
              See what each case cost →
            </span>
          </div>
        </div>

        <Label style={{ margin: "28px 0 10px" }}>
          LIMITS{admin ? "" : " · ADMIN CAN ADJUST"}
        </Label>
        <LimitsPanel limits={data.limits} onSaved={reload} />

        <Label style={{ margin: "28px 0 10px" }}>THIS PRODUCT</Label>
        <div style={{ maxWidth: MEASURE, padding: `${S[4]} ${S[5]}`, background: C.card,
                      border: `1px solid ${C.border2}`, borderRadius: R.card,
                      display: "flex", flexDirection: "column", gap: S[3] }}>
          <Field label="Name" value={product?.name ?? data.product ?? "—"} />
          <Field label="Play Store package" value={product?.package_name ?? "not connected"} />
          <Field label="GitHub repo" value={product?.github_repo ?? "not connected"} />
          <div style={{ display: "flex", gap: S[2], marginTop: S[1], flexWrap: "wrap" }}>
            <button onClick={onGoSources} className="el-btn"
              style={{ background: "transparent", color: C.text2, border: `1px solid ${C.border3}`,
                       borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, cursor: "pointer" }}>
              Manage sources
            </button>
            {admin && (
              <button onClick={onAddProduct} className="el-btn"
                style={{ background: "transparent", color: C.text2,
                         border: `1px solid ${C.border3}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`,
                         fontSize: T.base, cursor: "pointer" }}>
                Add another product
              </button>
            )}
            {admin && product && (
              <button onClick={() => onDeleteProduct(product)} className="el-btn"
                style={{ background: "transparent", color: C.bad, border: `1px solid ${C.bad}55`,
                         borderRadius: R.control, padding: `${S[2]} ${S[3]}`, fontSize: T.base, cursor: "pointer" }}>
                Delete {product.name}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "170px 1fr", gap: S[3],
                  alignItems: "baseline" }}>
      <span style={{ fontSize: T.sm, color: C.muted }}>{label}</span>
      <span style={{ fontFamily: mono, fontSize: T.sm, color: C.text2, wordBreak: "break-all" }}>
        {value}
      </span>
    </div>
  );
}

function LimitsPanel({ limits, onSaved }: {
  limits: { daily_investigations: number; per_case_budget: number; per_case_wall_min: number };
  onSaved: () => void;
}) {
  const [state, setState] = useState(limits);
  useEffect(() => setState(limits), [limits]);
  const admin = isAdmin();

  const adjust = async (key: keyof typeof state, delta: number, min: number, max: number) => {
    const before = state;
    const next = Math.min(max, Math.max(min, +(state[key] + delta).toFixed(2)));
    if (next === state[key]) return;
    setState({ ...state, [key]: next });
    const ok = await withToast(() => api.setLimits({ [key]: next }), {
      success: "Limit saved.",
      failure: "Couldn't save that limit",
    });
    if (!ok) setState(before);
    else onSaved();
  };

  const fields: {
    key: keyof typeof state; name: string; explain: string;
    fmt: (v: number) => string; step: number; min: number; max: number;
  }[] = [
    { key: "daily_investigations", name: "Investigations per day",
      explain: "Anything past this queues for tomorrow rather than being dropped.",
      fmt: (v) => `${v} / day`, step: 1, min: 1, max: 50 },
    { key: "per_case_budget", name: "Budget per case",
      explain: "A case that hits this stops and reports budget exhausted, honestly.",
      fmt: (v) => money(v), step: 0.25, min: 0.25, max: 10 },
    { key: "per_case_wall_min", name: "Time per case",
      explain: "Wall-clock cap, so nothing runs unattended forever.",
      fmt: (v) => `${v} min`, step: 5, min: 5, max: 240 },
  ];

  return (
    <div style={{ display: "flex", gap: S[3], maxWidth: MEASURE, flexWrap: "wrap" }}>
      {fields.map((f) => (
        <div key={f.key} style={{ flex: 1, minWidth: 240, padding: `${S[3]} ${S[4]}`, background: C.card,
                                  border: `1px solid ${C.border2}`, borderRadius: R.card }}>
          <div style={{ display: "flex", alignItems: "center", gap: S[3] }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: T.sm, color: C.text3 }}>{f.name}</div>
              <div style={{ fontFamily: mono, fontSize: T.lg, color: C.text, marginTop: S[1] }}>
                {f.fmt(state[f.key])}
              </div>
            </div>
            {admin && (
              <div style={{ display: "flex", flexDirection: "column", gap: S[1] }}>
                <button className="el-btn" aria-label={`Increase ${f.name}`}
                  onClick={() => adjust(f.key, f.step, f.min, f.max)} style={stepBtn}>▲</button>
                <button className="el-btn" aria-label={`Decrease ${f.name}`}
                  onClick={() => adjust(f.key, -f.step, f.min, f.max)} style={stepBtn}>▼</button>
              </div>
            )}
          </div>
          <div style={{ fontSize: T.xs, color: C.dim, marginTop: S[2], lineHeight: "var(--el-lh-normal)" }}>
            {f.explain}
          </div>
        </div>
      ))}
    </div>
  );
}

const stepBtn: React.CSSProperties = {
  width: 22, height: 20, borderRadius: R.sm, border: `1px solid ${C.border3}`, background: C.hover,
  color: C.muted, fontSize: T.micro, cursor: "pointer", lineHeight: 1,
};
