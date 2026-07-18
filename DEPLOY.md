# Deploying EchoLens to production (Render backend + Vercel frontend + Supabase)

The repo is deploy-ready: [render.yaml](render.yaml) defines the backend, [frontend/vercel.json](frontend/vercel.json) configures the frontend, migrations run automatically on boot, and a startup guard refuses to run with an insecure config. **You do the dashboard steps** (they need your accounts); everything else is prepared.

**Topology:** backend API on **Render**, frontend on **Vercel**, database on **Supabase**. They're separate origins — CORS and a build-time `VITE_API_BASE` (already wired) connect them.

---

## What you need before you start

| Item | You have it? | Where to get it |
|---|---|---|
| GitHub repo | ✅ pushed | this repo |
| Render account | ⬜ | <https://render.com> (free) — sign in with GitHub — hosts the **backend** |
| Vercel account | ⬜ | <https://vercel.com> (free) — sign in with GitHub — hosts the **frontend** |
| OpenAI API key | ✅ | your existing key |
| Supabase DB URL | ✅ | Supabase → Settings → Database → **Transaction pooler** connection string |
| JWT secret | ⬜ generate | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| GitHub token | optional | only for connecting a real GitHub repo as a source |

A freshly generated secret you can use now:
```
JWT_SECRET = 3TeGcNmu1bS7AQ4KJS08RjMESliRktb1IkCLhPBk1oxumNH2OVLChPwaCAGwNe8V
```
(Generate your own if you prefer — anything from the command above works.)

---

## Steps

### 1. Backend on Render
1. In Render: **New +** → **Blueprint** → select this GitHub repo. Render reads `render.yaml` and creates **echolens-api** (Docker backend).
2. Set its secrets (**echolens-api → Environment**):

| Key | Value |
|---|---|
| `ECHOLENS_DB_URL` | your Supabase transaction-pooler URL |
| `OPENAI_API_KEY` | your OpenAI key |
| `JWT_SECRET` | the generated secret (or let Render's "Generate" fill it) |
| `CORS_ORIGINS` | *(fill in step 3, once you have the Vercel URL)* |

`ECHOLENS_ENV=production` and `ECHOLENS_MODEL=gpt-4o-mini` are already set by the blueprint.
3. Wait for it to go live and **copy the API URL** (e.g. `https://echolens-api.onrender.com`). Check `https://<that>/health`.

### 2. Frontend on Vercel
1. In Vercel: **Add New… → Project** → import this GitHub repo.
2. **Root Directory**: set to **`frontend`** (important — the app isn't at the repo root). Vercel auto-detects Vite from `frontend/vercel.json`.
3. **Environment Variables**: add `VITE_API_BASE` = your Render API URL from step 1 (e.g. `https://echolens-api.onrender.com`). *(Vite inlines env at build time, so this must be set before the build.)*
4. **Deploy**. Copy the resulting URL (e.g. `https://echolens.vercel.app`).

### 3. Connect them (CORS)
Back on **echolens-api → Environment**, set `CORS_ORIGINS` = your Vercel URL (e.g. `https://echolens.vercel.app`) and save — Render auto-redeploys. Now the browser is allowed to call the API.

*(If you later add a custom domain on Vercel, add it to `CORS_ORIGINS` too, comma-separated.)*

### 4. Seed data + create your admin login
Once the backend is live, open **echolens-api → Shell** (Render) and run:
```bash
python -m echolens.cli preflight                       # should print "Ready to deploy"
python -m echolens.cli seed                            # synthetic Lumo demo data (optional)
python -m echolens.cli createuser you@you.com 'a-strong-password' --role admin
```
Or connect a real app instead of seeding:
```bash
python -m echolens.cli connect play_store com.your.app --product "Your App"
python -m echolens.cli connect github your-org/your-repo --product "Your App"
python -m echolens.cli collect
python -m echolens.cli embed        # turns on semantic search
python -m echolens.cli scan
```

### 5. Log in
Open the Vercel URL, log in with the admin you created. Done.

---

## Notes & gotchas

- **Frontend is always fast** on Vercel (static CDN). Only the **Render backend** free tier cold-starts after ~15 min idle (~30s to wake); the first request after idle is slow, then fine. Investigations survive restarts (they checkpoint and resume). For always-on backend, bump echolens-api to a paid instance.
- **Auto-deploy:** both hosts redeploy on every push to `main` — Render rebuilds the API, Vercel rebuilds the frontend.
- **Scheduled collection:** Render's cron is paid. On free tier, either click "collect" manually, or add a **GitHub Actions** workflow that hits `POST /collectors/run` on a schedule (free). Ask me and I'll add the workflow.
- **Secrets never live in git** — `.gitignore` excludes `backend/.env`. Set backend secrets in the Render dashboard, and `VITE_API_BASE` in the Vercel dashboard.
- **Auth is ON in production** (`ECHOLENS_ENV=production`): every mutating endpoint needs a bearer token; roles are admin > reviewer > viewer.
- **`preflight`** (`python -m echolens.cli preflight`) is your pre-deploy sanity check — it refuses an insecure JWT secret, missing CORS, or SQLite in prod. The API itself also refuses to boot if misconfigured.
- **Semantic search** uses in-Python cosine over stored embeddings — no pgvector extension needed. Fine to thousands of rows; revisit for millions.
