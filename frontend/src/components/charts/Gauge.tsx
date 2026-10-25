// Health, 0–100, as a 240° dial with the number in the middle.
//
// Higher is healthier. Colour follows the fixed semantics: emerald from 75,
// neutral in the middle, calm amber below 45 (it needs a look). Coral never
// appears here — low health is not, by itself, a confirmed regression.

export function Gauge({ value, size = 120, label = "Health", caption }: {
  value: number | null | undefined;
  size?: number;
  label?: string;
  /** One short line under the number, e.g. "vs 82 last week". */
  caption?: string;
}) {
  const v = value == null || !Number.isFinite(value) ? null : Math.max(0, Math.min(100, value));
  const stroke = Math.max(6, size / 14);
  const r = (size - stroke) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const sweep = 240;
  const start = 150;                                   // degrees, clockwise from +x
  const arc = (from: number, to: number) => {
    const p = (deg: number) => {
      const rad = (deg * Math.PI) / 180;
      return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
    };
    const [x1, y1] = p(from);
    const [x2, y2] = p(to);
    return `M${x1.toFixed(2)} ${y1.toFixed(2)} A${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };
  const tone = v == null ? "none" : v >= 75 ? "verified" : v >= 45 ? "neutral" : "lead";
  return (
    <div className={`el-gauge el-gauge--${tone}`} style={{ width: size }}
         role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
         aria-valuenow={v ?? undefined} aria-valuetext={v == null ? "No data yet" : `${Math.round(v)} of 100`}>
      <svg width={size} height={size * 0.86} viewBox={`0 0 ${size} ${size * 0.86}`} aria-hidden>
        <path className="el-gauge__track" d={arc(start, start + sweep)} strokeWidth={stroke} />
        {v != null && v > 0 && (
          <path className="el-gauge__value" d={arc(start, start + (sweep * v) / 100)} strokeWidth={stroke} />
        )}
      </svg>
      <div className="el-gauge__center" style={{ top: size * 0.3 }}>
        <span className="el-gauge__number">{v == null ? "—" : Math.round(v)}</span>
        <span className="el-gauge__label">{label}</span>
      </div>
      {caption && <div className="el-gauge__caption">{caption}</div>}
    </div>
  );
}
