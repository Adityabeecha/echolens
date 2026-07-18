# PRD: ProductPulse — An Agentic Product-Feedback Investigation System

**Version:** 1.0 (v0 → v1 scope)
**Owner:** Aditya
**Status:** Ready for build
**Primary reader:** Claude Code (build from this document top to bottom)

---

## 0. How to use this document (for Claude Code)

Build in the order defined in **Section 13 (Milestones)**. Do not build everything at once. Milestone 1 must run end-to-end before Milestone 2 begins.

**The architectural rule that governs this system:**
> Agents decide; tools execute; ingestion is dumb. An agent's job is runtime judgment — what to investigate, which tool to call next, whether evidence is sufficient, when to escalate to a human. Anything that does not require judgment (scraping, storing, counting) is a plain deterministic function, never an agent. If a component's steps can be drawn as a fixed flowchart at design time, it must not be implemented as an agent.

**The evidence rule (non-negotiable):**
> No causal claim without an evidence chain. Every finding must cite the specific reviews, issues, release notes, or statistics that support it, with retrievable IDs. If evidence is insufficient, the agent reports "insufficient evidence" and escalates — it never bluffs. (This is the ProductPulse equivalent of Closebrief's faithfulness guard.)

---

## 1. Overview & Problem Statement

Product teams drown in feedback: app-store reviews, GitHub issues, Reddit threads, support tickets. Today a PM notices a rating drop, then spends days manually reading reviews, cross-referencing release notes, and guessing at root causes. The analysis is slow, anecdotal, and biased toward whoever complained loudest.

**ProductPulse** is an agentic system that watches feedback streams, notices anomalies worth investigating, and autonomously investigates them — forming hypotheses, gathering evidence across sources, and producing a root-cause finding with a full evidence chain and a recommended action plan. A human approves or challenges findings before anything is published.

The demo moment: *"1-star reviews spiked 23% this week"* → the agent investigates live, its reasoning visible step by step → *"Battery complaints began 3 days after v3.2 shipped background sync; 4 corroborating GitHub issues; confidence HIGH; recommended: make sync opt-in, ship hotfix"* — every claim clickable to its evidence.

### 1.1 What makes this agentic (and not a pipeline)
- The investigation path is chosen at **runtime** by the agent based on what it finds; two different anomalies produce entirely different tool-call sequences.
- The agent maintains explicit **hypotheses** with confidence, decides what evidence would confirm/kill each, and loops until resolved or budget-exhausted.
- An **orchestrator triages**: it decides which anomalies deserve investigation, which are noise, and which duplicate open investigations — deciding what NOT to do.
- **Human-in-the-loop**: low-confidence or conflicting-evidence findings pause and escalate rather than publish.

### 1.2 Anchor scenario (v0 builds exactly this)
A mobile app's Play Store reviews + its GitHub repo + its release notes. One trigger type (negative-review spike). One full investigation with visible reasoning. One finding with evidence chain. One human approval step.

---

## 2. Goals & Non-Goals

### 2.1 Goals
- Autonomous investigation of feedback anomalies with runtime tool selection.
- Every finding carries a complete, clickable evidence chain (IDs of reviews/issues/notes used).
- Explicit hypothesis tracking with confidence scores; honest "insufficient evidence" outcomes.
- Cost-bounded agency: hard per-investigation budgets (tokens, tool calls, wall-clock).
- Human review checkpoint before findings are published; feedback recorded.
- A live reasoning trace UI — the investigation is watchable, step by step.

### 2.2 Non-Goals
- Not a dashboard/BI product (no KPI cards; that's Closebrief).
- Not real-time streaming; scheduled collection + on-demand investigation.
- Not multi-tenant SaaS; single workspace.
- No fine-tuning or custom models; prompted LLM + deterministic tools.
- v0 does not include Zendesk/analytics-events sources (synthetic/CSV stubs acceptable later).

---

## 3. Personas

| Persona | Role | Primary need |
|---|---|---|
| **PM (primary)** | Reviews findings, approves/challenges | Trustworthy root causes with evidence, not vibes |
| **Engineer** | Consumes the finding | Enough specificity to act (version, feature, linked issues) |
| **Recruiter/interviewer (meta)** | Watches the demo | See real agency: branching decisions, honest uncertainty, budget control |

---

## 4. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  COLLECTORS (deterministic, scheduled — NOT agents)          │
│  play_store_collector · github_collector · reddit_collector  │
│  release_notes_loader                                        │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
                 ┌────────────────────┐
                 │  Store (Postgres)  │  reviews, issues, posts,
                 │  + embeddings      │  releases, stats rollups
                 └─────────┬──────────┘
                           ▼
              ┌─────────────────────────┐
              │  ANOMALY DETECTOR       │  deterministic stats:
              │  (deterministic)        │  z-score on volume/rating
              └───────────┬─────────────┘
                          ▼ anomaly events
              ┌─────────────────────────┐
              │  ORCHESTRATOR AGENT     │  triage: investigate /
              │  (judgment: triage,     │  ignore / merge-dup;
              │   budget, dedupe)       │  assigns budget
              └───────────┬─────────────┘
                          ▼ spawns (one per investigation)
              ┌─────────────────────────┐
              │  INVESTIGATOR AGENT     │  plan → tool call → update
              │  (LangGraph loop)       │  hypotheses → repeat until
              │                         │  resolved / budget out /
              │  tools:                 │  needs-human
              │   search_reviews        │
              │   review_stats          │
              │   search_github_issues  │
              │   get_release_notes     │
              │   search_reddit         │
              │   compare_periods       │
              └───────────┬─────────────┘
                          ▼ Finding (hypotheses + evidence chain)
              ┌─────────────────────────┐
              │  RECOMMENDER AGENT      │  drafts actions, ranked
              │  (single LLM pass)      │  roadmap, optional PRD stub
              └───────────┬─────────────┘
                          ▼
              ┌─────────────────────────┐
              │  HUMAN REVIEW           │  approve / challenge /
              │  (UI checkpoint)        │  request-more-evidence
              └───────────┬─────────────┘
                          ▼
                 Published finding + report / Slack webhook
```

### 4.1 Component responsibilities (strict)
- **Collectors**: fetch and normalize. No LLM, no decisions. Cron/scheduled.
- **Anomaly detector**: pure stats (z-score of daily 1-star volume vs trailing 28-day baseline; rating drop; volume surge per source). Emits `anomaly_event` rows. Deterministic and unit-tested.
- **Orchestrator**: an agent, but a small one. Input: pending anomaly events + open investigations + remaining daily budget. Output per event: `investigate(budget) | ignore(reason) | merge(existing_id)`. One LLM call per triage batch.
- **Investigator**: the heart. A LangGraph state machine that loops: *reason → pick tool → execute → update hypotheses → check stop conditions*. All tool calls logged as trace steps.
- **Recommender**: takes a resolved finding, drafts 2–4 ranked actions with effort/impact guesses and an optional one-page PRD stub. Single pass; no tool loop.
- **Human review**: findings with confidence < HIGH, or any finding, wait for approve/challenge. Challenge with a note re-opens the investigation with the note injected as context.

---

## 5. The Investigator (detailed spec — this is the project)

### 5.1 State (LangGraph graph state)
```python
class InvestigationState(TypedDict):
    investigation_id: str
    trigger: AnomalyEvent            # what fired
    hypotheses: list[Hypothesis]     # see 5.2
    evidence: list[EvidenceItem]     # see 5.3
    trace: list[TraceStep]           # every reasoning/tool step, ordered
    budget: Budget                   # remaining tokens/tool_calls/seconds
    status: Literal["running","resolved","insufficient_evidence",
                    "needs_human","budget_exhausted"]
    finding: Finding | None
```

### 5.2 Hypothesis object
```json
{
  "id": "H1",
  "statement": "Battery drain complaints are caused by the background sync feature shipped in v3.2",
  "confidence": 0.72,
  "status": "active | supported | rejected",
  "evidence_for": ["ev_003","ev_007","ev_011"],
  "evidence_against": ["ev_009"],
  "next_test": "Check whether battery-mention rate among users on v3.1 stayed flat"
}
```
Rules: max 4 active hypotheses; every confidence change must reference the evidence item that caused it; a hypothesis may only reach `supported` with ≥2 independent evidence items from ≥2 distinct sources (e.g., reviews + GitHub), otherwise best status is `active` and the finding escalates to human.

### 5.3 Evidence item
```json
{
  "id": "ev_007",
  "source": "github",
  "ref": "issue #482",
  "retrieved_by": "search_github_issues('background sync battery')",
  "content_snippet": "…drains 8%/hr since 3.2 when sync enabled…",
  "supports": ["H1"], "contradicts": []
}
```
Every evidence item must be re-retrievable by its `ref`. The finding UI links each claim to its evidence items.

### 5.4 Tools (contracts — plain Python functions, no LLM inside)
| Tool | Signature (summary) | Returns |
|---|---|---|
| `search_reviews` | query, date_range, rating_filter, limit | matching reviews with ids, dates, ratings |
| `review_stats` | term or theme, granularity | daily counts, % of negatives, deltas |
| `compare_periods` | metric, before_range, after_range | means, delta %, z-score |
| `search_github_issues` | query, state, since | issues with ids, titles, snippets |
| `get_release_notes` | version or date_range | release entries |
| `search_reddit` | query, subreddit, since | posts with ids, snippets |
Tool outputs are truncated/summarized deterministically (top-k, char caps) before entering context — token discipline lives in the tool layer, not the prompt.

### 5.5 The loop (LangGraph nodes)
1. **plan** — LLM: given state, either (a) pick one tool + args + which hypothesis it tests, (b) create/revise hypotheses, (c) declare resolution, or (d) declare insufficient evidence / needs-human. Must output structured JSON.
2. **act** — execute the tool (deterministic), append EvidenceItem(s).
3. **update** — LLM: revise hypothesis confidences citing new evidence ids.
4. **check** — deterministic guard: budget remaining? iterations < max (default 12)? any hypothesis ≥0.8 with the two-source rule satisfied? conflicting strong evidence (→ needs_human)?
Loop plan→act→update→check until check exits.

### 5.6 Stop conditions & honesty
- `resolved`: a hypothesis is `supported` under the two-source rule.
- `insufficient_evidence`: iterations/budget spent, best confidence <0.5 → finding says exactly that, with what was checked and what evidence would settle it.
- `needs_human`: strong conflicting evidence, or confidence 0.5–0.8 at budget end.
- Never emit a causal claim in prose that isn't backed by listed evidence ids — a deterministic post-check scans the finding text for unsupported claims (Closebrief-guard analog: claim sentences must reference evidence ids; flag otherwise).

### 5.7 Budgets (hard limits, enforced in code)
Per investigation: max 12 loop iterations, max 20 tool calls, max N tokens (config, default ~60k cumulative), max 5 min wall-clock. Orchestrator daily budget: max K investigations/day (default 5), max $X LLM spend (tracked like Closebrief's /costs). Exhaustion is a first-class outcome, shown honestly in the UI.

---

## 6. Data Sources (v0 vs later)

| Source | v0 | How |
|---|---|---|
| Play Store reviews | ✅ | `google-play-scraper` (unofficial lib, fine for portfolio); pick a real popular app OR use the synthetic set (Section 10) |
| GitHub Issues | ✅ | official REST API, authenticated (5k req/hr free) |
| Release notes | ✅ | GitHub releases API or a hand-authored file for the synthetic story |
| Reddit | v1 | official API free tier |
| Zendesk tickets | v1+ | synthetic CSV only (no free real source) |
| Analytics events | out of v1 | stub |

---

## 7. Storage & Schema (Postgres/Supabase, pgvector for review embeddings)

```
reviews            (id, source, ext_id, rating, text, version, created_at, embedding)
issues             (id, ext_id, title, body_snippet, state, created_at)
posts              (id, source, ext_id, text_snippet, created_at)
releases           (id, version, notes, released_at)
anomaly_events     (id, type, metric, delta, z, window, status, created_at)
investigations     (id, anomaly_id, status, budget_json, created_at, resolved_at)
hypotheses         (id, investigation_id, statement, confidence, status, json)
evidence           (id, investigation_id, source, ref, snippet, retrieved_by, json)
trace_steps        (id, investigation_id, seq, kind[plan|act|update|check], content_json, tokens, ms)
findings           (id, investigation_id, summary, confidence, status[draft|approved|challenged], json)
recommendations    (id, finding_id, action, rationale, effort, impact, rank)
reviews_feedback   (id, finding_id, action[approve|challenge], note, created_at)
llm_calls          (id, agent, tokens_in, tokens_out, cost, ms, created_at)
```

---

## 8. API (FastAPI)

| Endpoint | Purpose |
|---|---|
| `POST /collect/run` | trigger collectors (dev convenience) |
| `POST /anomalies/scan` | run detector now |
| `GET /anomalies` | pending/triaged events |
| `POST /investigations` | start investigation for an anomaly (or orchestrator does) |
| `GET /investigations/{id}` | full state incl. hypotheses, evidence, budget |
| `GET /investigations/{id}/trace` | ordered trace steps (poll or SSE stream for live UI) |
| `POST /findings/{id}/review` | approve / challenge(note) |
| `GET /costs` | spend, tokens, per-agent latency (reuse Closebrief pattern) |
| `GET /health` | db, llm, scheduler status |

---

## 9. UI (thin — the trace is the star)

Three screens, plain HTML/JS (reuse Closebrief's shell aesthetic; no login for v0):
1. **Anomaly feed** — detected events with the orchestrator's triage decision + reason ("ignored: duplicate of INV-3").
2. **Investigation view (the demo screen)** — live-updating reasoning trace (each step: thought → tool called → evidence found), hypothesis panel with confidence bars moving as evidence lands, budget meter (iterations/tokens used), and the final finding with every claim linking to evidence.
3. **Finding review** — the finding + recommendations + Approve / Challenge (with note). Challenged findings visibly re-open.

---

## 10. Synthetic Demo Dataset (build this — controllability beats realism)

A generator script (like Closebrief's) producing a coherent story: fictional app "Lumo" —
- 6 months of ~3,000 reviews with baseline themes (UI praise, occasional crash mentions)
- v3.2 released day X shipping "background sync" (release note exists)
- battery-complaint rate rises from ~2% to ~9% of negatives starting X+3
- 4 GitHub issues about sync/battery filed X+4..X+12, one with a red-herring comment blaming the OS update (forces hypothesis competition)
- an OS update also occurred X-1 (the decoy — the agent must distinguish; version-segmented stats settle it)
- a second, unrelated mini-anomaly (shipping-cost complaints after a pricing post) the orchestrator should triage as separate
Expected outcomes are documented so the demo is verifiable: H_sync supported (~0.85), H_os rejected (v3.1-user battery mentions flat).

## 11. Evaluation (the differentiator, again)

- **Golden investigations**: ≥6 scripted scenarios on the synthetic data (clear cause; decoy cause; genuinely insufficient evidence; conflicting evidence → needs_human; duplicate anomaly → merge; budget-exhaustion path). Assert final status, supported hypothesis, and that cited evidence ids exist.
- **Claim-grounding check**: automated scan that every causal sentence in findings references evidence ids (target 100%).
- **Honesty metric**: on the insufficient-evidence scenario, the agent must NOT emit a supported finding (target 100%).
- **Budget compliance**: no investigation exceeds hard caps (target 100%).
- **Efficiency**: median tool calls per resolved investigation (track; interviewers ask).

## 12. Tech Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Agent framework | **LangGraph** | explicit state machine, HITL interrupts, replayable |
| LLM | Groq (free Llama) or Gemini Flash free tier for dev; any via `LLMClient` interface | swappable, as in Closebrief |
| Embeddings | sentence-transformers local | $0 |
| API | FastAPI | |
| DB | SQLite dev → Supabase Postgres (+pgvector) | reuse Closebrief patterns |
| Cache/queue | none in v0; Upstash Redis if needed for scheduling | keep it simple |
| UI | static HTML/JS + SSE polling | trace view priority |
| Deploy | Render free tier | collectors as scheduled jobs |
| Cost | $0 dev; ≤$10 for polished final runs | budgets enforced in code |

## 13. Milestones (BUILD IN THIS ORDER)

### M1 — The Investigator core (no orchestrator, no UI)
Synthetic dataset generator + store + the 6 tools (unit-tested, deterministic) + the LangGraph loop with hypotheses/evidence/trace/budget + CLI: `python -m pulse.investigate --anomaly demo1` prints the full trace and finding.
**Exit:** the battery scenario resolves with H_sync supported, decoy rejected, every claim evidence-linked, within budget. The insufficient-evidence scenario honestly fails.

### M2 — Detector + Orchestrator + review loop
Deterministic anomaly detector; orchestrator triage (investigate/ignore/merge) with budgets; findings + recommender; challenge-reopens flow; eval harness (Section 11) green.

### M3 — Live UI + real source + deploy
Trace UI with SSE; swap in a real Play-Store app + its GitHub repo alongside synthetic; costs page; deploy to Render; README with architecture + eval results + a recorded demo GIF of a live investigation.

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent flails / loops uselessly | hard iteration+budget caps; plan step must name which hypothesis a tool call tests |
| Confident wrong causes | two-source rule; claim-grounding scan; decoy scenario in evals |
| Free LLM rate limits mid-demo | trace persisted + replayable; demo can replay a recorded investigation live-style |
| Scraper breaks (Play Store) | synthetic dataset is the demo backbone; real source is garnish |
| Scope creep into more sources | v0 = one trigger, three sources, one full investigation. Everything else is roadmap |

## 15. Open Decisions
1. Name: EchoLens / ProductPulse / other — pick before repo creation.
2. Real app to track in M3 (pick something with an active public GitHub, e.g. an OSS Android app like Signal or Firefox) — or stay synthetic-only.
3. Groq vs Gemini free tier as the dev LLM (recommend Groq for speed of the loop).

*End of PRD.*
