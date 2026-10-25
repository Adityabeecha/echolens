// "Sonar Prism" — the EchoLens mark.
//
// Concentric soundwave rings on the left (the noisy echoes) pass through a
// prism and refract into one sharp beam that ends at a glowing node (the
// verified root cause). Drawn on a 32-unit grid with strokes no thinner than
// 1.6 units, so it stays crisp at 20px in the rail. `live` emanates the rings
// and breathes the node while any investigation runs; tokens.css stills it
// under prefers-reduced-motion.

export function Logo({ size = 24, live = false, title = "EchoLens", decorative = false }: {
  size?: number;
  /** Rings emanate and the node glows — used while any investigation runs. */
  live?: boolean;
  title?: string;
  /** Beside a visible "EchoLens" wordmark, the mark is decoration. */
  decorative?: boolean;
}) {
  return (
    <svg
      className={`el-logo${live ? " is-live" : ""}`}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      role={decorative ? undefined : "img"}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : live ? `${title} — investigating` : title}
    >
      {/* echoes: three arcs opening toward the prism */}
      <path className="el-logo__ring el-logo__ring--3" d="M3.2 6.6a11 11 0 0 1 0 18.8" />
      <path className="el-logo__ring el-logo__ring--2" d="M3.4 10.4a6.6 6.6 0 0 1 0 11.2" />
      <path className="el-logo__ring el-logo__ring--1" d="M3.6 13.9a2.4 2.4 0 0 1 0 4.2" />
      {/* the prism: a lens that turns many signals into one */}
      <path className="el-logo__prism" d="M16 8 22.4 24.2H9.6Z" />
      {/* the path through it, faint inside, full strength once it exits */}
      <path className="el-logo__facet" d="M12.9 16H19.1" />
      {/* the beam and the node it resolves to */}
      <path className="el-logo__beam" d="M19.6 16H25.8" />
      <circle className="el-logo__halo" cx="27.6" cy="16" r="3.9" />
      <circle className="el-logo__node" cx="27.6" cy="16" r="2.4" />
    </svg>
  );
}

/** The mark with the wordmark beside it, for the rail and public pages. */
export function LogoLockup({ size = 24, live = false, subtitle }: {
  size?: number; live?: boolean; subtitle?: string;
}) {
  return (
    <span className="el-logo-lockup">
      <Logo size={size} live={live} decorative />
      <span className="el-logo-lockup__text">
        <span className="el-logo-lockup__name">EchoLens</span>
        {subtitle && <span className="el-logo-lockup__sub">{subtitle}</span>}
      </span>
    </span>
  );
}
