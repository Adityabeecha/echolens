# Deploying EchoLens to production (Render + Supabase)

The repo is deploy-ready: [render.yaml](render.yaml) defines both services, migrations run automatically on boot, and a startup guard refuses to run with an insecure config. **You do the Render dashboard steps** (they need your account); everything else is prepared.

---

## What you need before you start

| Item | You have it? | Where to get it |
|---|---|---|
| GitHub repo | ✅ pushed | this repo |
| Render account | ⬜ | <https://render.com> (free) — sign in with GitHub |
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

### 1. Create the services from the blueprint
1. In Render: **New +** → **Blueprint**.
2. Select this GitHub repo. Render reads `render.yaml` and proposes two services: **echolens-api** (Docker backend) and **echolens-web** (static frontend).
3. Click **Apply**. Both are created; they'll fail the first build until env vars are set — that's expected.

### 2. Set the backend secrets (echolens-api → Environment)
| Key | Value |
|---|---|
| `ECHOLENS_DB_URL` | your Supabase transaction-pooler URL |
| `OPENAI_API_KEY` | your OpenAI key |
| `JWT_SECRET` | the generated secret (or let Render's "Generate" fill it) |
| `CORS_ORIGINS` | *(fill in step 4)* |

`ECHOLENS_ENV=production` and `ECHOLENS_MODEL=gpt-4o-mini` are already set by the blueprint.

### 3. Deploy the frontend and note its URL
`echolens-web` builds automatically and gets a URL like `https://echolens-web.onrender.com`. Copy it.

### 4. Wire the two together
1. **echolens-web → Environment**: set `VITE_API_BASE` = the backend URL (e.g. `https://echolens-api.onrender.com`). Trigger a redeploy (Vite inlines env at build time).
2. **echolens-api → Environment**: set `CORS_ORIGINS` = the frontend URL (e.g. `https://echolens-web.onrender.com`). Save (auto-redeploys).

### 5. Seed data + create your admin login
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

### 6. Log in
Open the frontend URL, log in with the admin you created. Done.

---

## Notes & gotchas

- **Free tier cold starts:** the backend spins down after ~15 min idle and takes ~30s to wake. Investigations survive restarts (they checkpoint and resume). For always-on, bump echolens-api to a paid instance.
- **Scheduled collection:** Render's cron is paid. On free tier, either click "collect" manually, or add a **GitHub Actions** workflow that hits `POST /collectors/run` on a schedule (free). Ask me and I'll add the workflow.
- **Secrets never live in git** — `.gitignore` excludes `backend/.env`. Set them only in the Render dashboard.
- **Auth is ON in production** (`ECHOLENS_ENV=production`): every mutating endpoint needs a bearer token; roles are admin > reviewer > viewer.
- **`preflight`** (`python -m echolens.cli preflight`) is your pre-deploy sanity check — it refuses an insecure JWT secret, missing CORS, or SQLite in prod. The API itself also refuses to boot if misconfigured.
- **Semantic search** uses in-Python cosine over stored embeddings — no pgvector extension needed. Fine to thousands of rows; revisit for millions.
