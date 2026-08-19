import { ThemeMode, nextTheme } from "../themeMode";
import { Icon } from "./Icon";

export function ThemeToggle({ mode, onChange, compact = false }: {
  mode: ThemeMode;
  onChange: (mode: ThemeMode) => void;
  compact?: boolean;
}) {
  const next = nextTheme(mode);
  const label = `Switch to ${next} theme`;

  return (
    <button
      type="button"
      className={`el-theme-toggle${compact ? " is-compact" : ""}`}
      onClick={() => onChange(next)}
      aria-label={label}
      title={label}
    >
      <Icon name={mode === "dark" ? "sun" : "moon"} size={16} />
      {!compact && <span className="el-nav-label">{next === "light" ? "Light mode" : "Dark mode"}</span>}
    </button>
  );
}
