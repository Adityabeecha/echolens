import { api } from "../../api";
import { useAsync } from "../../hooks";
import { LabelStamp } from "./LabelStamp";

/** The cap the code ships with, shown while /guards/config is unreachable. */
const FALLBACK_CAP = 0.75;

/**
 * The four honesty checks, in plain words. The single-source cap is read from
 * the server (GET /guards/config, public) so the page states the number the
 * code actually enforces; the guard names stay in tooltips.
 */
export function HonestyChecks() {
  const cfg = useAsync(() => api.guardsConfig(), []);
  const cap = Math.round((cfg.data?.single_source_cap ?? FALLBACK_CAP) * 100);
  const checks = [
    { stamp: <LabelStamp tone="ink" rotation={-4}>EVERY CLAIM CITED</LabelStamp>, tip: "Citation check",
      text: "A sentence without proof is removed from the answer and shown separately as a hunch." },
    { stamp: <LabelStamp tone="hunch" rotation={3}>TWO WITNESSES</LabelStamp>, tip: "Two-source rule and single-source cap",
      text: `One kind of source is only a hunch, capped at ${cap}% sure. Confirming needs two independent kinds.` },
    { stamp: <LabelStamp tone="request" rotation={-2}>CAUSE CAME FIRST</LabelStamp>, tip: "Temporal-order check",
      text: "A release can't be blamed for complaints that started before it shipped." },
    { stamp: <LabelStamp tone="confirmed" rotation={4}>TRIED TO DISPROVE IT</LabelStamp>, tip: "Counter-evidence pass",
      text: "Before confirming, EchoLens looks for evidence against its own answer." },
  ];
  return (
    <div className="pub-checks">
      {checks.map((c) => (
        <div key={c.tip} className="pub-check" title={c.tip}>
          {c.stamp}
          <div>{c.text}</div>
        </div>
      ))}
    </div>
  );
}
