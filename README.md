# EchoLens — Feedback Forensics

An agentic system that watches product-feedback streams (app-store reviews, GitHub issues, release notes), notices anomalies, and autonomously investigates them — forming hypotheses, gathering evidence, and producing root-cause findings where **every causal claim links to retrievable evidence**. A human approves or challenges findings before anything is published.

- **Spec:** [PRD.md](PRD.md) · **Design:** [ARCHITECTURE.md](ARCHITECTURE.md) · **UI handoff:** [echolens-ui-build/](echolens-ui-build/)

## Layout

- `backend/` — Python 3.11+, LangGraph investigator, deterministic tools, SQLite/Postgres store, FastAPI (M2+)
- `frontend/` — React + Vite + TypeScript UI (M3), pixel-matched to the design handoff

## Quick start

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows; use bin/activate on POSIX
pip install -e ".[dev]"
copy .env.example .env                            # add your OPENAI_API_KEY

python -m echolens.cli seed                       # generate the synthetic "Lumo" dataset

# Milestone 1 — the investigator
python -m echolens.cli investigate --anomaly demo1   # battery-spike investigation
python -m echolens.cli investigate --anomaly demo2   # shipping-cost case (honestly fails)

# Milestone 2 — detector, orchestrator, eval, API
python -m echolens.cli scan                       # deterministic anomaly detector
python -m echolens.cli triage                     # orchestrator triage (add --run to spawn investigations)
python -m echolens.cli eval                       # 6 golden scenarios + honesty metrics (no API key needed)
python -m echolens.cli serve                      # FastAPI on :8000 (SSE trace at /investigations/{id}/trace/stream)

pytest                                            # 38 tests
```

`demo1` resolves with the background-sync hypothesis supported (≥0.8), the Android-15 decoy rejected, and every claim in the finding citing evidence IDs — all within budget. `demo2` ends `insufficient_evidence` without bluffing. `eval` is fully hermetic (scripted LLM) and reports claim-grounding / honesty / budget compliance at 100%.

## Frontend (Milestone 3)

```bash
# terminal 1 — backend
cd backend && python -m echolens.cli serve      # FastAPI on :8000

# terminal 2 — frontend
cd frontend && npm install && npm run dev        # Vite on :5173, proxies /api → :8000
```

Open the Vite URL. Six screens, pixel-matched to the design in [echolens-ui-build/](echolens-ui-build/): Case Feed, Investigation (live trace over SSE), Finding Review (clickable evidence citations, approve/challenge), Archive, Sources, Costs. `npm run build` type-checks the whole app.

## v1.0 — Live data & production hardening

```bash
# connect a real source, collect, embed, then scan/triage/investigate as usual
python -m echolens.cli connect github <owner>/<repo> --product MyApp
python -m echolens.cli connect play_store com.your.app --product MyApp
python -m echolens.cli collect            # incremental fetch (watermark + dedup)
python -m echolens.cli embed              # backfill embeddings → semantic search on
python -m echolens.cli serve --schedule   # API + background collector cron

python -m echolens.cli createuser you@team.com pw --role admin   # for prod auth
python -m echolens.cli resume             # recover investigations killed mid-run
```

- **Real collectors** (`echolens/collectors/`): Play Store and GitHub (issues+labels+reactions, releases) — incremental by watermark, dedup by ext_id, network calls injectable (offline-testable). APScheduler cron + per-collector health. (Reddit dropped — its free API ended in 2026.)
- **Semantic search** (`echolens/search/`): embeddings backfill the corpus; search tools blend keyword + cosine similarity with a keyword fallback. Zero-dep `hash` backend by default; `sentence-transformers` optional for paraphrase-aware matching.
- **Auth & RBAC**: JWT (admin/reviewer/viewer), audit log on reviews. Off in `dev`, required in `staging`/`production` (`ECHOLENS_ENV`).
- **Hardening**: structlog JSON logs with per-investigation correlation IDs, LLM exponential backoff on rate limits, slowapi rate limiting on cost-sensitive endpoints, and crash recovery (investigations checkpoint each iteration and resume on restart).
- **Deploy**: `docker compose up` (Postgres+pgvector, Redis, backend, frontend, Nginx) or `render.yaml`.

## Status

- **M1, M2, M3 & v1.0 complete.** Core loop + six-screen React UI + real collectors, semantic search, auth/RBAC, hardening, and deployment. **58 tests + 6 eval scenarios green.** See [ARCHITECTURE.md](ARCHITECTURE.md) and [ROADMAP.md](ROADMAP.md) (v2.0/v3.0 next).
