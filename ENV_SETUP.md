# Configure EchoLens

Copy `backend/.env.example` to `backend/.env`. Keep that file local: it can contain API keys, passwords, signing keys, and webhook secrets.

```powershell
Copy-Item backend\.env.example backend\.env
```

## Required core settings

| Variable | Local default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | none | Secret API key used by investigations. Required when an LLM-backed operation runs. |
| `ECHOLENS_MODEL` | `gpt-4o-mini` | OpenAI chat model used by the investigation agents. |
| `ECHOLENS_DB_URL` | `sqlite:///echolens.db` | SQLAlchemy database URL. Use a PostgreSQL pooler URL in production. |
| `ECHOLENS_ENV` | `dev` | `dev` disables authentication; `staging` and `production` require it. Never publish a `dev` deployment. |

## Database and search

| Variable | Default | Purpose |
|---|---|---|
| `EMBEDDING_BACKEND` | `hash` | `hash` is dependency-free; `sentence-transformers` requires `pip install -e ".[embeddings]"`. |
| `EMBEDDING_DIM` | `256` | Vector dimension for the hash embedding backend. |
| `SEED_ON_START` | `false` | Seeds the synthetic demo corpus when the database is empty. |

For Supabase, use its PostgreSQL pooler connection string rather than the direct database host. Encode special characters in the password as required by a URL.

## Authentication and browser access

| Variable | Default | Purpose |
|---|---|---|
| `JWT_SECRET` | insecure example | Secret used to sign access tokens. Generate a unique production value. |
| `JWT_EXPIRE_MINUTES` | `1440` | Access-token lifetime in minutes. |
| `CORS_ORIGINS` | empty | Comma-separated frontend origins allowed by the API, with scheme and no trailing slash. Required in production. |
| `ALLOW_GUEST` | `false` | Allows unauthenticated read-only viewer access. |
| `GUEST_DEMO_ONLY` | `true` | Restricts guests to products explicitly marked as demos. Keep enabled for public deployments. |
| `GOOGLE_CLIENT_ID` | empty | Enables Google sign-in. This browser client ID is public by design. |
| `GOOGLE_DEFAULT_ROLE` | `reviewer` | Role assigned to Google users unless their email is listed as an admin. Use `viewer` for public demos. |
| `GOOGLE_ADMIN_EMAILS` | empty | Comma-separated Google-account emails that receive the admin role. |
| `BOOTSTRAP_ADMIN_EMAIL` | empty | Creates the first admin at startup when the database has no users. Remove after bootstrap. |
| `BOOTSTRAP_ADMIN_PASSWORD` | empty | Secret password paired with `BOOTSTRAP_ADMIN_EMAIL`. Remove after bootstrap. |

Generate a signing key with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

For Google sign-in, create a Web OAuth client and add the exact frontend origins, such as `http://localhost:5173` and your production Vercel origin, under Authorized JavaScript origins. A client secret is not used by this browser flow.

## Collectors and GitHub integration

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | empty | Raises GitHub API limits, accesses permitted private repositories, and enables configured issue actions. |
| `COLLECTOR_INTERVAL_HOURS` | `6` | Interval used by the in-process collector scheduler. |
| `AUTO_CREATE_ISSUE_ON_APPROVE` | `false` | Creates a GitHub issue when a finding is approved. |
| `GITHUB_DEFAULT_REPO` | empty | Fallback `owner/repository` used when a product has no connected GitHub source. |
| `GITHUB_WEBHOOK_SECRET` | empty | Secret used to verify GitHub webhook signatures for fix tracking. |

Play Store collection requires no credential. Configure sources through the UI or with `python -m echolens.cli connect`.

## Alerts and notifications

| Variable | Default | Purpose |
|---|---|---|
| `APP_BASE_URL` | empty | Public frontend origin used for deep links in notifications and tickets. |
| `ALERTS_ENABLED` | `true` | Enables alert and digest delivery. |
| `ALERT_INSTANT_MIN_SEVERITY` | `0.5` | Severity threshold from `0` to `1` for immediate alerts. |
| `SLACK_WEBHOOK_URL` | empty | Secret Slack incoming-webhook URL for alerts and digests. |
| `SLACK_ACTION_TOKEN` | empty | Shared secret protecting Slack reply-to-act requests. |
| `SMTP_HOST` | empty | SMTP server; leaving it empty disables email delivery. |
| `SMTP_PORT` | `587` | SMTP port. |
| `SMTP_USER` | empty | SMTP username. |
| `SMTP_PASSWORD` | empty | Secret SMTP password. |
| `ALERT_EMAIL_FROM` | empty | Sender address for email alerts. |
| `ALERT_EMAIL_TO` | empty | Recipient address or addresses for email alerts. |

## Logging

| Variable | Default | Purpose |
|---|---|---|
| `ECHOLENS_LOG_JSON` | `1` | Emits structured JSON logs when enabled. |
| `ECHOLENS_LOG_LEVEL` | `INFO` | Application logging level. |

## Frontend build setting

| Variable | Local default | Purpose |
|---|---|---|
| `VITE_API_BASE` | `/api` | Backend public URL embedded into the frontend build. Set it in Vercel to the Northflank URL with no trailing slash. |

Vite reads `VITE_API_BASE` at build time. Changing it requires a new frontend deployment.

## GitHub Actions settings

The scheduled workflows use repository settings rather than `backend/.env`:

| Setting | Kind | Used by |
|---|---|---|
| `ECHOLENS_API` | Actions secret | Scheduled collection and weekly brief. |
| `ECHOLENS_EMAIL` | Actions secret | Account used by scheduled workflows. |
| `ECHOLENS_PASSWORD` | Actions secret | Password used by scheduled workflows. |
| `ECHOLENS_API` | Actions variable | Post-deployment health verification. |

Use the same backend origin for both `ECHOLENS_API` entries. The duplicate name is intentional because GitHub stores secrets and variables separately.

## Recommended production baseline

```dotenv
ECHOLENS_ENV=production
ECHOLENS_DB_URL=postgresql://USER:PASSWORD@POOLER_HOST:6543/postgres
OPENAI_API_KEY=replace-with-secret
JWT_SECRET=replace-with-generated-secret
CORS_ORIGINS=https://your-frontend.vercel.app
APP_BASE_URL=https://your-frontend.vercel.app
ALLOW_GUEST=false
GUEST_DEMO_ONLY=true
ECHOLENS_LOG_JSON=1
ECHOLENS_LOG_LEVEL=INFO
```

Run `python -m echolens.cli preflight` from `backend/` before deploying. It rejects insecure production configuration.
