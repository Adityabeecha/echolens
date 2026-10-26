// A word-sized trend line. Decorative unless given a label: beside a number
// it repeats what the number says, so it stays out of the accessibility tree.

export function Sparkline({
  values, width = 96, height = 24, tone = "neutral", area = true, label,
}: {
  values: number[];
  width?: number;
  height?: number;
  /** Colour by meaning: neutral by default; `live` for AI activity,
   *  `verified` for a falling complaint rate after a fix, `lead`/`regress`
   *  only when the series IS that state. */
  tone?: "neutral" | "live" | "verified" | "lead" | "regress";
  area?: boolean;
  /** Give one when the sparkline stands alone; it becomes role="img". */
  label?: string;
}) {
  const pad = 2;
  const n = values.length;
  if (n === 0) return <svg width={width} height={height} aria-hidden />;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const px = (i: number) => pad + (n === 1 ? (width - 2 * pad) / 2 : (i / (n - 1)) * (width - 2 * pad));
  const py = (v: number) => pad + (1 - (v - lo) / span) * (height - 2 * pad);
  const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)} ${py(v).toFixed(1)}`).join(" ");
  const fill = `${d} L${px(n - 1).toFixed(1)} ${height - pad} L${px(0).toFixed(1)} ${height - pad} Z`;
  return (
    <svg className={`el-spark el-spark--${tone}`} width={width} height={height}
         viewBox={`0 0 ${width} ${height}`}
         role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      {area && <path className="el-spark__area" d={fill} />}
      <path className="el-spark__line" d={d} />
      <circle className="el-spark__end" cx={px(n - 1)} cy={py(values[n - 1])} r={2} />
    </svg>
  );
}
