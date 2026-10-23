# Frontend TypeSafe follow-up

Reviewed the existing uncommitted frontend patch and the report's frontend risk flags. TypeSafe supplies categorical probabilities, not reproducible defect descriptions; unchanged dispositions below do not certify the absence of all defects.

## Confirmed fixes retained

- `frontend/src/hooks.ts`: discard watcher responses after dependency cleanup; discard old trace responses/events; serialize fallback polling with completion-scheduled timeouts and stop on terminal replies. Prevents an old product/case response from affecting the new selection.
- `frontend/src/api.ts`: QuarterPlan exposes optional saved `included` / `excluded` arrays, matching the updated backend response. Brain risk review already sends `{ text, product_id }`, matching ReviewDoc; no argument change needed.
- `frontend/src/screens/Backlog.tsx`: save only explicit includes/excludes rather than treating every automatically selected/deferred case as an override. Capacity edits retain planner freedom; input is disabled while saving. Omitted notes preserve notes; the UI does not submit an empty notes object.
- `frontend/scripts/verify-typesafe-regressions.mjs`: retained four executable production-hook/handler regressions; added capacity override preservation and terminal polling checks. This is a deterministic hook harness, not a browser or full React lifecycle test.

## Other flagged files: dispositions

| File | Disposition |
| --- | --- |
| `frontend/src/App.tsx` | No change: boot callbacks have alive guards; case screens are keyed by case ID and product screens by product scope. Build verifies component contracts. |
| `frontend/src/components/GoogleButton.tsx` | No change: cancelled guards already protect SDK readiness and resize callbacks. Live Google sign-in was not exercised. |
| `frontend/src/components/NewCaseModal.tsx` | No change: async errors surface, busy controls and dialog dismissal guard exist. No introduced defect confirmed. |
| `frontend/src/components/Toast.tsx` | Maintainability-only flag; no refactor needed for the focused fixes. |
| `frontend/src/screens/CaseDetail.tsx` | No change: request sequence and alive guards plus bounded poll failures already exist. |
| `frontend/src/screens/Chat.tsx` | No change: product remount and alive guard handle old replies; StrictMode mount restores the guard. |
| `frontend/src/screens/Costs.tsx` | No change: useAsync handles fetch errors and stale loads; static build passes. Live cost arithmetic remains part of backend verification. |
| `frontend/src/screens/Login.tsx` | No introduced defect confirmed; browser overflow verification remains unavailable in this session. |
| `frontend/src/screens/Portfolio.tsx` | No change: main and secondary request error states exist; relies on typed backend response. |
| `frontend/src/screens/Sources.tsx` | No introduced defect confirmed; connector/service behavior was not exercised. |
| `frontend/src/screens/Today.tsx` | Shared watcher fix covers stale background updates; no screen-specific edit required. |
| `frontend/src/screens/case/FindingTab.tsx` | No introduced defect confirmed; static compilation passes. No speculative maintenance rewrite. |

## Verification

- `node frontend/scripts/verify-typesafe-regressions.mjs`: 6/6 pass.
- `npm run build` from frontend: TypeScript and Vite production build pass (56 modules).
- `node --experimental-strip-types scripts/verify-theme-mode.mjs`: pass.
- `node --experimental-strip-types scripts/verify-sidebar-state.mjs`: pass.
- `node scripts/verify-responsive-contract.mjs`: pass.
- `node scripts/verify-login-overflow.mjs`: unavailable; ECONNREFUSED on required local CDP endpoint `127.0.0.1:9223`. No browser result claimed.

Node is v22.14.0. Running the theme/sidebar scripts without `--experimental-strip-types` initially failed because their catch masks unsupported `.ts` imports as missing implementations; rerunning with the flag passed. No external services, keys, or production data were used. Backend/full-suite testing belongs to the parent task.
