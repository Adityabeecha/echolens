export const SIDEBAR_STORAGE_KEY = "echolens_sidebar_collapsed";

type ReadStorage = Pick<Storage, "getItem">;
type WriteStorage = Pick<Storage, "setItem">;

export function resolveSidebarCollapsed(storage?: ReadStorage): boolean {
  try {
    const source = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    return source?.getItem(SIDEBAR_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function persistSidebarCollapsed(collapsed: boolean, storage?: WriteStorage): void {
  try {
    const target = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    target?.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    // The control still works for the current visit when storage is blocked.
  }
}
