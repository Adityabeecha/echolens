# Security Policy

## Reporting a vulnerability

Email SECURITY_CONTACT (placeholder, replace with your address). Please do not open a public issue for security problems.

Include:

- a description of the issue and its impact
- steps to reproduce or a proof of concept
- affected endpoint, file or configuration
- the commit or version tested
- your contact details for follow-up

Our goal is to acknowledge reports within a few business days and to share a remediation plan after triage. This is a goal, not a guarantee.

## Supported versions

Only the `main` branch is supported.

## Deployment hardening checklist

Setting names below are defined in `backend/echolens/config.py`.

- [ ] `ECHOLENS_ENV` set explicitly to `production` or `staging`. The API refuses to start if it is unset on a non-SQLite database, because `dev` disables authentication and makes every caller an admin. Never expose `dev` publicly.
- [ ] Strong, unique `JWT_SECRET` (for example `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Startup fails in production/staging with the default value.
- [ ] `CORS_ORIGINS` set to your exact frontend origin(s). Required in production.
- [ ] `GITHUB_WEBHOOK_SECRET` set. Webhooks are refused without it.
- [ ] `SLACK_SIGNING_SECRET` set (preferred). `SLACK_ACTION_TOKEN` is the older fallback.
- [ ] Google sign-in: set `GOOGLE_ALLOWED_DOMAINS` and `GOOGLE_ADMIN_EMAILS`. `GOOGLE_DEFAULT_ROLE` defaults to `viewer`; keep it that way.
- [ ] Do not enable `ALLOW_GUEST` on a workspace holding real customer data unless `GUEST_DEMO_ONLY=true`.
- [ ] Use a dedicated low-privilege account/token for GitHub Actions automation (`GITHUB_TOKEN`, collectors, scheduled workflows).
- [ ] Use Postgres, not SQLite, in production, and keep `OPENAI_API_KEY`, SMTP and database credentials in your host's secret store, never in git.
- [ ] Rotate secrets periodically and after any suspected exposure. Rotating `JWT_SECRET` invalidates existing sessions.
- [ ] Run `echolens preflight` before deploying.

## Authentication model

- JWT bearer tokens (PyJWT, HS256 by default via `JWT_ALGORITHM`); lifetime set by `JWT_EXPIRE_MINUTES` (default 24 hours).
- Roles: `admin` > `reviewer` > `viewer`. The role is read from the database on every request, so changes and removals take effect immediately.
- Passwords are hashed with bcrypt. New accounts (signup, CLI, bootstrap) require at least 10 characters and reject a few very common passwords.
- Google sign-in verifies the ID token server-side. Accounts not on the admin list get `GOOGLE_DEFAULT_ROLE`, and only allowed domains or existing users may sign in.
- Rate limits (slowapi): signup 5/minute, login 10/minute, Google sign-in 20/minute, plus limits on several LLM-backed endpoints.
- Invalid or expired tokens always return 401. Guests (when `ALLOW_GUEST=true`) are read-only viewers.
