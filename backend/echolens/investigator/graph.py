"""The Investigator: a LangGraph state machine looping
plan → act → update → check until resolved / honest failure / budget out.

Agents decide (plan, update); tools execute (act); guards enforce (check).
Every step is persisted as a trace_steps row (THINK/TOOL/EVID/UPDT/FAIL/CHECK)
— the live UI streams that table verbatim.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from echolens.config import (
    EXTENSION_CONFIDENCE,
    EXTENSION_FACTOR,
    MAX_ACTIVE_HYPOTHESES,
    SUPPORT_CONFIDENCE,
)
from echolens.db.models import (
    AnomalyEvent,
    EvidenceRow,
    Finding,
    HypothesisRow,
    Investigation,
    LLMCall,
    TraceStep,
)
from echolens.investigator import guards
from echolens.investigator.prompts import (
    FINDING_SCHEMA,
    FINDING_SYSTEM,
    PLAN_SCHEMA,
    UPDATE_SCHEMA,
    UPDATE_SYSTEM,
    plan_system,
    render_state,
)
from echolens.investigator.state import Budget, InvState
from echolens.llm.client import LLMClient, LLMFormatError
from echolens.logging import get_logger
from echolens.tools.registry import TOOLS, run_tool

log = get_logger("investigator")


def _collect_refs(node) -> set[str]:
    """All verbatim `ref` values present in a tool result — the only refs the
    update step is allowed to turn into evidence (re-retrievability)."""
    refs: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "ref" and isinstance(v, str):
                refs.add(v)
            else:
                refs |= _collect_refs(v)
    elif isinstance(node, list):
        for item in node:
            refs |= _collect_refs(item)
    return refs


class Investigator:
    def __init__(
        self,
        session: Session,
        anomaly: AnomalyEvent,
        llm: LLMClient | None = None,
        tier: str = "standard",
        on_step: Callable[[str, dict], None] | None = None,
        opened_by: str = "anomaly",
        context_note: str | None = None,
        reopens_investigation_id: int | None = None,
        existing_investigation: Investigation | None = None,
    ):
        self.session = session
        self.anomaly = anomaly
        self.budget = Budget.for_tier(tier)
        self.on_step = on_step or (lambda kind, content: None)
        self.context_note = context_note  # injected on challenge-reopen (PRD §4.1)
        self._recent: list[str] = []
        self._executed_calls: set[str] = set()
        self._refuted: set[str] = set()   # v5.0 counter-evidence duty (per hypothesis)
        # v5.0 trust loop: past human verdicts (calibration + weak spots) become a
        # corrective note injected into this investigation's planning prompt.
        try:
            from echolens.calibration import guidance_text
            self._guidance = guidance_text(session, getattr(anomaly, "product_id", None))
        except Exception:
            self._guidance = ""

        if llm is None:
            from echolens.llm.openai_client import OpenAIClient
            llm = OpenAIClient(on_call=self._record_llm_call)
        self.llm = llm

        if existing_investigation is not None:  # v1.0 recovery: bind, don't create
            self.inv = existing_investigation
            self.inv.status = "running"
            self._seq = session.query(TraceStep).filter_by(
                investigation_id=self.inv.id).count()
        else:
            self._seq = 0
            self.inv = Investigation(
                anomaly_id=anomaly.id, status="running", opened_by=opened_by,
                budget_tier=tier, budget_json=self.budget.as_dict(),
                reopens_investigation_id=reopens_investigation_id,
                product_id=getattr(anomaly, "product_id", None),
            )
            session.add(self.inv)
        session.flush()

        # v8.0 scoping: an investigation may only read ITS product's corpus.
        # Enforced here (deterministic), not asked of the model — the agent has
        # no way to widen the blast radius by writing a different product arg.
        self._product_name = self._resolve_product_name()

    def _resolve_product_name(self) -> str | None:
        """Display name of this case's product — the value stamped on corpus rows.
        None on a pre-v8 / unscoped case, which reads the whole corpus as before."""
        pid = getattr(self.inv, "product_id", None)
        if pid is None:
            return None
        from echolens.db.models import Product
        product = self.session.get(Product, pid)
        return product.name if product is not None else None

    # ── bookkeeping ────────────────────────────────────────────────────

    def _record_llm_call(self, agent: str, model: str, tokens_in: int,
                         tokens_out: int, cost: float, ms: int) -> None:
        self.budget.tokens += tokens_in + tokens_out
        self.budget.cost_usd += cost
        self.session.add(LLMCall(
            investigation_id=self.inv.id, agent=agent, model=model,
            tokens_in=tokens_in, tokens_out=tokens_out, cost=cost, ms=ms,
        ))

    def _trace(self, kind: str, content: dict, tokens: int = 0, ms: int = 0) -> None:
        self._seq += 1
        self.session.add(TraceStep(
            investigation_id=self.inv.id, seq=self._seq, kind=kind,
            content_json=content, tokens=tokens, ms=ms,
        ))
        self.session.flush()
        summary = content.get("text") or content.get("code") or json.dumps(content)[:120]
        self._recent.append(f"[{kind}] {summary[:160]}")
        self.on_step(kind, content)

    # ── nodes ──────────────────────────────────────────────────────────

    def _plan(self, state: InvState) -> InvState:
        state["pending_tool"] = None
        state["pending_delegate"] = None
        prompt = render_state(
            state["trigger"], state["hypotheses"],
            [{k: e[k] for k in ("id", "source", "ref", "snippet", "supports", "contradicts")}
             for e in state["evidence"]],
            self.budget.as_dict(), self._recent,
        )
        try:
            res = self.llm.complete_json(plan_system(self._guidance), prompt, PLAN_SCHEMA, "investigator.plan")
        except LLMFormatError as err:
            self._trace("FAIL", {"code": "plan", "error": str(err),
                                 "text": "Plan step produced malformed output; iteration burned."})
            return state

        out = res.parsed
        self._trace("THINK", {"text": out.get("thought", ""), "action": out.get("action")},
                    tokens=res.total_tokens, ms=res.ms)

        action = out.get("action")
        if action == "call_tool":
            tool = out.get("tool") or {}
            if tool.get("name") in TOOLS and tool.get("tests_hypothesis"):
                state["pending_tool"] = tool
            else:
                self._trace("FAIL", {
                    "code": f"plan → {tool.get('name') or 'no tool payload'}",
                    "error": "action=call_tool requires tool{name,args,tests_hypothesis} "
                             f"with a name from: {', '.join(TOOLS)}",
                    "text": "Step wasted. Next plan MUST include a complete tool payload.",
                })
        elif action == "revise_hypotheses":
            if out.get("hypotheses"):
                state["hypotheses"] = self._apply_hypothesis_revision(state, out["hypotheses"])
            else:
                self._trace("FAIL", {
                    "code": "plan → revise_hypotheses",
                    "error": "action=revise_hypotheses requires the full 'hypotheses' list",
                    "text": "Step wasted. Next plan MUST include the hypotheses payload.",
                })
        elif action == "conclude":
            if out.get("conclusion"):
                state["proposed"] = out["conclusion"]
            else:
                self._trace("FAIL", {
                    "code": "plan → conclude",
                    "error": "action=conclude requires conclusion{status,reason}",
                    "text": "Step wasted. Next plan MUST include the conclusion payload.",
                })
        elif action == "delegate":
            from echolens.investigator.specialists import SPECIALISTS
            deleg = out.get("delegate") or {}
            if deleg.get("specialist") in SPECIALISTS:
                state["pending_delegate"] = deleg
            else:
                self._trace("FAIL", {
                    "code": f"plan → delegate {deleg.get('specialist')}",
                    "error": f"unknown specialist; choose from {list(SPECIALISTS)}",
                    "text": "Step wasted.",
                })
        return state

    def _delegate(self, state: InvState) -> InvState:
        """v2.0: run a single-pass specialist and fold its analysis into the
        investigator's context (not as evidence — analysis only)."""
        from echolens.investigator.specialists import run_specialist

        deleg = state.get("pending_delegate") or {}
        state["pending_delegate"] = None
        name = deleg.get("specialist")
        focus = deleg.get("focus", "")
        context = self._specialist_context(name, focus)
        result = run_specialist(self.llm, name, context)
        if result is None:
            self._trace("FAIL", {"code": f"specialist {name}",
                                 "error": "specialist produced no usable analysis",
                                 "text": "Continuing without it."})
            return state
        self._trace("SPEC", {"specialist": name, "focus": focus,
                             "text": result.get("takeaway", ""), "detail": json.dumps(result)})
        return state

    def _specialist_context(self, name: str, focus: str) -> str:
        """Gather a compact, deterministic data slice for the specialist."""
        from echolens.tools.get_release_notes import get_release_notes
        from echolens.tools.review_stats import review_stats
        from echolens.tools.search_github_issues import search_github_issues
        from echolens.tools.search_reviews import search_reviews

        scope = self._product_name  # specialists read this case's product only
        if name == "sentiment_analyst":
            reviews = search_reviews(self.session, query=focus or "issue", rating_max=2,
                                     limit=8, product=scope)
            return ("Negative reviews to analyze:\n" +
                    "\n".join(f"- ({r['rating']}★, {r['version']}) {r['snippet']}"
                              for r in reviews["reviews"]))
        # timeline_reconstructor
        releases = get_release_notes(self.session, product=scope)
        issues = search_github_issues(self.session, query=focus or "bug", product=scope)
        stats = review_stats(self.session, term=focus or "issue", product=scope)
        events = ["RELEASES:"] + [f"  {r['released_at']}: {r['version']} — {r['notes'][:80]}"
                                  for r in releases["releases"]]
        events += ["ISSUES:"] + [f"  {i['date']}: {i['title']}" for i in issues["issues"][:6]]
        events += ["COMPLAINT-RATE (recent days):"] + [
            f"  {d['date']}: {d['term_neg']} negatives mention it" for d in stats.get("daily_tail", [])]
        return "Dated events to order:\n" + "\n".join(events)

    def _apply_hypothesis_revision(self, state: InvState, proposed: list[dict]) -> list[dict]:
        existing = {h["id"]: h for h in state["hypotheses"]}
        merged: list[dict] = []
        active = 0
        for p in proposed:
            hid = p.get("id") or f"H{len(merged) + 1}"
            old = existing.get(hid, {})
            status = p.get("status", "active")
            if status == "supported":  # only the check guard can grant this
                status = "active"
            if status == "active":
                active += 1
                if active > MAX_ACTIVE_HYPOTHESES:
                    continue
            merged.append({
                "id": hid,
                "statement": p.get("statement", old.get("statement", "")),
                "confidence": max(0.0, min(1.0, float(p.get("confidence", old.get("confidence", 0.5))))),
                "status": status,
                "evidence_for": old.get("evidence_for", []),
                "evidence_against": old.get("evidence_against", []),
                "next_test": p.get("next_test", ""),
                # v2.0: hypotheses this one gains from if THEY are rejected
                "boost_if_rejected": p.get("boost_if_rejected", old.get("boost_if_rejected", [])),
            })
        self._persist_hypotheses(merged)
        self._trace("UPDT", {
            "code": "hypotheses revised",
            "text": "; ".join(f"{h['id']}({h['confidence']:.2f}): {h['statement'][:80]}" for h in merged),
        })
        return merged

    def _act(self, state: InvState) -> InvState:
        tool = state.get("pending_tool")
        state["pending_tool"] = None
        if not tool:
            return state
        name, args = tool["name"], tool.get("args", {})
        code = f"{name}({json.dumps(args, sort_keys=True, default=str)})"
        if code in self._executed_calls:  # deterministic dedupe: results won't change
            self._trace("FAIL", {"code": code,
                                 "error": "duplicate of an earlier tool call",
                                 "text": "Not executed — the result would be identical. "
                                         "Design a DIFFERENT test (other source, segment, or period)."})
            state["last_tool"] = None
            return state
        self._executed_calls.add(code)
        self.budget.tool_calls += 1
        start = time.monotonic()
        try:
            result = run_tool(self.session, name, args, product=self._product_name)
        except Exception as err:  # deterministic failure -> FAIL trace, loop continues
            self._trace("FAIL", {"code": code, "error": str(err),
                                 "text": "Tool failed; the next plan step decides whether this is blocking."})
            state["last_tool"] = None
            return state
        ms = int((time.monotonic() - start) * 1000)
        preview = {k: v for k, v in result.items() if not isinstance(v, list)}
        self._trace("TOOL", {"code": code, "preview": json.dumps(preview, default=str),
                             "tests_hypothesis": tool.get("tests_hypothesis")}, ms=ms)
        state["last_tool"] = {"name": name, "args": args, "result": result,
                              "tests_hypothesis": tool.get("tests_hypothesis")}
        return state

    def _update(self, state: InvState) -> InvState:
        last = state.get("last_tool")
        state["last_tool"] = None
        if not last:
            return state
        prompt = (
            f"HYPOTHESES:\n{json.dumps(state['hypotheses'], indent=1)}\n\n"
            f"TOOL CALL (testing {last.get('tests_hypothesis')}):\n"
            f"{last['name']}({json.dumps(last['args'], default=str)})\n\n"
            f"TOOL RESULT:\n{json.dumps(last['result'], default=str)}"
        )
        try:
            res = self.llm.complete_json(UPDATE_SYSTEM, prompt, UPDATE_SCHEMA, "investigator.update")
        except LLMFormatError as err:
            self._trace("FAIL", {"code": "update", "error": str(err),
                                 "text": "Evidence assessment failed; result kept in trace only."})
            return state

        valid_refs = _collect_refs(last["result"])
        retrieved_by = f"{last['name']}({json.dumps(last['args'], default=str)})"
        source = TOOLS[last["name"]].source
        known_h = {h["id"] for h in state["hypotheses"]}
        ref_to_eid: dict[str, str] = {e["ref"]: e["id"] for e in state["evidence"]}

        from echolens.config import MAX_EVIDENCE_PER_UPDATE
        for item in res.parsed.get("evidence", [])[:MAX_EVIDENCE_PER_UPDATE]:
            ref = item.get("ref", "")
            if ref not in valid_refs:  # not re-retrievable -> rejected by guard
                self._trace("FAIL", {"code": f"evidence ref '{ref}'",
                                     "error": "ref not present in tool result",
                                     "text": "Evidence rejected: must be re-retrievable verbatim."})
                continue
            if ref in ref_to_eid:  # already on record; don't double-count
                continue
            dup = self._near_duplicate(item.get("snippet", ""), source, state["evidence"])
            if dup:  # v5.0 quality: near-identical evidence merges, never double-counts
                ref_to_eid[ref] = dup
                self._trace("EVID", {"id": dup, "source": source.upper(), "ref": ref,
                                     "text": f"(merged) near-duplicate of {dup}; counted once, not twice.",
                                     "supports": [], "contradicts": []})
                continue
            eid = f"ev_{len(state['evidence']) + 1:03d}"
            ev = {
                "id": eid, "source": source, "ref": ref,
                "snippet": item.get("snippet", "")[:400], "retrieved_by": retrieved_by,
                "supports": [h for h in item.get("supports", []) if h in known_h],
                "contradicts": [h for h in item.get("contradicts", []) if h in known_h],
            }
            state["evidence"].append(ev)
            ref_to_eid[ref] = eid
            for h in state["hypotheses"]:
                if h["id"] in ev["supports"]:
                    h["evidence_for"].append(eid)
                if h["id"] in ev["contradicts"]:
                    h["evidence_against"].append(eid)
            self.session.add(EvidenceRow(
                investigation_id=self.inv.id, eid=eid, source=source, ref=ref,
                snippet=ev["snippet"], retrieved_by=retrieved_by,
                json={"supports": ev["supports"], "contradicts": ev["contradicts"]},
            ))
            self._trace("EVID", {"id": eid, "source": source.upper(), "ref": ref,
                                 "text": ev["snippet"], "supports": ev["supports"],
                                 "contradicts": ev["contradicts"]},
                        tokens=res.total_tokens, ms=res.ms)

        newly_rejected: list[str] = []
        for upd in res.parsed.get("hypothesis_updates", []):
            h = next((x for x in state["hypotheses"] if x["id"] == upd.get("id")), None)
            if h is None:
                continue
            cited = [ref_to_eid[r] for r in upd.get("based_on_refs", []) if r in ref_to_eid]
            if not cited:  # confidence may only move on cited evidence (PRD §5.2)
                continue
            old_conf, old_status = h["confidence"], h["status"]
            if upd.get("likelihood"):  # v2.0 Bayesian: posterior from prior × likelihood
                h["confidence"] = guards.bayesian_update(old_conf, upd["likelihood"])
            elif "new_confidence" in upd and upd["new_confidence"] is not None:
                h["confidence"] = max(0.0, min(1.0, float(upd["new_confidence"])))
            else:
                continue  # no confidence signal in this update
            if not guards.two_source_rule(h, state["evidence"]):
                # deterministic cap: no near-certainty without cross-source corroboration
                h["confidence"] = min(h["confidence"], 0.75)
            new_status = upd.get("new_status", h["status"])
            if new_status == "supported" and not guards.two_source_rule(h, state["evidence"]):
                new_status = "active"  # guard: two-source rule not met
            h["status"] = new_status
            if new_status == "rejected" and old_status != "rejected":
                newly_rejected.append(h["id"])
            self._trace("UPDT", {
                "code": f"{h['id']}  {old_conf:.2f} → {h['confidence']:.2f}",
                "text": f"{upd.get('note', '')} Based on {', '.join(cited)}.",
                "good": h["confidence"] >= old_conf,
            })

        self._apply_dependencies(state, newly_rejected)
        self._persist_hypotheses(state["hypotheses"])
        return state

    @staticmethod
    def _near_duplicate(snippet: str, source: str, evidence: list[dict]) -> str | None:
        """v5.0: is this snippet a near-duplicate of same-source evidence already on
        record? Token-set overlap (Jaccard ≥ 0.9, a cheap cosine proxy) so a rephrased
        one-line rant doesn't inflate the count. Returns the existing eid or None."""
        from echolens.textkit import tokenize
        a = set(tokenize(snippet))
        if len(a) < 3:
            return None
        for e in evidence:
            if e["source"] != source:
                continue
            b = set(tokenize(e["snippet"]))
            if not b:
                continue
            if len(a & b) / len(a | b) >= 0.9:
                return e["id"]
        return None

    def _apply_dependencies(self, state: InvState, newly_rejected: list[str]) -> None:
        """v2.0 hypothesis dependency tracking: when a competing hypothesis is
        rejected, hypotheses that named it in `boost_if_rejected` gain confidence
        (bounded, and never past the single-source clamp)."""
        if not newly_rejected:
            return
        for h in state["hypotheses"]:
            if h["status"] == "rejected":
                continue
            triggers = [r for r in h.get("boost_if_rejected", []) if r in newly_rejected]
            if not triggers:
                continue
            old = h["confidence"]
            h["confidence"] = min(1.0, h["confidence"] + 0.1 * len(triggers))
            if not guards.two_source_rule(h, state["evidence"]):
                h["confidence"] = min(h["confidence"], 0.75)
            if h["confidence"] != old:
                self._trace("UPDT", {
                    "code": f"{h['id']}  {old:.2f} → {h['confidence']:.2f}",
                    "text": f"Auto-boosted: it depended on {', '.join(triggers)} being false, and that was just rejected.",
                    "good": True,
                })

    def _check(self, state: InvState) -> InvState:
        self.budget.iterations += 1
        proposed = state.get("proposed")
        state["proposed"] = None  # explicit: absent keys keep their old channel value
        status, reason = "running", ""

        winner = guards.resolvable_hypothesis(state["hypotheses"], state["evidence"])
        if proposed:
            want = proposed.get("status")
            if want == "resolved":
                if winner:
                    status, reason = "resolved", proposed.get("reason", "")
                else:
                    self._trace("CHECK", {
                        "text": "Declared resolution REJECTED by guard: no hypothesis meets "
                                f"confidence ≥ {SUPPORT_CONFIDENCE} with the two-source rule. Continuing.",
                        "budget": self.budget.as_dict(),
                    })
            elif want in ("insufficient_evidence", "needs_human"):
                status, reason = want, proposed.get("reason", "")
        elif winner:
            status, reason = "resolved", f"{winner['id']} meets the two-source rule at {winner['confidence']:.2f}"

        if status == "running" and guards.conflicting_evidence(state["hypotheses"]):
            status, reason = "needs_human", "strong conflicting evidence on a live hypothesis"

        if status == "running":
            exhausted = guards.budget_exceeded(self.budget)
            if exhausted:
                best = guards.best_confidence(state["hypotheses"])
                # v2.0: if we're close, grant ONE capped extension instead of quitting.
                if not self.budget.extended and best >= EXTENSION_CONFIDENCE:
                    self.budget.extended = True
                    self.budget.extension_factor = EXTENSION_FACTOR
                    self._trace("CHECK", {
                        "text": f"Budget hit but best hypothesis is promising ({best:.2f} ≥ "
                                f"{EXTENSION_CONFIDENCE}); granting a one-time {int((EXTENSION_FACTOR - 1) * 100)}% "
                                "budget extension to try to close it.",
                        "budget": self.budget.as_dict(),
                    })
                else:
                    status, reason = guards.classify_end_state(state["hypotheses"])
                    reason += f" (budget exhausted: {', '.join(exhausted)})"

        if status == "resolved" and winner:
            # v5.0 counter-evidence duty: before confirming, actively try to REFUTE
            # the leading hypothesis. This turns the two-source rule adversarial and
            # is logged in the trace of every resolved investigation.
            if winner["id"] not in self._refuted:
                self._refuted.add(winner["id"])
                if self._attempt_refutation(winner):
                    status = "needs_human"
                    reason = "a refutation query surfaced counter-evidence against the leading cause"
            if status == "resolved":
                winner["status"] = "supported"
                self._persist_hypotheses(state["hypotheses"])

        state["status"] = status
        state["status_reason"] = reason
        self._trace("CHECK", {"text": f"iteration {self.budget.iterations} complete → {status}"
                                      + (f" ({reason})" if reason else ""),
                              "budget": self.budget.as_dict()})
        self.inv.budget_json = self.budget.as_dict()
        # v1.0 recovery: snapshot the loop state each iteration so a crash can resume.
        self.inv.checkpoint_json = {
            "hypotheses": state["hypotheses"],
            "evidence": state["evidence"],
            "trigger": state["trigger"],
            "budget": {"iterations": self.budget.iterations, "tool_calls": self.budget.tool_calls,
                       "tokens": self.budget.tokens, "cost_usd": self.budget.cost_usd,
                       "elapsed_s": self.budget.elapsed_s()},
            "executed_calls": sorted(self._executed_calls),
            "recent": self._recent[-6:],
        }
        self.session.flush()

        # v2.0 cooperative pause: if a human paused this case (set on another
        # connection), stop between iterations. The checkpoint above lets Resume
        # continue exactly where we left off — no finding is drafted.
        if status == "running":
            self.session.refresh(self.inv, ["paused"])
            if self.inv.paused:
                state["status"] = "paused"
                self._trace("CHECK", {"text": "Paused by reviewer — state checkpointed; resume to continue.",
                                      "budget": self.budget.as_dict()})
        return state

    def _attempt_refutation(self, winner: dict) -> bool:
        """v5.0: run one deterministic query that COULD disprove the leading
        hypothesis (does the effect ALSO show up where it shouldn't?). Logs a
        REFUTE trace step in every resolved investigation. Returns True if it
        surfaced real counter-evidence (→ the conclusion is downgraded)."""
        from echolens.impact import theme_terms
        from echolens.tools.compare_cohorts import compare_cohorts

        terms = theme_terms(self.anomaly, {"summary": winner["statement"], "prose": ""})
        query = " ".join(terms[:3]) or winner["statement"][:40]
        contradicted = False
        try:
            # scoped: another product's reviews must never be able to veto this
            # product's finding by flattening the cohort ratio
            res = compare_cohorts(self.session, term=query, dimension="version",
                                  product=self._product_name)
            ratio, exclusive, top = (res.get("highest_vs_next_ratio"),
                                     res.get("only_in_top_cohort"), res.get("highest_cohort"))
            if exclusive:
                detail = f"'{query}' appears only in {top} — a version-specific cause survives refutation."
            elif ratio is not None and ratio >= 1.5:
                detail = f"'{query}' is {ratio}× more common in {top} than the next version — cause survives refutation."
            elif ratio is not None:
                detail = (f"'{query}' is spread roughly evenly across versions (ratio {ratio}) — "
                          "this UNDERCUTS a version-specific cause.")
                contradicted = True
            else:
                detail = f"No cohort separation available for '{query}'; refutation inconclusive."
        except Exception as err:  # never let the adversarial check crash the run
            detail = f"refutation query failed ({err}); proceeding without it."
        self._trace("REFUTE", {
            "text": f"Attempted refutation of {winner['id']} — {detail}",
            "query": query, "hypothesis": winner["id"], "contradicted": contradicted,
        })
        return contradicted

    # ── persistence helpers ────────────────────────────────────────────

    def _persist_hypotheses(self, hypotheses: list[dict]) -> None:
        rows = {r.hid: r for r in self.session.query(HypothesisRow)
                .filter_by(investigation_id=self.inv.id)}
        for h in hypotheses:
            row = rows.get(h["id"])
            if row is None:
                row = HypothesisRow(investigation_id=self.inv.id, hid=h["id"])
                self.session.add(row)
            row.statement = h["statement"]
            row.confidence = h["confidence"]
            row.status = h["status"]
            row.json = {"evidence_for": h["evidence_for"],
                        "evidence_against": h["evidence_against"],
                        "next_test": h.get("next_test", "")}
        self.session.flush()

    # ── finalization ───────────────────────────────────────────────────

    def _draft_finding(self, state: InvState) -> dict:
        context = (
            f"OUTCOME: {state['status']} — {state['status_reason']}\n\n"
            f"ANOMALY:\n{json.dumps(state['trigger'])}\n\n"
            f"HYPOTHESES:\n{json.dumps(state['hypotheses'], indent=1)}\n\n"
            f"EVIDENCE:\n{json.dumps(state['evidence'], indent=1)}"
        )
        evidence_ids = {e["id"] for e in state["evidence"]}
        finding: dict | None = None
        for attempt in range(2):
            try:
                res = self.llm.complete_json(FINDING_SYSTEM, context, FINDING_SCHEMA, "investigator.finding")
            except LLMFormatError:
                break
            candidate = res.parsed
            violations = guards.unsupported_claims(candidate.get("prose", ""), evidence_ids)
            if not violations:
                finding = candidate
                break
            context += ("\n\nYOUR PREVIOUS DRAFT HAD UNCITED CAUSAL CLAIMS — every causal "
                        f"sentence must cite existing evidence ids inline: {violations}")
            finding = candidate | {"grounding_violations": violations}

        if finding is None:  # deterministic honest fallback, no causal claims
            finding = {
                "summary": f"Investigation ended: {state['status']}",
                "prose": f"Status: {state['status']}. {state['status_reason']}",
                "confidence": guards.best_confidence(state["hypotheses"]),
                "supported_hypothesis": None,
                "checked": sorted({e["source"] for e in state["evidence"]}),
                "what_would_settle_it": "Re-run with a larger budget or additional sources.",
            }
        if finding.get("grounding_violations") and state["status"] == "resolved":
            state["status"] = "needs_human"
            state["status_reason"] = "claim-grounding scan flagged uncited causal claims"
        return finding

    # ── run ────────────────────────────────────────────────────────────

    @classmethod
    def resume(cls, session: Session, investigation: Investigation, llm: LLMClient | None = None,
               on_step=None) -> Investigation:
        """Continue an interrupted investigation from its last checkpoint (v1.0)."""
        anomaly = session.get(AnomalyEvent, investigation.anomaly_id)
        inv = cls(session, anomaly, llm=llm, tier=investigation.budget_tier,
                  on_step=on_step, existing_investigation=investigation)
        ckpt = investigation.checkpoint_json or {}
        b = ckpt.get("budget", {})
        inv.budget.iterations = b.get("iterations", 0)
        inv.budget.tool_calls = b.get("tool_calls", 0)
        inv.budget.tokens = b.get("tokens", 0)
        inv.budget.cost_usd = b.get("cost_usd", 0.0)
        inv.budget.prior_elapsed_s = b.get("elapsed_s", 0.0)  # wall-clock survives restart
        inv._executed_calls = set(ckpt.get("executed_calls", []))
        inv._recent = list(ckpt.get("recent", []))
        inv._trace("THINK", {"text": f"Resumed after interruption at iteration {inv.budget.iterations}; "
                                     "restored hypotheses and evidence from checkpoint."})
        return inv.run(seed_state={
            "hypotheses": ckpt.get("hypotheses", []),
            "evidence": ckpt.get("evidence", []),
            "trigger": ckpt.get("trigger"),
        })

    def run(self, seed_state: dict | None = None) -> Investigation:
        self.budget.started_at = time.monotonic()
        graph = StateGraph(InvState)
        graph.add_node("plan", self._plan)
        graph.add_node("act", self._act)
        graph.add_node("delegate", self._delegate)
        graph.add_node("update", self._update)
        graph.add_node("check", self._check)
        graph.set_entry_point("plan")
        graph.add_conditional_edges(
            "plan",
            lambda s: "act" if s.get("pending_tool")
            else "delegate" if s.get("pending_delegate")
            else "check",
        )
        graph.add_edge("act", "update")
        graph.add_edge("delegate", "check")
        graph.add_edge("update", "check")
        graph.add_conditional_edges(
            "check", lambda s: END if s["status"] != "running" else "plan")

        from echolens.detector.detect import reference_now
        trigger = {
            "type": self.anomaly.type, "metric": self.anomaly.metric,
            "delta": self.anomaly.delta, "z": self.anomaly.z,
            "window": self.anomaly.window, "description": self.anomaly.description,
            # the reference date the agent reasons from = the latest data point, so
            # "complaints started 3 days ago" is correct on live data (not a frozen date).
            "today": reference_now(self.session).date().isoformat(),
        }
        if self.context_note:
            trigger["reviewer_challenge"] = self.context_note
            self._trace("THINK", {
                "text": f"Investigation re-opened by a human challenge: “{self.context_note}”. "
                        "I must address this specifically before concluding again.",
            })
        # v5.0: make the learned guidance visible in the trace (trust, not a hidden knob).
        if self._guidance:
            self._trace("THINK", {"text": "Applying guidance learned from past reviews:\n" + self._guidance})
        # v6.0: a regression/persist follow-up starts from prior context, not scratch.
        if getattr(self.anomaly, "parent_case_id", None):
            self._trace("THINK", {"text": f"Follow-up on case #{self.anomaly.parent_case_id} "
                                          "— starting from the prior investigation's context rather than scratch."})
        # v6.0: seed with a validated pattern if this anomaly matches one (a proven prior).
        if seed_state is None:
            from echolens.patterns import matching_pattern
            pat = matching_pattern(self.session, self.anomaly)
            if pat:
                trigger["matching_pattern"] = pat
                self._trace("THINK", {"text": f"This matches a pattern verified {pat['verified_count']}× "
                                              f"(cause: {pat['cause']} → fix that worked: {pat['fix']}). "
                                              "Testing that hypothesis first before exploring alternatives."})
        # v2.0 cross-investigation memory: seed with related past confirmed causes.
        if seed_state is None:
            from echolens.investigator.memory import digest_text
            prior = digest_text(self.session, self.anomaly, exclude_investigation_id=self.inv.id)
            if prior:
                trigger["prior_findings"] = prior
                self._trace("THINK", {"text": "Recalled related past cases:\n" + prior})
        init: InvState = {
            "trigger": (seed_state or {}).get("trigger") or trigger,
            "hypotheses": (seed_state or {}).get("hypotheses", []),
            "evidence": (seed_state or {}).get("evidence", []),
            "status": "running",
            "status_reason": "", "finding": None, "pending_tool": None,
            "pending_delegate": None, "last_tool": None,
        }
        final: InvState = graph.compile().invoke(init, config={"recursion_limit": 400})

        # Paused mid-loop: leave it resumable (status stays running), no finding.
        if final["status"] == "paused":
            self.inv.status = "running"
            self.inv.budget_json = self.budget.as_dict()
            self.session.flush()
            self._final_state = final
            return self.inv

        finding = self._draft_finding(final)
        try:  # v4.0 impact quantification — deterministic, never fail the run over it
            from echolens.impact import quantify
            finding["impact"] = quantify(self.session, self.anomaly, finding)
        except Exception as err:
            log.error("impact_quantify_failed", error=str(err))
        final["finding"] = finding
        self.session.add(Finding(
            investigation_id=self.inv.id,
            summary=finding.get("summary", ""),
            confidence=float(finding.get("confidence", 0.0)),
            status="draft",
            json=finding,
            product_id=self.inv.product_id,
        ))
        self.inv.status = final["status"]
        self.inv.budget_json = self.budget.as_dict()
        self.inv.resolved_at = datetime.now(timezone.utc)
        # Only a resolved case is truly closed; needs_human / insufficient_evidence
        # keep their outcome as the anomaly status so they still read as open work.
        self.anomaly.status = "closed" if final["status"] == "resolved" else final["status"]
        self.session.flush()
        self._final_state = final
        return self.inv
