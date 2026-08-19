import assert from "node:assert/strict";

let themeMode;
try {
  themeMode = await import("../src/themeMode.ts");
} catch {
  assert.fail("theme mode implementation is missing");
}

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
}

const storage = new MemoryStorage();
assert.equal(themeMode.resolveTheme(storage), "dark", "first run must default to dark");

storage.setItem(themeMode.THEME_STORAGE_KEY, "light");
assert.equal(themeMode.resolveTheme(storage), "light", "a saved light preference must be restored");

storage.setItem(themeMode.THEME_STORAGE_KEY, "unexpected");
assert.equal(themeMode.resolveTheme(storage), "dark", "invalid preferences must fall back safely to dark");

const meta = { content: "" };
const root = { dataset: {}, style: {} };
const documentLike = {
  documentElement: root,
  querySelector(selector) { return selector === 'meta[name="theme-color"]' ? meta : null; },
};

themeMode.applyTheme("light", documentLike);
assert.equal(root.dataset.theme, "light");
assert.equal(root.style.colorScheme, "light");
assert.equal(meta.content, "#f6f4ef");

themeMode.applyTheme("dark", documentLike);
assert.equal(root.dataset.theme, "dark");
assert.equal(root.style.colorScheme, "dark");
assert.equal(meta.content, "#101816");

themeMode.persistTheme("light", storage);
assert.equal(storage.getItem(themeMode.THEME_STORAGE_KEY), "light");
assert.equal(themeMode.nextTheme("light"), "dark");
assert.equal(themeMode.nextTheme("dark"), "light");

const blockedStorage = {
  getItem() { throw new Error("storage blocked"); },
  setItem() { throw new Error("storage blocked"); },
};
assert.equal(themeMode.resolveTheme(blockedStorage), "dark", "blocked storage must fall back to dark");
assert.doesNotThrow(() => themeMode.persistTheme("light", blockedStorage), "blocked storage must not stop the app");

console.log("Theme mode behavior verified.");
