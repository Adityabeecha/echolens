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
5. Confirm Build Command is `npm run build` and Output Directory is `dist`.
6. Add `VITE_API_BASE` with the Northflank origin and no trailing slash.
7. Deploy and record the canonical Vercel origin.

`frontend/vercel.json` supplies the SPA rewrite so client-side routes resolve to `index.html`.

## 4. Connect frontend and backend

Return to Northflank and set `CORS_ORIGINS` to the exact Vercel origin, including `https://` and excluding a trailing slash. For multiple approved origins, use a comma-separated list. Set `APP_BASE_URL` to the canonical frontend origin when notifications should include deep links.

Redeploy the backend after changing environment variables. Then open the Vercel URL and confirm the login page can load `/auth/config` without a CORS error.

Create the first administrator with one method:

- Temporarily set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`, deploy once, then remove both values.
- Or run `python -m echolens.cli createuser EMAIL PASSWORD --role admin` from a trusted environment connected to the production database.

Do not expose `ECHOLENS_ENV=dev` publicly.

## 5. Configure scheduled workflows

In GitHub Settings, add these Actions secrets:

- `ECHOLENS_API`: Northflank backend origin.
- `ECHOLENS_EMAIL`: reviewer or administrator account used by automation.
- `ECHOLENS_PASSWORD`: password for that account.

Also add an Actions variable named `ECHOLENS_API` with the same backend origin. The secret is used by scheduled jobs; the variable is used by the post-deployment health workflow.

The retained workflows perform:

- `.github/workflows/collect.yml`: collect, scan, and triage every six hours.
- `.github/workflows/brief.yml`: send the weekly brief.
- `.github/workflows/deploy.yml`: verify `/health` after backend changes reach `main`.

Run each scheduled workflow manually once from the Actions tab to validate credentials.

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

`VITE_API_BASE` was missing during the build. Set it to the Northflank origin and redeploy Vercel.

### Northflank starts but health checks fail

Inspect startup logs and verify `ECHOLENS_DB_URL` uses a reachable PostgreSQL pooler URL. Run `python -m echolens.cli preflight` with the production environment to identify insecure or missing settings.

### Scheduled workflows return `401`

Verify `ECHOLENS_EMAIL` and `ECHOLENS_PASSWORD` match an active account and `ECHOLENS_API` points to the backend origin without an extra path.
