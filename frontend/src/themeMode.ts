export type ThemeMode = "dark" | "light";

export const THEME_STORAGE_KEY = "echolens_theme";

type StorageLike = Pick<Storage, "getItem" | "setItem">;
type ThemeDocument = {
  documentElement: {
    dataset: Record<string, string | undefined>;
    style: { colorScheme: string };
  };
  querySelector: (selector: string) => { content: string } | null;
};

export function resolveTheme(storage?: Pick<Storage, "getItem">): ThemeMode {
  try {
    const source = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    return source?.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function nextTheme(theme: ThemeMode): ThemeMode {
  return theme === "dark" ? "light" : "dark";
}

export function applyTheme(theme: ThemeMode, target?: ThemeDocument): void {
  const doc = target ?? (document as unknown as ThemeDocument);
  doc.documentElement.dataset.theme = theme;
  doc.documentElement.style.colorScheme = theme;
  const meta = doc.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "dark" ? "#101816" : "#f6f4ef";
}

export function persistTheme(theme: ThemeMode, storage?: StorageLike): void {
  try {
    const target = storage ?? (typeof window !== "undefined" ? window.localStorage : undefined);
    target?.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Privacy modes and sandboxed embeds may deny storage. The active in-memory
    // theme still works; it simply cannot persist across reloads.
  }
}
