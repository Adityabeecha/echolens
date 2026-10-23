// Same-origin API proxy for Vercel, configured by one build env var.
//
// Why: on *.vercel.app the frontend and the Northflank API are different
// sites, and Safari (ITP) drops the API's session cookie as a third-party
// cookie, so sign-in silently fails. Proxying /api/* through the frontend's own
// domain makes the cookie first-party.
//
// vercel.json cannot read environment variables, so the proxy target cannot
// live there. When ECHOLENS_API_ORIGIN is set at build time, this writes the
// Build Output API (.vercel/output) instead: the built files plus the routes
// from vercel.json, with /api/* proxied to that origin and the CSP narrowed to
// same-origin. Unset, it does nothing and vercel.json applies as before.
//
//   ECHOLENS_API_ORIGIN=https://echolens-api--xyz.code.run node build/vercel-output.mjs
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const raw = (process.env.ECHOLENS_API_ORIGIN || "").trim();
if (!raw) {
  console.log("vercel-output: ECHOLENS_API_ORIGIN unset — no /api proxy, vercel.json applies.");
  process.exit(0);
}
let origin;
try {
  const url = new URL(raw);
  if (url.protocol !== "https:") throw new Error("must be https://");
  origin = url.origin;
} catch (err) {
  console.error(`vercel-output: ECHOLENS_API_ORIGIN=${raw} is not a usable https origin (${err.message}).`);
  process.exit(1);
}
if (!existsSync("dist/index.html")) {
  console.error("vercel-output: dist/ is missing — run `npm run build` first.");
  process.exit(1);
}

const vercel = JSON.parse(readFileSync("vercel.json", "utf8"));
// The same headers vercel.json sends, with connect-src narrowed: every API call
// is now same-origin, so no other https origin needs to be reachable.
const headers = {};
for (const h of vercel.headers?.find((x) => x.source === "/(.*)")?.headers ?? []) {
  headers[h.key] = h.key === "Content-Security-Policy"
    ? h.value.replace(/connect-src [^;]*/, "connect-src 'self' https://accounts.google.com/gsi/")
    : h.value;
}

rmSync(".vercel/output", { recursive: true, force: true });
mkdirSync(".vercel/output/static", { recursive: true });
cpSync("dist", ".vercel/output/static", { recursive: true });
writeFileSync(".vercel/output/config.json", JSON.stringify({
  version: 3,
  routes: [
    // The API keeps its own paths; the frontend calls them under /api.
    { src: "^/api/(.*)$", dest: `${origin}/$1` },
    { src: "^/(.*)$", headers, continue: true },
    { handle: "filesystem" },
    // Anything that is not a built file is a client-side route.
    { src: "^/(.*)$", dest: "/index.html" },
  ],
}, null, 2));
console.log(`vercel-output: /api/* -> ${origin}; wrote .vercel/output (Build Output API v3).`);
