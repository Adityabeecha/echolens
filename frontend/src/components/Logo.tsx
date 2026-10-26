/** Sonar Prism: the exact 34-unit mark from design/approved/today.html. */
export function Logo({ size = 28, live = false, title = "EchoLens", decorative = false }: {
  size?: number; live?: boolean; title?: string; decorative?: boolean;
}) {
  return <svg width={size} height={size} viewBox="0 0 34 34" className={`el-logo${live ? " is-live" : ""}`}
    role={decorative ? undefined : "img"} aria-hidden={decorative || undefined}
    aria-label={decorative ? undefined : live ? `${title} — investigating now` : title}>
    <circle cx="9" cy="17" r="3" fill="var(--el-ink)" />
    <circle className="el-logo__echo" cx="9" cy="17" r="8" fill="none" stroke="var(--el-ink)" strokeWidth="1.4" opacity=".3" />
    <path d="M18 9 L25 17 L18 25 Z" fill="none" stroke="var(--el-ink)" strokeWidth="1.8" strokeLinejoin="round" />
    <path d="M25 17 H31" fill="none" stroke="var(--el-stamp-red)" strokeWidth="2.4" strokeLinecap="round" />
  </svg>;
}
export function LogoLockup({ size = 28, live = false, subtitle }: { size?: number; live?: boolean; subtitle?: string }) {
  return <span className="el-logo-lockup"><Logo size={size} live={live} decorative />
    <span className="el-logo-lockup__text"><span className="el-logo-lockup__name">EchoLens</span>
      {subtitle && <span className="el-logo-lockup__sub">{subtitle}</span>}</span></span>;
}
