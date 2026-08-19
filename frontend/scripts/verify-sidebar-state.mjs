import assert from "node:assert/strict";

let sidebarState;
try {
  sidebarState = await import("../src/sidebarState.ts");
} catch {
  assert.fail("sidebar state implementation is missing");
}

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
}

const storage = new MemoryStorage();
assert.equal(sidebarState.resolveSidebarCollapsed(storage), false, "the wide sidebar must start open");

storage.setItem(sidebarState.SIDEBAR_STORAGE_KEY, "1");
assert.equal(sidebarState.resolveSidebarCollapsed(storage), true, "a saved collapsed choice must be restored");

storage.setItem(sidebarState.SIDEBAR_STORAGE_KEY, "unexpected");
assert.equal(sidebarState.resolveSidebarCollapsed(storage), false, "invalid state must fall back to open");

sidebarState.persistSidebarCollapsed(true, storage);
assert.equal(storage.getItem(sidebarState.SIDEBAR_STORAGE_KEY), "1");
sidebarState.persistSidebarCollapsed(false, storage);
assert.equal(storage.getItem(sidebarState.SIDEBAR_STORAGE_KEY), "0");

const blockedStorage = {
  getItem() { throw new Error("storage blocked"); },
  setItem() { throw new Error("storage blocked"); },
};
assert.equal(sidebarState.resolveSidebarCollapsed(blockedStorage), false);
assert.doesNotThrow(() => sidebarState.persistSidebarCollapsed(true, blockedStorage));

console.log("Sidebar state behavior verified.");
