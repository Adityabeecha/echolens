import { CSSProperties, ReactNode } from "react";
import "../../components/casefile/casefile.css";

/**
 * A stamp with its own words — the landing page's honesty checks
 * ("TWO WITNESSES", "CAUSE CAME FIRST"). The shared `Stamp` only prints the
 * five verdicts, so this is a thin local wrapper over the same `cf-stamp`
 * classes: same border, type, rotation and one-time press. It is never a
 * verdict on a problem; use `Stamp` for those.
 */
export function LabelStamp({ children, tone, rotation = -4 }: {
  children: ReactNode;
  /** Colour by meaning: ink (plain rule), hunch (amber dashed), request (pencil blue), confirmed (red). */
  tone: "ink" | "hunch" | "request" | "confirmed";
  rotation?: number;
}) {
  const cls = tone === "ink" ? "pub-stamp--ink" : `cf-stamp--${tone}`;
  return (
    <span className={`cf-stamp is-compact ${cls}`}
      style={{ "--stamp-rotation": `${rotation}deg` } as CSSProperties}>
      {children}
    </span>
  );
}
