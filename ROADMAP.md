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
- One-click deploy to Render / Railway / Fly.io with a `render.yaml` or `fly.toml`.
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

## v3.0 — Platform Intelligence

**Theme:** _"From tool to teammate. EchoLens starts telling you things you didn't ask about."_

### Proactive Monitoring & Alerts
- **Scheduled investigations**: The system runs the full pipeline (collect → detect → triage → investigate) on a cron schedule. PMs wake up to findings, not anomaly alerts.
- **Email digest**: Daily/weekly summary of new anomalies, ongoing investigations, and approved findings. Templated with `mjml` or plain HTML.
- **Slack integration**: Post findings to a channel. Support `/echolens status` and `/echolens investigate <topic>` slash commands.
- **Webhook system**: Fire configurable webhooks on events (anomaly detected, investigation resolved, finding approved). Enables integration with Jira, Linear, PagerDuty, etc.

### New Data Sources
- **App Store (iOS)** — Scrape or use the App Store Connect API for review ingestion. Unify with Play Store reviews under a common `source` field.
- **Zendesk / Intercom tickets** — CSV import initially, then API integration. Map ticket categories to investigation themes.
- **Custom CSV/JSON upload** — Let users upload arbitrary feedback data (survey results, NPS comments, support transcripts) via the UI. Schema-on-read with a simple column mapping step.
- **Hacker News** — Monitor HN mentions of tracked products via the Algolia API.

### Comparative Analysis
- **Cross-product benchmarking**: Track multiple products and compare their anomaly rates, investigation outcomes, and response times.
- **Competitor monitoring**: Ingest a competitor's Play Store reviews and surface when their users complain about things your product does well (or vice versa).

### Investigation Replay & Sharing
- **Public share links**: Generate a read-only, expiring URL for any finding. PMs can share with stakeholders without giving them EchoLens accounts.
- **Investigation replay**: Re-run a past investigation's trace step-by-step in the UI, like watching a chess game replay. Useful for auditing the agent's reasoning.
- **PDF/Markdown export**: One-click export of findings with evidence citations, recommendations, and the confidence timeline chart.

### Dashboard & Analytics
- **Product health dashboard**: Aggregate view across all tracked products — anomaly frequency, mean time to resolution, investigation success rate, top recurring themes.
- **Trend charts**: Sparklines for key metrics over time (negative review rate, theme prevalence, investigation count).
- **Cost analytics**: Breakdown of LLM spend by investigation, by agent (investigator vs orchestrator vs recommender), by model. Projected monthly cost at current usage.

---

## v4.0 — Multi-Workspace & Team Collaboration

**Theme:** _"EchoLens for the whole org, not just one PM."_

### Multi-Tenant Architecture
- **Workspaces**: Each workspace has its own products, data sources, investigations, and user roster. Data is fully isolated (schema-level or row-level tenant isolation).
- **Workspace settings**: Per-workspace LLM provider (OpenAI / Anthropic / Groq / local), budget limits, collector schedules, notification preferences.

### Collaboration Features
- **Finding comments**: Threaded discussion on findings. PMs and engineers can debate root causes before approving.
- **@mentions and assignments**: Assign findings to specific team members. "@eng-lead please review the sync hypothesis."
- **Activity feed**: Real-time feed of all actions across the workspace — investigations started, findings approved, challenges filed.
- **Investigation handoff**: A PM can add context notes mid-investigation ("We actually shipped a config change on that date too") that get injected into the agent's next planning step.

### Custom Investigation Templates
- Define reusable investigation templates: "When you see a rating drop, always check: recent releases, competitor app changes, and OS updates."
- Templates are injected into the investigator's initial prompt as domain-specific guidance.
- **Custom tools**: Let power users register custom tools (Python functions or HTTP endpoints) that the investigator can call. Example: a company's internal A/B test results API.

### Access Control & Compliance
- **SSO/SAML** for enterprise login (Okta, Azure AD).
- **Data retention policies**: Auto-delete raw review text after N days, keeping only evidence snippets cited in findings.
- **Finding approval workflows**: Multi-step approval (reviewer → manager) for high-severity findings before they trigger downstream actions.

---

## v5.0 — Autonomous Feedback Operations

**Theme:** _"The system doesn't just find problems — it helps fix them."_

### Closed-Loop Actions
- **Jira/Linear ticket creation**: Approved findings auto-create tickets with the root cause, evidence links, and recommended actions pre-filled.
- **App Store response drafting**: The recommender drafts review responses for the worst-affected users, grounded in the finding. A human approves before posting.
- **Release note suggestions**: When a fix ships, EchoLens drafts a "what we fixed" note citing the original finding and user complaints.

### Learning & Self-Improvement
- **Investigation outcome tracking**: After a fix ships, EchoLens monitors whether the anomaly actually resolves. If battery complaints drop after sync is made opt-in, that's a confirmed win — feed it back as ground truth.
- **Prompt evolution**: Track which investigation strategies (tool sequences, hypothesis structures) lead to accurate findings. Use this to improve the investigator's system prompt over time.
- **Confidence calibration**: Over many investigations, are "0.85 confidence" findings actually correct 85% of the time? Track and recalibrate.

### Advanced Detection
- **Anomaly forecasting**: Use historical anomaly patterns to predict when the next spike is likely (e.g., every major OS update triggers battery complaints for apps with background services).
- **Sentiment shift detection**: Beyond volume spikes, detect when the *tone* of reviews shifts (from "annoying" to "furious") even if volume stays flat.
- **Cross-source correlation engine**: Automatically detect when a GitHub issue surge, a Reddit thread, and a review spike are all about the same thing — without the orchestrator needing to infer it from text.

### Natural Language Interface
- **Chat with EchoLens**: "What's the biggest unresolved complaint about our Android app?" → EchoLens queries its investigation history and answers with citations.
- **Investigation by question**: "Why did our rating drop last Tuesday?" → auto-creates an anomaly event and kicks off an investigation.
- **Findings Q&A**: Ask follow-up questions about any finding. "Was this also happening on iOS?" → the agent runs targeted queries and extends the finding.

---

## Guiding Principles (all versions)

1. **Evidence or silence.** No version of EchoLens ever makes a claim it can't back with a retrievable reference. This is the non-negotiable.
2. **Agents decide, tools execute.** New capabilities are added as deterministic tools, not as agent sprawl. Every new agent must justify why runtime judgment is required.
3. **Cost is first-class.** Every feature ships with cost tracking. No hidden LLM calls, no unbounded loops, no "just throw GPT-4 at it."
4. **Honesty over confidence.** "Insufficient evidence" is always a valid and respected outcome. The system's credibility comes from what it refuses to claim, not just what it finds.
5. **Human-in-the-loop forever.** Even at v5, humans approve findings before they trigger real-world actions. The system proposes; the human disposes.
