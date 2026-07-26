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

## Optional — showing the app to other people

Two independent switches. **Both are off by default**, so nothing changes until you set them.

### `ALLOW_GUEST` — let people use the app without logging in

Set `ALLOW_GUEST=true` and a visitor with no account is admitted as a **viewer**:
they see every screen with real data, and the login page leads with
"Explore the demo" instead of a password box.

What a guest **cannot** do — the server refuses these with a 403, so the UI
hides or disables the controls:

- start an investigation (this is the one that spends your OpenAI credits)
- connect, retry or run a collector
- approve, challenge or queue anything
- create or delete a product, or change budgets

Guests only ever see products marked as **demo** (`GUEST_DEMO_ONLY=true`, the
default). Everything else in your workspace stays invisible to them — it is not
merely hidden in the UI, the API returns 404 for a real product even if a
visitor guesses its id. Mark the product you want to show with `is_demo`, and
your other products stay private on the same deployment.

> This is **not** the same as `ECHOLENS_ENV=dev`. Dev mode admits anonymous
> callers as a full **admin**, which on a public URL would let any visitor
> spend your credits and delete your data. Never use `dev` for a link you
> share; use `ECHOLENS_ENV=production` **plus** `ALLOW_GUEST=true`.

### `GOOGLE_CLIENT_ID` — "Sign in with Google"

The button only appears when this is set, so leaving it blank simply means no
Google option.

1. Go to <https://console.cloud.google.com/apis/credentials>
2. Create a project if you have none (any name)
3. **Configure consent screen** → *External* → fill in app name + your email → Save.
   While it is in "Testing" only accounts you list under **Test users** can sign
   in; click **Publish app** to open it to anyone.
4. **Create credentials** → **OAuth client ID** → *Web application*
5. Under **Authorised JavaScript origins** add the exact origins you serve from:
   - `http://localhost:5173` (local dev)
   - `https://your-app.vercel.app` (your deployed frontend)
   No trailing slash. This must match the address bar exactly or Google refuses.
6. Copy the **Client ID** (`...apps.googleusercontent.com`) into `GOOGLE_CLIENT_ID`.

You do **not** need the client *secret* — the browser flow used here only needs
the id, which is designed to be public.

| Variable | Default | What it does |
|---|---|---|
| `GOOGLE_CLIENT_ID` | *(blank)* | Enables the Google button. Blank = no Google option. |
| `GOOGLE_DEFAULT_ROLE` | `reviewer` | Role a Google user gets. Set to `viewer` to make every Google sign-in read-only too. |
| `GOOGLE_ADMIN_EMAILS` | *(blank)* | Comma-separated emails that get **admin**. Put your own address here. |
| `GUEST_DEMO_ONLY` | `true` | Guests see only products flagged `is_demo`. Set `false` only on a private deployment. |

**Note on cost:** with the default `reviewer`, anyone who signs in with Google
can start investigations, which bills your OpenAI account. If you are sharing
the link widely, set `GOOGLE_DEFAULT_ROLE=viewer` and keep yourself in
`GOOGLE_ADMIN_EMAILS`.

### Recommended setup for a public portfolio demo

```bash
ECHOLENS_ENV=production
ALLOW_GUEST=true
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_ADMIN_EMAILS=b.aditya.741@gmail.com
GOOGLE_DEFAULT_ROLE=viewer      # nobody but you can spend credits
JWT_SECRET=<generated, see above>
CORS_ORIGINS=https://your-app.vercel.app
```

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
