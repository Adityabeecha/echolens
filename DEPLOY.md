# Deploying EchoLens (Northflank backend + Vercel frontend + Supabase)

The repo is deploy-ready: [backend/Dockerfile](backend/Dockerfile) builds the API,
[frontend/vercel.json](frontend/vercel.json) configures the frontend, migrations run
automatically on boot, and a startup guard refuses to run with an insecure config.

**Topology:** backend API on **Northflank**, frontend on **Vercel**, database on **Supabase**.
They are separate origins — CORS and a build-time `VITE_API_BASE` (already wired) connect them.

### Why a container host and not serverless

EchoLens runs investigations in **background threads** and keeps an in-process collector
scheduler. Serverless platforms (Vercel Functions, Lambda, Cloud Run scaled to zero) freeze
or kill the container once the HTTP response is sent, which would abandon a running
investigation mid-loop. Northflank runs a real long-lived container, so both survive.

The Dockerfile pins `--workers 1` deliberately: with more than one worker you would get
several schedulers racing on the same database.

---

## What you need

| Thing | Done | Where |
|---|---|---|
| GitHub repo | ✅ | already pushed |
| Northflank account | ⬜ | <https://northflank.com> — sign in with GitHub |
| Vercel account | ⬜ | <https://vercel.com> — hosts the frontend |
| Supabase project | ✅ | your existing database |
| OpenAI API key | ✅ | in `backend/.env` |

---

## Steps

### 1. Backend on Northflank

1. **Create a project** (pick a region near your Supabase region — every query pays that
   round trip).
2. **Add a service → Combined service** (build + deploy from Git).
3. **Repository**: this repo, branch `main`. Turn **on** build-on-push so a push deploys.
4. **Build**:
   - Build type: **Dockerfile**
   - Build context / directory: `/backend`
   - Dockerfile path: `/backend/Dockerfile`
5. **Runtime → Port**: expose **8000**, protocol **HTTP**, and enable **public DNS**.
   That gives you the API URL.
6. **Health check** (so a bad build does not silently take over): HTTP `GET /health` on
   port 8000. It only checks the database, never the LLM or any third-party API, so it
   cannot fail for reasons outside your control.
7. **Environment variables** — add these under the service (mark the secret ones as secrets):

| Key | Value |
|---|---|
| `ECHOLENS_ENV` | `production` |
| `ECHOLENS_DB_URL` | your Supabase **transaction pooler** URL |
| `OPENAI_API_KEY` | `sk-…` |
| `JWT_SECRET` | a long random string — `openssl rand -hex 32` |
| `CORS_ORIGINS` | your Vercel URL (fill in after step 2) |
| `ECHOLENS_MODEL` | `gpt-4o-mini` |
| `ECHOLENS_LOG_JSON` | `1` |
| `GITHUB_TOKEN` | optional — for creating issues |

Deploy, then check `https://<your-service-url>/health`. It returns `{"db": true, …}` when
Supabase is reachable.

> Use the **pooler** connection string, not the direct one. Containers open and close
> connections in a way the direct Postgres endpoint does not like.

### 2. Frontend on Vercel

1. Import the repo at vercel.com.
2. **Root Directory** → `frontend`.
3. **Environment Variables** → `VITE_API_BASE` = your Northflank URL.
   *(Vite inlines env at build time, so set this before the first build.)*

### 3. Let the browser call the API

Back in Northflank, set `CORS_ORIGINS` to your Vercel URL and redeploy. Until this matches,
every request fails in the browser with a CORS error while working fine from curl — which is
a confusing way to lose an afternoon.

*(Adding a custom domain later? Append it, comma-separated.)*

### 4. Create your admin login

Pick **one**:

**A. Auto-bootstrap from env vars (easiest).** Add `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD`. On the next boot the backend creates that admin — only if no
users exist yet. Delete both afterwards.

**B. First-signup bootstrap.** The very first `/auth/signup` becomes the admin; later
signups require one. Note open signup is **blocked in production** once a user exists.
```bash
curl -X POST https://<your-service-url>/auth/signup   -H "Content-Type: application/json"   -d '{"email":"you@you.com","password":"a-strong-password"}'
```

**C. From your own machine.** The database is shared, so a local checkout can bootstrap it:
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

## Scheduled work

Northflank builds on push, but the recurring jobs run on GitHub Actions cron (free):

| Workflow | Does |
|---|---|
| [collect.yml](.github/workflows/collect.yml) | pulls new reviews/issues, then scans **every product** |
| [brief.yml](.github/workflows/brief.yml) | sends the weekly brief |
| [deploy.yml](.github/workflows/deploy.yml) | verifies `/health` serves after a backend push |

They need repo **secrets** `ECHOLENS_API`, `ECHOLENS_EMAIL`, `ECHOLENS_PASSWORD`, and a repo
**variable** `ECHOLENS_API` for the verify workflow. Each fails fast naming what is missing
rather than dying with an unexplained 401.

---

## Notes & gotchas

- **Investigations survive restarts** — they checkpoint every iteration and resume.
- **One worker only.** Do not raise it. Background threads and the scheduler live in the
  process; more workers means duplicate scheduled runs against one database.
- **Reads require auth.** Every data endpoint needs a signed-in user, so an unauthenticated
  `curl` to `/portfolio` returning `401` is correct. Only `/health` is open.
