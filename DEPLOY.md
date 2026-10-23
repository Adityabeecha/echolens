# Deploy EchoLens

## Production architecture

Use three managed services:

- PostgreSQL, such as Supabase, for persistent data.
- Northflank for the long-running FastAPI container, background investigations, and scheduler.
- Vercel for the static React frontend.

The frontend and backend use separate origins. `VITE_API_BASE` tells the browser where the API lives, and `CORS_ORIGINS` tells the API which browser origins may call it.

## Prerequisites

- This GitHub repository connected to Northflank and Vercel.
- A PostgreSQL database and pooler connection string.
- An OpenAI API key.
- A generated JWT signing secret.
- Optional GitHub, Google, Slack, SMTP, and webhook credentials described in [ENV_SETUP.md](ENV_SETUP.md).

## 1. Database

Create a PostgreSQL database. For Supabase, copy the pooler connection string from the database connection settings. Use it as `ECHOLENS_DB_URL`; the application initializes its schema during startup.

Keep the database region close to the backend region. Do not expose the connection string in frontend settings or commit it to Git.

## 2. Backend on Northflank

1. Create a project and add a combined service from this GitHub repository.
2. Select production branch `main` and enable build-on-push.
3. Set the service root/build context to `backend`.
4. Select Dockerfile builds using `backend/Dockerfile`.
5. Expose container port `8000` over HTTP and enable public DNS.
6. Configure an HTTP health check for `GET /health` on port `8000`.
7. Add these minimum environment variables:

| Variable | Value |
|---|---|
| `ECHOLENS_ENV` | `production` |
| `ECHOLENS_DB_URL` | PostgreSQL pooler URL |
| `OPENAI_API_KEY` | Secret OpenAI key |
| `JWT_SECRET` | Unique generated secret |
| `CORS_ORIGINS` | Exact Vercel origin; add after the frontend is created |
| `SESSION_COOKIE_SAMESITE` | `none` when the frontend and API are on different sites (Vercel + Northflank); see [Browser sessions](#browser-sessions-cookies-and-csrf) |
| `ECHOLENS_LOG_JSON` | `1` |

Add integrations from [ENV_SETUP.md](ENV_SETUP.md) only when those features are used. Keep one application worker: investigations and scheduled collection use in-process coordination.

Deploy the service and record its public origin, for example `https://api.example.code.run`. Verify:

```bash
curl https://api.example.code.run/health
```

The endpoint must return HTTP `200` before connecting the frontend.

## 3. Frontend on Vercel

1. Import this GitHub repository into Vercel.
2. Set Production Branch to `main`.
3. Set Root Directory to `frontend`.
4. Confirm Framework Preset is Vite.
5. Leave Build Command and Output Directory to `frontend/vercel.json`: it runs `npm run build && node build/vercel-output.mjs` and serves `dist`.
6. Choose how the browser reaches the API (below), and set that variable for Production (and Preview, if you use previews).
7. Deploy and record the canonical Vercel origin.

### Same-origin API proxy (recommended, and required for Safari)

On `*.vercel.app` the frontend and the Northflank API are different sites. Safari (and Chrome with tracking protection) treats the API's session cookie as third-party and drops it, so sign-in appears to work and the next request returns `401`. The fix that costs nothing is to call the API through the frontend's own domain:

| Where | Variable | Value |
|---|---|---|
| Vercel (build env) | `ECHOLENS_API_ORIGIN` | the Northflank origin, e.g. `https://api--echolens--abc123.code.run` (https, no path, no trailing slash) |
| Vercel | `VITE_API_BASE` | **unset** (it is ignored when `ECHOLENS_API_ORIGIN` is set) |
| Northflank | `SESSION_COOKIE_SAMESITE` | `lax` |
| Northflank | `CORS_ORIGINS` | unchanged: the exact Vercel origin. It can stay strict, because the browser now only talks to its own origin. |

`vercel.json` cannot read environment variables, so the proxy is written at build time: with `ECHOLENS_API_ORIGIN` set, `build/vercel-output.mjs` emits Vercel's Build Output API (`.vercel/output`), with the built files plus the rewrites and headers from `vercel.json`, and `/api/*` proxied to the API. Vercel deploys that output instead of `dist`. The app calls `/api/...` on its own origin. The Content-Security-Policy's `connect-src` becomes `'self'` plus Google sign-in, in both the header and the build-time `<meta>` policy. Changing the API origin needs a Vercel redeploy.

Check it after deploying: `curl -i https://<your-app>.vercel.app/api/health` must return the API's JSON (not `index.html`), and signing in from Safari must keep you signed in after a reload. The live trace is an `EventSource` through the same proxy. If the proxy ever cuts a long stream, the trace view falls back to polling on its own.

### Direct API origin (split sites)

Leave `ECHOLENS_API_ORIGIN` unset and set `VITE_API_BASE` to the Northflank origin (no trailing slash). The browser then calls the API directly, so the session cookie is cross-site: Northflank needs `SESSION_COOKIE_SAMESITE=none` (see [Browser sessions](#browser-sessions-cookies-and-csrf)), and Safari users will not stay signed in unless both run under one custom domain.

`frontend/vercel.json` supplies the SPA rewrite so client-side routes resolve to `index.html`, and the security headers for every page: a Content-Security-Policy (`frame-ancestors 'none'`, scripts from the site itself and Google Identity Services only, Google Fonts styles and fonts, `data:` images), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin` and `X-Frame-Options: DENY`.

The header's `connect-src` is static and therefore allows any `https:` origin. The build narrows it: `vite.config.ts` reads `VITE_API_BASE` at build time and injects a second policy as a `<meta>` tag whose `connect-src` is `'self'`, that exact API origin and Google sign-in. Browsers enforce both policies, so the effective allowlist is the intersection. Consequently `VITE_API_BASE` must be set for the build that is deployed, and changing the API origin requires a frontend rebuild, not just a backend change. If you add another origin the browser must call (an analytics endpoint, a second API), add it to both `frontend/vercel.json` and the plugin in `frontend/vite.config.ts`.

### Clean URLs

The app uses history paths (`/p/2/today`, `/p/2/cases/34/trace`, `/share/<token>`), not hash routes. Every path that is not a built file is rewritten to `index.html`, so deep links and refreshes work. Old hash links (`/#/p/2/today`, `/#/share/<token>`, `/#/cases/34`) from bookmarks, Slack and email are rewritten to the clean path when the page loads. `/costs` links open Settings → Costs.

## 4. Connect frontend and backend

Return to Northflank and set `CORS_ORIGINS` to the exact Vercel origin, including `https://` and excluding a trailing slash. For multiple approved origins, use a comma-separated list. Set `APP_BASE_URL` to the canonical frontend origin when notifications should include deep links.

Redeploy the backend after changing environment variables. Then open the Vercel URL and confirm the login page can load `/auth/config` without a CORS error.

Create the first administrator with one method:

- Temporarily set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`, deploy once, then remove both values.
- Or run `python -m echolens.cli createuser EMAIL PASSWORD --role admin` from a trusted environment connected to the production database.

Do not expose `ECHOLENS_ENV=dev` publicly.

### Browser sessions: cookies and CSRF

The browser session is an `HttpOnly`, `Secure` cookie (`echolens_session`) set by `/auth/login`, `/auth/signup` (self-service bootstrap only) and `/auth/google`, and cleared by `POST /auth/logout`. The JWT is never stored in `localStorage`. Non-browser clients (the GitHub workflows, the CLI, scripts) keep using the `token` from the login response as `Authorization: Bearer`; a Bearer header always takes precedence over a cookie.

Cross-site cookies need all of the following, or sign-in will appear to work and every following request will return `401`:

- `SESSION_COOKIE_SAMESITE=none` when the frontend and API are on different registrable domains (for example `*.vercel.app` and `*.code.run`). Browsers only send cookies on cross-site `fetch`/`EventSource` requests when they are `SameSite=None`, and only accept `SameSite=None` together with `Secure`. If both run under one domain (for example `app.example.com` and `api.example.com`), keep the default `lax`.
- `SESSION_COOKIE_SECURE=true` (the default). Production and staging refuse to start with it off.
- `CORS_ORIGINS` set to the exact frontend origin(s). The API only enables credentialed CORS (`Access-Control-Allow-Credentials: true`) when this list is explicit; with no list (local dev) credentials stay off.
- Optionally `SESSION_COOKIE_DOMAIN` (for example `.example.com`) to share the cookie across subdomains; leave empty for a host-only cookie.

Browsers that block third-party cookies (Safari by default, Chrome with tracking protection) will not send a `SameSite=None` cookie to a different site at all. For those users the reliable setup is to serve the API from a subdomain of the frontend's domain (a custom domain on both Vercel and Northflank) and keep `SESSION_COOKIE_SAMESITE=lax`.

Cookie-authenticated `POST`, `PUT`, `PATCH` and `DELETE` requests must carry `X-CSRF-Token` equal to the `echolens_csrf` cookie (double-submit). The frontend receives the value in the login response and recovers it after a reload from `GET /auth/csrf`; Bearer-authenticated requests are exempt.

The live trace (`/investigations/{id}/trace/stream`) authenticates with the cookie (`EventSource` with `withCredentials`). The old `?token=` query parameter is still accepted for one release and logs a `deprecated_query_token` warning; it will be removed.

## 5. Configure scheduled workflows

In GitHub Settings, add these Actions secrets:

- `ECHOLENS_API`: Northflank backend origin.
- `ECHOLENS_EMAIL`: reviewer or administrator account used by automation.
- `ECHOLENS_PASSWORD`: password for that account.

Also add an Actions variable named `ECHOLENS_API` with the same backend origin. The secret is used by scheduled jobs; the variable is used by the post-deployment health workflow.

The retained workflows perform:

- `.github/workflows/collect.yml`: collect, scan, and triage every six hours.
- `.github/workflows/brief.yml`: send the weekly brief.
- `.github/workflows/deploy.yml`: poll `/health` (up to about 10 minutes) after backend changes reach `main`.
- `.github/workflows/ci.yml`: on every push and pull request to `main`, runs the backend tests (Python 3.11, SQLite) and the frontend `npm ci` + `npm run build` (Node 22).

Run each scheduled workflow manually once from the Actions tab to validate credentials.

## Security checklist

- Set `ECHOLENS_ENV` explicitly (`production`, or `staging`) on every deployed environment. The app refuses to start outside local dev without an explicit value; `dev` disables authentication and must never be public.
- Use a strong, unique `JWT_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- Set `CORS_ORIGINS` to the exact frontend origin(s), with no trailing slash.
- Set `SESSION_COOKIE_SAMESITE=none` for a split-site frontend and API, and keep `SESSION_COOKIE_SECURE=true`.
- Build the frontend with `VITE_API_BASE` set, so the Content-Security-Policy names the real API origin.
- Set `GITHUB_WEBHOOK_SECRET` if GitHub webhooks are used, and the same value in the webhook config.
- Restrict Google sign-in with `GOOGLE_ALLOWED_DOMAINS` (comma-separated email domains). If empty, only emails in `GOOGLE_ADMIN_EMAILS` or existing users can sign in. `GOOGLE_DEFAULT_ROLE` defaults to `viewer`.
- In the Google OAuth client, add the frontend origin (and `http://localhost:5173` for local development) to Authorized JavaScript origins.
- Use a dedicated low-privilege reviewer account for `ECHOLENS_EMAIL`/`ECHOLENS_PASSWORD`, not an admin.
- Keep `GUEST_DEMO_ONLY=true` for public demos, and run `python -m echolens.cli preflight` before deploying.

## Verify the deployment

1. `GET <backend>/health` returns HTTP `200`.
2. The Vercel deployment shows the latest `main` commit.
3. The browser loads `/auth/config` from the Northflank origin without CORS errors.
4. An administrator can sign in and open the Today, Cases, Sources, and Settings screens.
5. A source collection run completes or reports a clear source-specific error.
6. The GitHub deployment-verification workflow succeeds after a backend push.

## Troubleshooting

### The frontend did not update

Confirm Vercel is connected to this repository, uses branch `main`, and has Root Directory `frontend`. Northflank backend deployments do not publish frontend-only changes.

### Browser requests fail but curl works

Compare the browser origin with `CORS_ORIGINS` character for character. Update Northflank and redeploy the backend.

### The frontend calls `/api` on the Vercel domain

That is expected with the same-origin proxy. If `/api/health` on the Vercel domain returns `index.html` instead of the API's JSON, `ECHOLENS_API_ORIGIN` was missing (or not https) during the build: set it and redeploy Vercel. Without the proxy, `VITE_API_BASE` was missing during the build: set it to the Northflank origin and redeploy.

### Northflank starts but health checks fail

Inspect startup logs and verify `ECHOLENS_DB_URL` uses a reachable PostgreSQL pooler URL. Run `python -m echolens.cli preflight` with the production environment to identify insecure or missing settings.

### Scheduled workflows return `401`

Verify `ECHOLENS_EMAIL` and `ECHOLENS_PASSWORD` match an active account and `ECHOLENS_API` points to the backend origin without an extra path.
