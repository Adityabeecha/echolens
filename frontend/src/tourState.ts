// The first-run tour is shown once per browser. Storage can be blocked
// (private windows, strict cookie settings), so every access is guarded and a
// failure means "don't show it" rather than "show it on every load".
export const TOUR_STORAGE_KEY = "echolens_tour_v1";

type ReadStorage = Pick<Storage, "getItem">;
type WriteStorage = Pick<Storage, "setItem">;

export function tourSeen(storage?: ReadStorage): boolean {
  try {
    const source = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    return source ? source.getItem(TOUR_STORAGE_KEY) === "done" : true;
  } catch {
    return true;
  }
}

export function markTourSeen(storage?: WriteStorage): void {
  try {
    const target = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    target?.setItem(TOUR_STORAGE_KEY, "done");
  } catch {
    // Dismissed for this visit either way; the component state already closed it.
  }
}
