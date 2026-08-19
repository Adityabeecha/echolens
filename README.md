# EchoLens

EchoLens is a product-feedback investigation workspace. It collects signals from app-store reviews and GitHub, detects meaningful changes, investigates likely causes, and keeps every conclusion connected to retrievable evidence for human review.

## What EchoLens does

- Collects Play Store feedback and GitHub issues, reactions, and releases.
- Detects anomalies across product-feedback streams.
- Runs budgeted investigations that test hypotheses against evidence.
- Produces findings, recommendations, and follow-up work without hiding uncertainty.
- Supports admin, reviewer, viewer, Google sign-in, and read-only guest access.
- Tracks whether shipped fixes improve the underlying feedback.

## How it works

The FastAPI backend owns collection, detection, investigations, authentication, persistence, scheduled work, and the API. The React frontend provides the operational workspace for monitoring products, reviewing cases and evidence, managing sources, and following fixes. SQLite works for local development; PostgreSQL is recommended for production.

## Repository structure

```text
backend/             Python API, investigation engine, collectors, database, and tests
frontend/            React/Vite application and focused frontend verification scripts
.github/workflows/   Scheduled collection, weekly briefing, and deployment verification
deploy/              Nginx configuration for the Docker Compose deployment
```

## Quick start

Requirements: Python 3.11+, Node.js 20.19+ or 22.12+, and an OpenAI API key.

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` in `backend/.env`, then start the API:

```powershell
python -m echolens.cli seed
python -m echolens.cli serve --reload
```

The API runs at `http://127.0.0.1:8000`. See [ENV_SETUP.md](ENV_SETUP.md) for every setting and safe production defaults.

### Frontend

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the local backend.

## Run the tests

```powershell
cd backend
.venv\Scripts\python -m pytest -q

cd ..\frontend
node scripts\verify-responsive-contract.mjs
node --experimental-strip-types scripts\verify-sidebar-state.mjs
node --experimental-strip-types scripts\verify-theme-mode.mjs
npm run build
```

`frontend/scripts/verify-login-overflow.mjs` is a browser regression test. It expects a local Vite server and a Chromium browser exposed through the Chrome DevTools Protocol; its defaults are documented at the top of the script.

## Deploy

The recommended production topology is PostgreSQL/Supabase, a long-running Northflank backend, and a Vercel frontend. Follow [DEPLOY.md](DEPLOY.md). For a single-machine deployment, provide `OPENAI_API_KEY` and `JWT_SECRET`, then run `docker compose up --build`.

## Security

- Never commit `.env`, API keys, OAuth credentials, webhook secrets, or database passwords.
- Never expose `ECHOLENS_ENV=dev` publicly; development mode grants anonymous admin access.
- Use a strong `JWT_SECRET`, exact `CORS_ORIGINS`, and `GUEST_DEMO_ONLY=true` for public demos.
- Treat findings as evidence-backed decision support and retain human review for consequential actions.
