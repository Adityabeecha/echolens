import { useState } from "react";
import { TicketResult, TrackerId, api, canReview } from "../api";
import { useAsync } from "../hooks";
import { C, S, T } from "../theme";
import { Button } from "../ui";
import { withToast } from "./Toast";

interface Props {
  findingId: number;
  /** Called after a ticket is filed, e.g. to reload the case. */
  onFiled?: (result: TicketResult) => void;
  /** Disable every button (e.g. the case is not resolved yet). */
  disabled?: boolean;
}

/**
 * "File this finding" for every tracker the deployment has configured —
 * GitHub, Linear, Jira. One button each, not a dropdown: there are at most
 * three, and a hidden choice is a choice nobody discovers.
 *
 * Self-contained so any screen can drop it in. Renders nothing for someone who
 * can't file (viewers, guests), and a one-line pointer to Settings when no
 * tracker is configured, rather than a button that can only fail.
 */
export function TrackerMenu({ findingId, onFiled, disabled }: Props) {
  const { data, error } = useAsync(() => api.trackers(), []);
  const [busy, setBusy] = useState<TrackerId | null>(null);

  if (!canReview() || error) return null;
  if (!data) return null;  // a split second; a spinner here would only flicker
  const ready = data.trackers.filter((t) => t.configured);
  if (ready.length === 0) {
    return (
      <span style={{ fontSize: T.sm, color: C.dim }}>
        No issue tracker is set up. Settings lists what to configure.
      </span>
    );
  }

  const file = async (tracker: TrackerId, label: string) => {
    setBusy(tracker);
    const r = await withToast(() => api.createTicket(findingId, tracker), {
      success: (res) => `Filed in ${label}${res.number != null ? ` as ${tracker === "github" ? "#" : ""}${res.number}` : ""}.`,
      failure: `Couldn't file the ${label} issue`,
    });
    setBusy(null);
    if (r) onFiled?.(r);
  };

  return (
    <span role="group" aria-label="File this finding"
      style={{ display: "inline-flex", gap: S[2], flexWrap: "wrap", alignItems: "center" }}>
      {ready.map((t) => (
        <Button key={t.id} variant="ghost" size="sm" icon="external"
          loading={busy === t.id} disabled={disabled || (busy != null && busy !== t.id)}
          onClick={() => file(t.id, t.label)}>
          {busy === t.id ? "Filing…" : `File in ${t.label}`}
        </Button>
      ))}
    </span>
  );
}
