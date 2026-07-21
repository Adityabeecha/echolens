# EchoLens — Future Roadmap

> **Where we are:** M1–M3 complete. The core loop works end-to-end — synthetic data → anomaly detection → orchestrator triage → LangGraph investigator → recommender → human review, with a live-streaming React UI. Everything runs on SQLite with a single OpenAI provider and the fictional "Lumo" dataset.
>
> **Where we're going:** From a compelling demo to a production-grade feedback intelligence platform that ingests real data, learns from its own investigations, and scales across teams.

---

## v1.0 — Live Data & Production Hardening

**Theme:** _"Stop demoing synthetic data. Investigate real products."_

The system proves its value on synthetic data — now make it work against the messy real world.

### Real Collectors
- **Play Store collector** — `google-play-scraper` integration with rate-limit handling, incremental fetches (last-seen watermark), and deduplication by `ext_id`. Track any public Android app by package name.
- **GitHub collector** — REST API with token auth, paginated issue/PR ingestion, label and reaction extraction. Map repos to products.
- ~~**Reddit collector**~~ — **dropped.** Reddit ended free API access in 2026, so there is no viable free live Reddit source. The `search_reddit` tool and `Post` corpus remain (fillable via CSV/import later), but no collector ships.
- **Collector scheduler** — APScheduler running collectors on configurable cron intervals (default: every 6 hours). Health checks per collector with failure alerts.

### Semantic Search (pgvector)
- Migrate from SQLite keyword/LIKE search to **Postgres + pgvector**. Generate embeddings on ingestion using `sentence-transformers` (local, $0).
- Upgrade `search_reviews`, `search_reddit`, `search_github_issues` tools to use cosine similarity with a keyword fallback.
- This lets the investigator find thematically related feedback even when users don't use the exact same words (e.g., "phone gets hot" ↔ "battery drain").

### Auth & Multi-User
- JWT-based authentication (FastAPI + `python-jose`). Email/password signup, no OAuth yet.
- Role-based access: **Admin** (full control), **Reviewer** (approve/challenge findings), **Viewer** (read-only dashboards).
- Audit log on every finding review action (who approved, when, with what note).

### Deployment
- **Docker Compose** setup: backend + Postgres + Redis (for scheduler) + Nginx reverse proxy.
- Container deploy on Northflank from `backend/Dockerfile` (shipped).
- Environment-based config: dev (SQLite, no auth) → staging → production.

### Hardening
- Structured logging with `structlog` (JSON logs, correlation IDs per investigation).
- Retry logic on LLM calls with exponential backoff (currently: one retry → FAIL).
- Graceful investigation recovery: if the server crashes mid-investigation, resume from the last persisted trace step on restart.
- Rate-limit the API (`slowapi`) — especially `/investigations` POST to prevent runaway cost.

---

## v2.0 — Smarter Investigations

**Theme:** _"The agent gets better at its job."_

The investigator loop works, but it's only as smart as one LLM call per step. v2 makes it genuinely more capable.

### Multi-Agent Investigation Teams
- **Specialist sub-agents** for complex cases: a "Sentiment Analyst" that breaks down emotional tone across review cohorts, a "Timeline Reconstructor" that builds a precise event timeline from scattered evidence.
- The main investigator can **delegate** to specialists when a hypothesis needs a type of analysis it can't do with basic search tools.
- Each specialist is a single-pass LLM with its own prompt and output schema — not a full loop. Keeps the architecture honest.

### New Tool: Trend Analysis
- `analyze_trend` — Takes a metric (e.g., "battery mentions") and produces a statistical decomposition: baseline, changepoint detection (PELT algorithm), seasonality, and outlier windows.
- Gives the investigator quantitative ammunition beyond z-scores. "Battery complaints changed on day X with 94% confidence" is stronger than "z=2.3 vs baseline."

### New Tool: User Cohort Comparison
- `compare_cohorts` — Segment reviews by version, OS, device, or geography and compare sentiment / complaint rates between cohorts.
- Enables the investigator to prove version-specific causation: "v3.2 users complain about battery 4x more than v3.1 users on the same OS."

### Cross-Investigation Memory
- When the investigator starts a new case, it gets a digest of **past findings** on the same product/theme. If we already proved that background sync causes battery drain, the agent should know that and check whether a new battery spike is related or distinct.
- Stored as a lightweight "investigation knowledge base" — a summary table linking products → confirmed causes → dates.

### Improved Hypothesis Reasoning
- **Bayesian confidence updates**: Instead of the LLM just picking a new confidence number, compute a prior × likelihood update from the evidence. The LLM proposes the likelihood ("how strongly does this evidence support/contradict?"), and the math enforces consistency.
- **Hypothesis dependency tracking**: H2 depends on H1 being false → rejecting H1 should auto-boost H2. Currently this is implicit in the LLM's judgment; make it explicit in the state machine.

### Adaptive Budgets
- The orchestrator assigns budgets based on anomaly complexity, not just severity. A simple single-source spike gets "quick"; a multi-signal, multi-source anomaly gets "deep" automatically.
- **Budget extension requests**: If the investigator is at 70% confidence with 1 iteration left, it can request a one-time budget extension (logged, capped, requires orchestrator approval in code).

---

## v3.0 — Proactive Operations & Observability

**Theme:** _"The system watches while you sleep."_

### Autonomous Pipeline
- **Scheduled full-pipeline runs** — Cron trigger (APScheduler): collect → detect → orchestrator triage → investigate → recommend, end-to-end without human initiation. PMs wake up to findings, not raw anomaly alerts.
- **Per-product cadence** — New `product_config` table storing investigation schedule (hourly/daily/weekly), default budget tier, and source bindings. The orchestrator checks this before spawning investigations to avoid duplicate runs on the same anomaly window.

### Notification System
- **Email digest** — Daily/weekly HTML summary of: new anomalies, completed investigations, findings awaiting review. `jinja2` templates + transactional email (Resend/SendGrid). Per-user preferences in `notification_preferences`.
- **Slack integration** — Post finding summaries to a channel via incoming webhook. Slash commands: `/echolens status`, `/echolens investigate <topic>`. Lightweight `integrations/slack.py`.
- **Webhook system** — Fire HTTP callbacks on events (`anomaly.detected`, `investigation.resolved`, `finding.approved`). `webhooks` table with URL + secret + event filter. Enables Jira/Linear/PagerDuty without native integrations.

### Product Health Dashboard
- **New React screen** — Per-product aggregate view: anomaly frequency sparkline, mean time to resolution, investigation success rate, top 5 recurring complaint themes (from cross-investigation memory).
- **Trend charts** — Recharts-based: daily negative review rate, theme prevalence, investigation count/week, cost/investigation. Endpoint: `GET /dashboard/trends?product=X&period=30d`.
- **Extended cost analytics** — Per-investigation breakdown (investigator vs orchestrator vs recommender), per-model spend, projected monthly cost at current rate. Aggregated from `llm_calls`.

### Investigation Sharing & Export
- **Public share links** — `POST /findings/{id}/share` → short-lived token (72h). `GET /shared/{token}` serves read-only finding view, no account required.
- **Investigation replay** — `?replay=true` mode on Investigation screen: steps play back at 1x/2x/5x speed from persisted `trace_steps`.
- **PDF/Markdown export** — `POST /findings/{id}/export?format=pdf|md`. Finding prose + evidence table + recommendations + confidence timeline.

### Exit criteria
- Full pipeline runs autonomously on schedule; a PM gets an email with a finding they didn't trigger.
- Product health dashboard renders real data with trend charts.
- A finding is shared via public link and exported as PDF.

---

## v4.0 — Evidence Depth & Source Expansion

**Theme:** _"More sources, smarter evidence, deeper truth."_

### New Data Sources
- **App Store (iOS)** — `collectors/app_store.py` via `app_store_scraper` or App Store Connect API. Unified under `source` field on `reviews`.
- **Custom CSV/JSON upload** — `POST /sources/upload`: file + column mapping (text, date, rating, version). Ingested as `source="upload"`. No rigid schema.
- **Hacker News** — `collectors/hackernews.py`: Algolia HN API for product mentions. Ingested as `posts` with `source="hackernews"`.

### Evidence Quality & Reliability
- **Source quality scoring** — Not all reviews are equal. Score evidence items by: verified purchase flag, review length, reviewer history (repeat vs. one-time), helpfulness votes. Store as `quality_score` on `evidence`. The investigator's `update` node weights confidence adjustments by evidence quality — a 500-word detailed bug report moves confidence more than a one-line rant.
- **Evidence freshness decay** — Evidence ages. A review from 6 months ago carries less weight than one from yesterday. Implement temporal decay: `relevance = quality_score × decay(days_old)`. The `update` node uses this when revising hypothesis confidence.
- **Duplicate evidence detection** — Before adding an `EvidenceItem`, check semantic similarity against existing evidence for the same investigation. If cosine similarity > 0.9, merge rather than append. Prevents the investigator from inflating confidence by re-finding the same complaint in slightly different words.

### Cross-Source Correlation Engine
- **Automatic correlation** — When anomaly events fire within a 72-hour window across multiple sources (reviews + GitHub + HN) with overlapping themes (embedding similarity of descriptions > threshold), auto-merge into a single `correlated_anomaly` event. The orchestrator treats this as signal for `deep` budget tier.
- **Evidence graph** — Instead of flat evidence lists, build a graph linking evidence items by corroboration, contradiction, and temporal order. New `evidence_links` table: `(evidence_id_a, evidence_id_b, relation, strength)`. Visualized in the UI as an interactive network diagram on the Finding Review screen. The investigator traverses the graph to identify evidence gaps.

### Theme Taxonomy
- **Auto-built complaint hierarchy** — After each investigation, extract themes and organize into a hierarchical taxonomy: `Performance → Battery → Background Battery Drain`. Stored in `theme_taxonomy` (id, parent_id, label, product_id). The investigator uses the taxonomy to formulate more precise hypotheses (not just "battery" but specifically "background battery drain during sync").
- **Theme merging** — When two themes are semantically equivalent (cosine > 0.85), prompt for merge. Maintains a clean, non-redundant theme space over time.

### Competitor Monitoring
- **Competitor product tracking** — Ingest a competitor's Play Store / App Store reviews alongside your own. Tag with `product_id` to keep them separate.
- **Competitive insight generation** — When the competitor's users complain about something your product handles well (or vice versa), surface it as a `competitive_insight` event. Deterministic: compare theme prevalence rates across products, flag significant divergences.

### Exit criteria
- At least 4 data sources are live and producing evidence.
- An investigation uses evidence quality scores and a low-quality review demonstrably moves confidence less than a high-quality one.
- Two anomaly events from different sources are auto-correlated into one.
- The theme taxonomy has at least 3 levels of depth for one product.

---

## v5.0 — Team Collaboration & Enterprise Readiness

**Theme:** _"EchoLens for the whole org, not just one PM."_

### Multi-Workspace Architecture
- **Workspaces** — `workspaces` table. Every table gets `workspace_id` FK. Full data isolation. Current setup becomes the "default" workspace on migration.
- **Workspace settings** — Per-workspace: LLM provider, budget tier overrides, collector schedules, notification preferences, default investigation templates.
- **Workspace switching** — JWT includes `workspace_id`. React nav bar gets a workspace selector.

### Collaboration
- **Finding comments** — `finding_comments` table. Threaded discussion on any finding. PMs and engineers debate root causes before approving.
- **@mentions & assignments** — `finding_assignments` table. Assign findings to team members. Mentioned users get notified (email/Slack).
- **Activity feed** — `GET /workspace/activity`. Real-time feed: investigations started, findings approved/challenged, comments posted. New "Activity" tab on Case Feed. Backed by `activity_log`.
- **Mid-investigation handoff** — `POST /investigations/{id}/context`: inject a context note into the agent's next `plan` step while it's still running. Extends the existing challenge-reopen pattern to live investigations.

### Custom Playbooks & Tools
- **Investigation templates** — `investigation_templates` table. Reusable playbooks injected into the investigator's initial prompt. "When you see a rating drop, always check: releases, OS updates, competitor changes."
- **Custom tools** — `custom_tools` table. Register external HTTP endpoints the investigator can call. Name, description, URL, auth header, input schema, output mapping. Dynamically loaded by `tools/registry.py`. Example: internal A/B test API, feature-flag service, crash analytics.

### Enterprise Access
- **SSO/SAML** — Okta / Azure AD via `authlib`. SSO exchanges SAML assertion for local JWT. Per-workspace config.
- **Data retention** — Auto-delete raw review text after N days (configurable per workspace), keeping only cited evidence snippets. Scheduled `retention_cleanup` job. Audit-logged.
- **Multi-step approval** — High-severity findings (confidence ≥ 0.9 + high impact) require two-step approval: reviewer → manager. `review_feedback` gains a `step` field; finding status flows `draft → reviewed → approved`.

### Exit criteria
- Two workspaces operate simultaneously with fully isolated data.
- A finding gets threaded comments and is assigned to a team member who resolves it.
- A custom HTTP tool is called by the investigator during a live investigation.
- SSO login works with at least one provider.

---

## v6.0 — Closed-Loop Actions & Self-Learning

**Theme:** _"The system doesn't just find problems — it helps fix them and gets smarter doing it."_

### Closed-Loop Action Engine
- **Jira / Linear ticket creation** — `integrations/ticketing.py`. Approved finding → auto-create ticket with root cause, evidence links, recommended actions, severity mapping, link back to finding. OAuth2 per workspace. Human confirms with one click.
- **App Store response drafting** — Recommender gains `review_responses[]` output: personalized drafts for the N worst-affected reviews, acknowledging the issue and noting the fix. Human approves before posting.
- **Release note suggestions** — When a linked ticket is marked "done" (tracked via Jira/Linear webhook), draft a "what we fixed" note citing original complaints. Stored in `release_drafts`.

### Outcome Tracking
- **Fix verification** — After a linked ticket resolves, set a 14-day monitoring window. Re-run detector on the same metric. Anomaly resolves → `outcome: confirmed_fix`. Persists → `outcome: unresolved`, flag for re-investigation. `outcome_tracking` table.
- **Root cause pattern library** — As outcomes accumulate, build a curated, editable library of proven root cause patterns: `(trigger, root_cause, fix, success_rate)`. Example: `("battery complaints spike after release", "background sync enabled by default", "make sync opt-in", 87%)`. When a new anomaly matches a known pattern, the investigator starts from there — not from scratch. Distinct from cross-investigation memory: memory is raw recall, patterns are validated knowledge.
- **Investigation cost prediction** — Before starting, estimate cost from anomaly complexity and historical data. "This looks like a 12-iteration, ~$0.60 investigation." Let PMs make informed budget tier decisions.

### Self-Improvement Loop
- **Strategy effectiveness** — Track which tool-call sequences and hypothesis structures lead to `confirmed_fix` vs `unresolved`. `strategy_scores` derived from `trace_steps` + `outcome_tracking`. Surface top strategies in a "Meta-analytics" view.
- **Confidence calibration** — Over N investigations: "When we say 0.85 confidence, are findings actually correct 85% of the time?" Calibration curve plotted. Systematic overconfidence → inject calibration note into the investigator's prompt.
- **Prompt evolution** — Based on strategy scores, regenerate the system prompt to emphasize successful patterns. Versioned in `prompt_versions` with A/B metrics. Always human-approved.
- **Human review feedback loop** — When a PM challenges a finding, track WHY (wrong root cause? missing evidence? wrong severity?) via structured challenge reasons. Aggregate challenge patterns to identify the investigator's weak spots (e.g., "it frequently misidentifies OS updates as root causes") and inject corrective guidance into prompts.

### Advanced Detection
- **Sentiment shift detection** — Beyond volume spikes: compute average sentiment embedding per day. When the centroid shifts significantly (cosine distance > threshold) even with flat volume, fire `type: sentiment_shift` anomaly. Catches "users went from annoyed to furious."
- **Anomaly forecasting** — Seasonal decomposition + linear trend on historical `anomaly_events`. Predict next spike likelihood. Display on dashboard as "risk window" indicator.

### Exit criteria
- An approved finding auto-creates a Jira ticket with evidence and actions.
- After a fix ships, the system detects resolution and marks `confirmed_fix`.
- The root cause pattern library has ≥ 5 validated patterns and the investigator uses one to shortcut an investigation.
- Calibration curve is available for ≥ 20 investigations.

---

## v7.0 — Conversational Intelligence & Predictive Analytics

**Theme:** _"Ask EchoLens anything. It answers from what it knows, investigates what it doesn't."_

### Conversational Interface
- **Chat with EchoLens** — New React screen: chat interface backed by RAG over the investigation knowledge base. `POST /chat` accepts natural language. Backend retrieves relevant findings, evidence, and trace steps via semantic search + cross-investigation memory, then answers with `[finding_id]` citations in a single LLM call. "What's the biggest unresolved complaint about our Android app?"
- **Investigation by question** — "Why did our rating drop last Tuesday?" → detect investigative intent, auto-create `anomaly_event` with inferred date range, kick off investigation. Trace streams into the chat window.
- **Finding follow-up Q&A** — "Was battery drain also happening on iOS?" → identify the relevant finding, run targeted tool calls (`compare_cohorts` by OS), append results as a finding addendum. No full re-investigation — focused evidence retrieval + single LLM synthesis pass.
- **Conversational context** — Multi-turn chat with memory. "What about last month?" follows up on the previous answer. Chat history stored in `chat_sessions` with `workspace_id` scoping.

### Predictive Product Intelligence
- **Theme lifecycle tracking** — Track complaint themes through: emergence → peak → resolution (or `chronic` if unresolved > 60 days). Status derived from `analyze_trend` data. Dashboard surfaces themes by lifecycle stage — PMs see what's getting worse vs. what they've fixed.
- **Impact scoring** — `impact = severity × volume × persistence × (1 - resolution_rate)`. Rank themes by impact on dashboard. Answers the PM's core question: "What should I fix next?"
- **Regression detection** — After `confirmed_fix`, if the same complaint theme re-emerges (z-score spike on same metric), auto-fire `regression` anomaly with the original finding linked. Investigator starts with prior context pre-loaded, focuses on "what changed since the fix."
- **Weekly intelligence brief** — Automated weekly report (email + dashboard widget): top emerging themes, resolved themes, regression risks, risk windows, product health score (composite of anomaly rate, resolution speed, sentiment trend). `intelligence/brief.py` — single LLM pass with strict output schema.

### Competitive Intelligence
- **Cross-product benchmarking** — Compare own vs competitor products: anomaly rates, resolution times, theme prevalence, sentiment trends. Comparative sparkline grids on dashboard.
- **Market signal detection** — When a theme spikes across multiple competitors simultaneously (e.g., all messaging apps see "notification" complaints after an OS update), flag as `market_signal` rather than product-specific. Orchestrator triages differently.

### Platform Maturity
- **API v2** — Versioned public API (`/api/v2/`) with OpenAPI spec, API key auth (separate from JWT), rate limiting. Enables third-party integrations.
- **Plugin architecture** — Formalize custom tools + collectors + notification channels into a plugin system with `plugin.json` manifests. Dynamic loading extends `tools/registry.py` and `collectors/registry.py`.
- **Full audit trail** — Every system action logged (investigation start, finding approval, ticket creation, data deletion). Exportable as compliance reports.

### Exit criteria
- A PM asks "Why did ratings drop?" in chat and gets either a cited answer from past findings or a new investigation launched — within the chat interface.
- Theme lifecycle shows a theme progressing emergence → peak → resolution.
- A regression is auto-detected and investigated with prior context pre-loaded.
- Weekly intelligence brief is generated and emailed without human initiation.

---

## Guiding Principles (all versions)

1. **Evidence or silence.** No version of EchoLens ever makes a claim it can't back with a retrievable reference. This is the non-negotiable.
2. **Agents decide, tools execute.** New capabilities are added as deterministic tools, not as agent sprawl. Every new agent must justify why runtime judgment is required.
3. **Cost is first-class.** Every feature ships with cost tracking. No hidden LLM calls, no unbounded loops, no "just throw GPT-4 at it."
4. **Honesty over confidence.** "Insufficient evidence" is always a valid and respected outcome. The system's credibility comes from what it refuses to claim, not just what it finds.
5. **Human-in-the-loop forever.** Even at v7, humans approve findings before they trigger real-world actions. The system proposes; the human disposes.
