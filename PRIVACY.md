# EchoLens Privacy and Data Handling

EchoLens is self-hosted. Whoever runs a deployment is the data controller. This document describes what the code stores and where it sends data. It is not legal advice.

## What is collected

| Data | Source | Notes |
|---|---|---|
| App store reviews | Google Play Store collector | Review text, ratings and metadata as published (`reviews` table). |
| GitHub issues, releases, discussions | GitHub collector (`GITHUB_TOKEN` optional) | `issues`, `releases` and `feedback_entries` tables. |
| Other feedback | Imported CSV/XLSX files; other v2 sources land in `feedback_entries` | Whatever columns you import are stored as feedback text and metadata. |
| User accounts | Signup, CLI, bootstrap admin, Google sign-in | Email, role (`admin`/`reviewer`/`viewer`), and either a bcrypt password hash or the marker `!sso-google` for Google accounts. Also the last product the user viewed. No Google profile data beyond the verified email is stored (`users` table). |
| Investigation records | Investigations | Hypotheses, evidence snippets, trace steps (`content_json`), findings, recommendations, reviewer feedback. |
| Comments and mentions | Team discussion on cases | Free text written by users. |
| LLM call ledger | Every LLM call | Agent name, model, tokens in/out, cost, latency, and product/investigation id. No prompt or response bodies are stored in `llm_calls` (verified in `db/models.py`). Note that trace steps and evidence may contain excerpts of reviews. |

TODO: confirm whether `trace_steps.content_json` ever stores full prompt text; the model comments describe it as step content, not raw prompts.

## Where it is stored

In the database named by `ECHOLENS_DB_URL`: SQLite for local development, Postgres in production (Supabase in the documented deployment, see `DEPLOY.md`). EchoLens does not add its own encryption at rest. Rely on your database provider for that. TODO: confirm provider region and encryption settings for your Supabase project.

## What is sent to OpenAI

Prompts sent to the OpenAI API include review and feedback text snippets, finding context and your questions. This happens during:

- investigations (planning, evidence updates, conclusions)
- chat / Ask
- triage of anomalies
- theme discovery
- recommendations

Handling of API data by OpenAI is governed by OpenAI's API data-usage policy: https://openai.com/policies/. EchoLens makes no further claims about OpenAI retention or training. Do not import data you are not allowed to share with OpenAI.

## Delivery integrations (only when configured)

- Slack: alerts and digests posted to `SLACK_WEBHOOK_URL`; Slack button clicks return to the API.
- Email: alerts sent through your SMTP server if `SMTP_HOST` is set.
- GitHub: issues created in a connected repo or `GITHUB_DEFAULT_REPO` when a finding is approved (automatically only if `AUTO_CREATE_ISSUE_ON_APPROVE=true`). GitHub webhooks inbound require `GITHUB_WEBHOOK_SECRET`.

These carry finding summaries and deep links (`APP_BASE_URL`) to the destination you configured. If unset, nothing is sent.

## Retention and deletion

There is no automatic expiry. Data is kept until a product is deleted. `DELETE /products/{id}` (admin only, requires typing the exact product name) removes:

- the product's corpus: reviews, issues, posts, releases and feedback entries (matched by product name)
- investigations with their hypotheses, evidence, trace steps, findings, recommendations, reviewer feedback and LLM ledger rows linked to those investigations or tagged with the product (chat, triage, theme discovery)
- anomalies and triage decisions, queued investigations, fix watches, collector state, knowledge-graph edges, comments, mentions and review requests
- the product row itself (and clears it as "last active product" on users)

Not removed by product deletion:

- user accounts (`users`) and `settings` rows
- copies already sent to Slack, email, GitHub, or OpenAI, and database backups

## Requesting deletion or export

Contact PRIVACY_CONTACT (placeholder, replace with your address). The operator can delete a product through the API/UI, delete user rows directly in the database, and export data with database tooling. TODO: confirm whether a built-in export endpoint covers all data.

## Guest / demo mode

With `ALLOW_GUEST=true`, visitors without a token get a read-only `viewer` role. When `GUEST_DEMO_ONLY=true` (the default), guests see only products flagged `is_demo`. Guests cannot start investigations, connect sources or delete anything. Do not enable guest mode on a workspace with real customer data unless `GUEST_DEMO_ONLY=true`.
