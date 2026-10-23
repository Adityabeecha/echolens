import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Narrow connect-src to the one API origin this build talks to.
 *
 * vercel.json carries the full Content-Security-Policy as a response header
 * (frame-ancestors only works there), but it is static, so its connect-src
 * has to allow any https: origin. This adds a second, build-time policy as a
 * <meta> tag whose connect-src names the exact origin from VITE_API_BASE.
 * Browsers enforce every policy present, so the effective connect-src is the
 * intersection: 'self' plus that API origin plus Google sign-in.
 * Build-only: the dev server's HMR websocket is not in the list.
 */
function apiConnectCsp(apiBase: string | undefined): Plugin {
  let origin = "";
  // Same repair as api.ts: a value without a scheme means https.
  const raw = (apiBase ?? "").trim();
  const base = raw && !raw.startsWith("/") && !/^https?:\/\//i.test(raw) ? `https://${raw}` : raw;
  try {
    if (base && /^https?:\/\//i.test(base)) origin = new URL(base).origin;
  } catch {
    origin = "";
  }
  const policy = ["connect-src 'self'", origin, "https://accounts.google.com/gsi/"]
    .filter(Boolean)
    .join(" ");
  return {
    name: "echolens-api-connect-csp",
    apply: "build",
    transformIndexHtml: () => [
      {
        tag: "meta",
        attrs: { "http-equiv": "Content-Security-Policy", content: policy },
        injectTo: "head-prepend", // before any script; charset stays inside the first 1024 bytes
      },
    ],
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  // With ECHOLENS_API_ORIGIN set, Vercel proxies /api/* to the API
  // (build/vercel-output.mjs), so the app must call its own origin: a leftover
  // VITE_API_BASE pointing at the API directly would bring back the
  // cross-site cookie Safari drops.
  const proxied = Boolean(process.env.ECHOLENS_API_ORIGIN?.trim());
  const apiBase = proxied ? "/api" : env.VITE_API_BASE;
  return {
    plugins: [react(), apiConnectCsp(apiBase)],
    define: proxied ? { "import.meta.env.VITE_API_BASE": JSON.stringify("/api") } : {},
    server: {
      proxy: {
        // Frontend calls /api/*; the backend serves routes without that prefix.
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/api/, ""),
        },
      },
    },
  };
});
