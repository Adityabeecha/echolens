# Deploying EchoLens to production (Fly.io backend + Vercel frontend + Supabase)

The repo is deploy-ready: [backend/fly.toml](backend/fly.toml) defines the backend,
[frontend/vercel.json](frontend/vercel.json) configures the frontend, migrations run
automatically on boot, and a startup guard refuses to run with an insecure config.
**You do the account steps**; everything else is prepared.

**Topology:** backend API on **Fly.io**, frontend on **Vercel**, database on **Supabase**.
They're separate origins — CORS and a build-time `VITE_API_BASE` (already wired) connect them.

### Why Fly and not a serverless host

EchoLens runs investigations in **background threads** and keeps an in-process collector
scheduler. Serverless platforms (Vercel Functions, Lambda, Cloud Run scaled to zero) freeze
or kill the container once the HTTP response is sent, which would abandon a running
investigation mid-loop. Fly runs a real always-on VM, so both survive.

`fly.toml` sets `auto_stop_machines = false` and `min_machines_running = 1` deliberately —
a stopped machine both kills in-flight work and makes the next request pay a cold start,
which is indistinguishable from a broken backend.

---

## What you need

| Thing | Done | Where |
|---|---|---|
| GitHub repo | ✅ | already pushed |
| Fly.io account | ⬜ | <https://fly.io> — hosts the **backend** |
| Vercel account | ⬜ | <https://vercel.com> — hosts the **frontend** |
| Supabase project | ✅ | your existing database |
| OpenAI API key | ✅ | in `backend/.env` |

Install the CLI once: <https://fly.io/docs/flyctl/install/> then `fly auth login`.

---

## Steps

### 1. Backend on Fly

```bash
cd backend
fly launch --no-deploy --copy-config      # claims the app name from fly.toml
```

Set the secrets (these never go in the repo):

```bash
fly secrets set   ECHOLENS_DB_URL="postgresql://...supabase pooler URL..."   OPENAI_API_KEY="sk-..."   JWT_SECRET="$(openssl rand -hex 32)"   CORS_ORIGINS="https://your-app.vercel.app"
```

Optional: `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `SLACK_WEBHOOK_URL`, `SLACK_ACTION_TOKEN`.

```bash
fly deploy
fly status                 # machine should be "started"
curl https://<app>.fly.dev/health
```

`/health` returns `{"db": true, ...}` when Supabase is reachable.

> Pick `primary_region` in `fly.toml` near your Supabase region — every query pays that
> round trip.

### 2. Frontend on Vercel
1. Import the repo at vercel.com.
2. **Root Directory** → `frontend`.
3. **Environment Variables** → `VITE_API_BASE` = `https://<app>.fly.dev`.
   *(Vite inlines env at build time, so set this before the first build.)*

### 3. Let the browser call the API
```bash
cd backend && fly secrets set CORS_ORIGINS="https://your-app.vercel.app"
```
Setting a secret triggers a rolling restart. *(Adding a custom domain later? Append it,
comma-separated.)*

### 3b. Automatic deploys from GitHub

[.github/workflows/deploy.yml](.github/workflows/deploy.yml) deploys on every push to
`main` that touches `backend/`. It needs one secret:

```bash
fly tokens create deploy      # copy the output
```
Add it as **FLY_API_TOKEN** under *Settings → Secrets and variables → Actions*.
Optionally add a repo **variable** `ECHOLENS_API` = `https://<app>.fly.dev` and the
workflow will verify `/health` after each rollout instead of assuming it worked.

### 4. Create your admin login

Pick **one**:

**A. Auto-bootstrap from secrets (easiest).**
```bash
fly secrets set BOOTSTRAP_ADMIN_EMAIL="you@you.com" BOOTSTRAP_ADMIN_PASSWORD="a-strong-password"
```
On the next boot the backend creates that admin — only if no users exist yet. Remove both
afterwards with `fly secrets unset BOOTSTRAP_ADMIN_EMAIL BOOTSTRAP_ADMIN_PASSWORD`.

**B. First-signup bootstrap.** The very first `/auth/signup` becomes the admin; later
signups require one. Note this is **blocked in production** unless no user exists yet.
```bash
curl -X POST https://<app>.fly.dev/auth/signup   -H "Content-Type: application/json"   -d '{"email":"you@you.com","password":"a-strong-password"}'
```

**C. A shell on the machine.**
```bash
fly ssh console -C "python -m echolens.cli createuser you@you.com 'a-strong-password' --role admin"
```

**D. From your own machine.** The DB is shared, so a local checkout can bootstrap it:
```bash
cd backend
.venv/Scripts/python -m echolens.cli createuser you@you.com 'a-strong-password' --role admin
.venv/Scripts/python -m echolens.cli connect play_store com.your.app --product "Your App"
.venv/Scripts/python -m echolens.cli connect github your-org/your-repo --product "Your App"
.venv/Scripts/python -m echolens.cli collect
.venv/Scripts/python -m echolens.cli scan
```

### 5. Log in
Open the Vercel URL and sign in. Done.

---

## Notes & gotchas

- **No cold starts.** The machine stays running, so the first request after an idle period
  is as fast as any other — this is the main reason to be on Fly rather than a free tier
  that sleeps.
- **Auto-deploy:** pushes to `main` deploy the API via GitHub Actions and the frontend via
  Vercel. Watch a rollout with `fly logs`.
- **Scheduled work:** Fly has no built-in cron. [collect.yml](.github/workflows/collect.yml)
  and [brief.yml](.github/workflows/brief.yml) run on GitHub Actions cron (free) and call
  the deployed API. Set the `ECHOLENS_API`, `ECHOLENS_EMAIL` and `ECHOLENS_PASSWORD` repo
  secrets or they fail fast and tell you which is missing.
- **Useful commands:** `fly logs`, `fly status`, `fly ssh console`, `fly secrets list`
  (names only — values are never shown), `fly deploy --remote-only` (no local Docker needed).
- **Investigations survive restarts** — they checkpoint each iteration and resume.
