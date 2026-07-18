# EchoLens — `.env` setup guide

Copy `backend/.env.example` → `backend/.env` and fill in. **Only two lines are truly required** to run; everything else is optional (needed only for specific v1.0 features). Nothing here is billed except the OpenAI key.

---

## Required to run at all

### `OPENAI_API_KEY` — the LLM (you already have this)
- Where: <https://platform.openai.com/api-keys> → **Create new secret key**.
- Needs: a payment method on the account (Settings → Billing). Investigations cost ~$0.005–0.01 each; budgets cap it.
- Looks like: `sk-proj-...`

### `ECHOLENS_DB_URL` — the database (you already have this)
- Local dev: `sqlite:///echolens.db` (no signup, a file).
- Your Supabase: the **Transaction pooler** URL from Supabase → Project → Settings → Database → Connection string → *Transaction pooler* (`...pooler.supabase.com:6543`). The direct `db.*.supabase.co` host is IPv6-only and won't connect from most networks.

---

## Optional — real data collectors (v1.0)

You can run everything on the synthetic "Lumo" data with **none** of these. Fill them in only when you connect a real source.

### `GITHUB_TOKEN` — for the GitHub collector
Lets you pull issues/releases at 5,000 req/hr instead of 60 (and read private repos you own).
1. GitHub → click your avatar → **Settings**
2. **Developer settings** (bottom of left sidebar) → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
3. Fill in: **Token name** (e.g. "echolens"), **Expiration** (90 days is fine), **Repository access** = *Public repositories (read-only)* if you only track public apps
4. No account/company details needed — just the token name
5. Click **Generate token**, copy the `github_pat_...` value
- For public repos you can even leave this blank; it just gets rate-limited sooner.

### Reddit — **removed** (no longer a live source)
Reddit ended free API access in 2026, so EchoLens no longer collects from Reddit. There are no Reddit env vars to fill. (The `search_reddit` tool still works over any Reddit posts already in the corpus, e.g. from a CSV/import, but there is no live collector.)

### Play Store — **no credentials needed**
The Play Store collector uses a public scraper. Just `connect play_store com.your.app`.

---

## Optional — only if you deploy with auth on (`ECHOLENS_ENV=production`)

### `JWT_SECRET` — you generate this yourself (not from any website)
It's just a long random string used to sign login tokens. Generate one:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Paste the output as `JWT_SECRET`. In `dev` mode (the default) auth is off and this is ignored.

---

## Optional — have sensible defaults (leave as-is unless you know you want to change)

| Variable | Default | What it does |
|---|---|---|
| `ECHOLENS_MODEL` | `gpt-4o-mini` | which OpenAI model the agents use |
| `ECHOLENS_ENV` | `dev` | `dev` = no auth; `staging`/`production` = login required |
| `COLLECTOR_INTERVAL_HOURS` | `6` | how often the scheduler collects |
| `EMBEDDING_BACKEND` | `hash` | `hash` = free/zero-dep; `sentence-transformers` = better semantics (heavy install) |
| `EMBEDDING_DIM` | `256` | embedding vector size for the hash backend |
| `ECHOLENS_LOG_JSON` | `1` | `1` = JSON logs, `0` = human-readable |

---

## TL;DR — minimum to keep going right now
You already have `OPENAI_API_KEY` and the Supabase URL. **You don't need to fill in anything else** unless you want to:
- pull a **real GitHub repo** → get a `GITHUB_TOKEN` (or leave blank and accept rate limits),
- **deploy with logins on** → generate a `JWT_SECRET`.

Play Store needs nothing. Reddit is no longer supported (free API ended 2026).
