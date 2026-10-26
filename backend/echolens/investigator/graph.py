"""The Investigator: a LangGraph state machine looping
plan → act → update → check until resolved / honest failure / budget out.

Agents decide (plan, update); tools execute (act); guards enforce (check).
Every step is persisted as a trace_steps row (THINK/TOOL/EVID/UPDT/FAIL/CHECK)
— the live UI streams that table verbatim.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Callable

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.config import (
    MAX_ACTIVE_HYPOTHESES,
    SEEDED_PRIOR_CONFIDENCE,
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
from echolens.llm.client import LLMClient, LLMError
from echolens.logging import get_logger
from echolens.textkit import clean_headline
from echolens.tools.registry import TOOLS, run_tool

log = get_logger("investigator")

# v15: the reviewer-granted budget fields, checkpointed and restored together.
_GRANT_FIELDS = ("extra_iterations", "extra_tool_calls", "extra_tokens",
                 "extra_cost_usd", "extra_wall_s", "human_extensions",
                 "auto_extensions", "cost_ceiling_usd", "wall_ceiling_s")


def _budget_grants(budget: Budget) -> dict:
    return {k: getattr(budget, k) for k in _GRANT_FIELDS}


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


def _items_by_ref(node, out: dict | None = None) -> dict[str, dict]:
    """Each `ref` in a tool result mapped to the item that carries it, so intake
    can judge a quote by what the TOOL returned (its rating, its full snippet),
    not by the excerpt the assessor chose to copy."""
    out = {} if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("ref"), str):
            out.setdefault(node["ref"], node)
        for v in node.values():
            _items_by_ref(v, out)
    elif isinstance(node, list):
        for item in node:
            _items_by_ref(item, out)
    return out


# Kept on each evidence item so the single-channel rule can count days,
# versions and release timing without re-querying.
_META_KEYS = ("rating", "date", "version", "released_at", "pr")

# A cause that names a build. "Complaints hit every version at once" is what a
# server-side outage looks like — and exactly what refutes a build-specific cause.
_NAMES_A_VERSION = re.compile(r"\bv?\d+\.\d+|\b(?:release|version|build)\b", re.IGNORECASE)


def _as_ids(value) -> list[str]:
    """A model may send `"supports": "H1"`; iterating that string yielded 'H'
    and '1', silently losing the evidence→hypothesis link."""
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value if v is not None]


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
        self._release_dates_cache: dict[str, str] | None = None
        self._temporal_logged: set[tuple] = set()
        # v5.0 trust loop: past human verdicts (calibration + weak spots) become a
        # corrective note injected into this investigation's planning prompt.
        try:
            from echolens.calibration import guidance_text
            self._guidance = guidance_text(session, getattr(anomaly, "product_id", None))
        except Exception:
            self._guidance = ""

        self._owns_llm = llm is None
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
        # How many feedback channels this product has connected. Exactly one
        # makes it a single-channel product: the two-source rule cannot be met
        # by definition, so the only available answer is the labelled, capped
        # "supported (single channel)" — and a release note no longer passes
        # for a second channel. Unknown (no collectors, e.g. the synthetic
        # demo) keeps today's rule exactly.
        self._single_channel = len(self._connected_channels()) == 1
        self._ignore_sources = (guards.SINGLE_CHANNEL_NON_FEEDBACK
                                if self._single_channel else frozenset())

    def _connected_channels(self) -> set[str]:
        from echolens.db.models import CollectorState
        pid, name = getattr(self.inv, "product_id", None), self._product_name
        if pid is None and not name:
            return set()
        scope = []
        if pid is not None:
            scope.append(CollectorState.product_id == pid)
        if name:
            scope.append(CollectorState.product == name)
        from sqlalchemy import or_
        rows = self.session.scalars(select(CollectorState.source).where(
            CollectorState.enabled == True, or_(*scope))).all()  # noqa: E712
        return {str(s).strip().lower() for s in rows if s}

    def _resolve_product_name(self) -> str | None:
        """Display name of this case's product — the value stamped on corpus rows.
        None on a pre-v8 / unscoped case, which reads the whole corpus as before."""
        pid = getattr(self.inv, "product_id", None)
        if pid is None:
            return None
        from echolens.db.models import Product
        product = self.session.get(Product, pid)
        return product.name if product is not None else None

    def _release_dates(self) -> dict[str, str]:
        """{version: release day} for this product, read once per run, so the
        temporal-order guard can date a version the hypothesis only names."""
        if self._release_dates_cache is None:
            from echolens.db.models import Release
            stmt = select(Release.version, Release.released_at)
            if self._product_name:
                stmt = stmt.where(Release.product == self._product_name)
            self._release_dates_cache = {
                v: at.date().isoformat() for v, at in self.session.execute(stmt).all() if at}
        return self._release_dates_cache

    def _temporally_blocked(self, h: dict, evidence: list[dict]) -> bool:
        """Temporal-order guard: True when `h` blames a release that shipped after
        its first cited complaint. Logged once per (hypothesis, release, date)
        as a REFUTE step naming both dates."""
        hit = guards.temporal_order_violation(h, evidence, self._release_dates())
        if hit is None:
            return False
        key = (h["id"], hit["release"], hit["first_complaint"])
        if key not in self._temporal_logged:
            self._temporal_logged.add(key)
            self._trace("REFUTE", {
                "guard": "temporal_order", "hypothesis": h["id"], "contradicted": True,
                "release": hit["release"], "release_date": hit["release_date"],
                "first_complaint": hit["first_complaint"], "complaint_id": hit["complaint_id"],
                "text": (f"Temporal-order guard: {h['id']} blames {hit['release']}, released "
                         f"{hit['release_date']}, but the first cited complaint "
                         f"({hit['complaint_id']}) is from {hit['first_complaint']}. A release "
                         "cannot cause complaints that began before it shipped, so "
                         f"{h['id']} cannot be supported."),
            })
        return True

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
        try:
            self.session.commit()
        except Exception as err:
            self.session.rollback()
            log.warning("trace_commit_failed", investigation=self.inv.id,
                        seq=self._seq, error=f"{type(err).__name__}: {err}")
        summary = content.get("text") or content.get("code") or json.dumps(content)[:120]
        self._recent.append(f"[{kind}] {summary[:160]}")
        self.on_step(kind, content)

    # ── nodes ──────────────────────────────────────────────────────────

    def _automatic_budget_stop(self, state: InvState) -> bool:
        if not self.budget.auto_extensions:
            return False
        from echolens.investigator.recover import auto_budget_room
        room = auto_budget_room(self.session, self.inv, self.budget)
        if room["cost_ceiling_usd"] > 0:
            self.budget.cost_ceiling_usd = min(self.budget.cost_ceiling_usd, room["cost_ceiling_usd"])
        reason = room["reason"] or ", ".join(guards.budget_exceeded(self.budget))
        if not reason:
            return False
        state["over_budget"], state["budget_stop_reason"] = True, reason
        return True

    def _plan(self, state: InvState) -> InvState:
        state["pending_tool"] = None
        state["pending_delegate"] = None
        # PRE-FLIGHT. The caps were consulted only in _check, at the END of a
        # plan->act->update cycle, so a run sitting at 119k/120k tokens still
        # executed a full iteration — two LLM calls and a tool result — and the
        # cap was merely OBSERVED to be blown afterwards, by an unbounded margin.
        # Refusing here means the ceiling is enforced rather than recorded.
        if self._automatic_budget_stop(state):
            return state
        if guards.budget_exceeded(self.budget):
            state["over_budget"] = True
            return state
        prompt = render_state(
            state["trigger"], state["hypotheses"],
            [{k: e[k] for k in ("id", "source", "ref", "snippet", "supports", "contradicts")}
             for e in state["evidence"]],
            self.budget.as_dict(), self._recent,
        )
        try:
            res = self.llm.complete_json(plan_system(self._guidance), prompt, PLAN_SCHEMA, "investigator.plan")
        except LLMError as err:
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
        if self._automatic_budget_stop(state):
            return state
        """v2.0: run a single-pass specialist and fold its analysis into the
        investigator's context (not as evidence — analysis only)."""
        from echolens.investigator.specialists import run_specialist

        deleg = state.get("pending_delegate") or {}
        state["pending_delegate"] = None
        name = deleg.get("specialist")
        focus = deleg.get("focus", "")
        # Delegation is WORK and must be charged for. _specialist_context runs up
        # to three full corpus queries and run_specialist makes an LLM call, none
        # of which touched tool_calls — so a model that chose "delegate" every
        # step burned the whole run while the budget reported tool_calls 0/20,
        # the one number a reader takes as "how much work did this do".
        self.budget.tool_calls += 1
        if guards.budget_exceeded(self.budget):
            self._trace("CHECK", {"text": f"Skipped {name}: no budget left to delegate."})
            return state
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

    def _next_eid(self, state: InvState) -> str:
        """Next free evidence id. `len(evidence) + 1` collided after a resume
        whose checkpoint predated rows already written for this case, so two
        different items shared one id. Take the max of state AND the DB."""
        used = [e["id"] for e in state["evidence"]]
        used += self.session.scalars(select(EvidenceRow.eid).where(
            EvidenceRow.investigation_id == self.inv.id)).all()
        nums = [int(u[3:]) for u in used if isinstance(u, str) and u[3:].isdigit()]
        return f"ev_{max(nums, default=0) + 1:03d}"

    def _apply_hypothesis_revision(self, state: InvState, proposed: list[dict]) -> list[dict]:
        existing = {h["id"]: h for h in state["hypotheses"]}
        by_statement = {
            (h.get("statement") or "").strip().lower(): h
            for h in state["hypotheses"] if (h.get("statement") or "").strip()
        }
        relevant = [p for p in proposed if guards.hypothesis_relevant(p, state.get("trigger", {}))]
        discarded = len(proposed) - len(relevant)
        if discarded:
            self._trace("CHECK", {
                "text": (f"Discarded {discarded} off-topic hypothesis proposal(s): each hypothesis "
                         "must stay connected to the detected customer problem."),
            })
        # A revision is meant to contain the full list, but model omissions and
        # rejected off-topic replacements must never erase an accepted
        # hypothesis (or its evidence) from loop state while leaving the DB row
        # alive. Preserve existing rows unless a relevant proposal explicitly
        # updates the same id or statement.
        represented = {
            (existing.get(p.get("id")) or
             by_statement.get((p.get("statement") or "").strip().lower()) or {}).get("id")
            for p in relevant
        }
        proposed = [h for h in state["hypotheses"] if h["id"] not in represented] + relevant
        merged: list[dict] = []
        active = 0
        # Fall back to matching on the STATEMENT when an id is new. The prompt
        # asks for "the FULL revised list", so a model renumbering H2 -> H3 is
        # realistic — and `existing.get(hid, {})` then returned {} and silently
        # dropped every accumulated evidence link. The evidence rows survived in
        # state and in the DB, but the hypothesis no longer cited them, so
        # two_source_rule saw zero items and it could never resolve.
        for p in proposed:
            hid = p.get("id") or f"H{len(merged) + 1}"
            if any(m["id"] == hid for m in merged):
                continue  # a repeated id in one revision is the same hypothesis
            statement = p.get("statement", "")
            old = existing.get(hid) or by_statement.get(statement.strip().lower(), {})
            status = p.get("status", "active")
            if status in ("supported", guards.SINGLE_CHANNEL_STATUS):  # only the check guard grants these
                status = "active"
            if status == "active":
                active += 1
                if active > MAX_ACTIVE_HYPOTHESES:
                    # Park it, do not DELETE it. `continue` skipped the append
                    # entirely, so a 5th active hypothesis that had already
                    # accumulated evidence vanished from loop state — while
                    # _persist_hypotheses only ever updates or inserts, leaving
                    # a stale DB row that then diverged permanently.
                    status = "parked"
            merged.append({
                "id": hid,
                "statement": p.get("statement", old.get("statement", "")),
                "confidence": max(0.0, min(1.0, float(p.get("confidence", old.get("confidence", 0.5))))),
                "status": status,
                # Copies, never the shared list: two proposals that matched the
                # same `old` used to alias one list, so evidence cited for one
                # hypothesis silently counted toward the other's two-source rule.
                "evidence_for": list(old.get("evidence_for", [])),
                "evidence_against": list(old.get("evidence_against", [])),
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
        if self._automatic_budget_stop(state):
            return state
        last = state.get("last_tool")
        state["last_tool"] = None
        if not last:
            return state
        # PRE-FLIGHT, as in _plan. This node makes the LARGEST call in the loop —
        # its prompt carries the full serialized tool result — and it was
        # unguarded, so a run that passed the _plan check and then spent its
        # remaining budget on the plan call and the tool would still make this
        # one. Measured overshoot on tier `quick` (50k cap): 2.4x at 20k/call,
        # 5.4x at 45k/call. The tool result is already recorded in the trace, so
        # stopping here loses the assessment, not the evidence.
        if guards.budget_exceeded(self.budget):
            state["over_budget"] = True
            self._trace("CHECK", {"code": "budget", "text":
                                  "Budget reached before assessing the tool result; "
                                  "it stays in the trace un-assessed."})
            return state
        prompt = (
            f"HYPOTHESES:\n{json.dumps(state['hypotheses'], indent=1)}\n\n"
            f"TOOL CALL (testing {last.get('tests_hypothesis')}):\n"
            f"{last['name']}({json.dumps(last['args'], default=str)})\n\n"
            f"TOOL RESULT:\n{json.dumps(last['result'], default=str)}"
        )
        try:
            res = self.llm.complete_json(UPDATE_SYSTEM, prompt, UPDATE_SCHEMA, "investigator.update")
        except LLMError as err:
            self._trace("FAIL", {"code": "update", "error": str(err),
                                 "text": "Evidence assessment failed; result kept in trace only."})
            return state

        valid_refs = _collect_refs(last["result"])
        by_ref = _items_by_ref(last["result"])
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
            supports = [h for h in _as_ids(item.get("supports")) if h in known_h]
            contradicts = [h for h in _as_ids(item.get("contradicts")) if h in known_h]
            found = by_ref.get(ref) or {}
            # A happy review cannot support a problem. Judged on the tool's own
            # copy of the review (rating + text), so the assessor cannot make
            # it qualify by excerpting the one negative-sounding clause.
            if (supports and source in guards.REVIEW_SOURCES
                    and guards.positive_without_complaint(found.get("snippet"), found.get("rating"))):
                self._trace("FAIL", {
                    "code": f"evidence ref '{ref}'",
                    "error": f"{found.get('rating')}★ review with no complaint cue cited as support "
                             f"for {', '.join(supports)}",
                    "text": ("Not accepted as SUPPORTING evidence: a positive review that "
                             "describes no problem cannot support a problem hypothesis."
                             + (" Kept as counter-evidence only." if contradicts else "")),
                })
                supports = []
                if not contradicts:
                    continue
            dup = self._near_duplicate(item.get("snippet", ""), source, state["evidence"])
            if dup:  # v5.0 quality: near-identical evidence merges, never double-counts
                ref_to_eid[ref] = dup
                self._trace("EVID", {"id": dup, "source": source.upper(), "ref": ref,
                                     "text": f"(merged) near-duplicate of {dup}; counted once, not twice.",
                                     "supports": [], "contradicts": []})
                continue
            eid = self._next_eid(state)
            ev = {
                "id": eid, "source": source, "ref": ref,
                "snippet": str(item.get("snippet") or "")[:400], "retrieved_by": retrieved_by,
                "supports": supports,
                "contradicts": contradicts,
            }
            meta = {k: found[k] for k in _META_KEYS if found.get(k) is not None}
            if meta:
                ev["meta"] = meta
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
                json={"supports": ev["supports"], "contradicts": ev["contradicts"],
                      **({"meta": ev["meta"]} if ev.get("meta") else {})},
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
            cited = guards.dedupe_refs(
                [ref_to_eid[r] for r in upd.get("based_on_refs", []) if r in ref_to_eid])
            if not cited:  # confidence may only move on cited evidence (PRD §5.2)
                continue
            old_conf, old_status = h["confidence"], h["status"]
            if upd.get("likelihood"):  # v2.0 Bayesian: posterior from prior × likelihood
                h["confidence"] = guards.bayesian_update(old_conf, upd["likelihood"])
            elif "new_confidence" in upd and upd["new_confidence"] is not None:
                h["confidence"] = max(0.0, min(1.0, float(upd["new_confidence"])))
            else:
                continue  # no confidence signal in this update
            corroborated = guards.two_source_rule(h, state["evidence"], self._ignore_sources)
            if not corroborated:
                # deterministic cap: no near-certainty without cross-source corroboration
                h["confidence"] = min(h["confidence"], 0.75)
            new_status = upd.get("new_status", h["status"])
            if new_status == "supported" and not corroborated:
                new_status = "active"  # guard: two-source rule not met
            if new_status == "supported" and self._temporally_blocked(h, state["evidence"]):
                new_status = "active"  # guard: the blamed release came after the complaints
            if new_status == guards.SINGLE_CHANNEL_STATUS:
                new_status = "active"  # only the check guard can grant it
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
        one-line rant doesn't inflate the count. Returns the existing eid or None.

        An EXACT (normalised) repeat from the same source merges whatever its
        length. The Jaccard check skips snippets under three tokens — too short to
        judge similarity — and that exemption let "It works fine, no complaints"
        (two tokens once stopwords go) be cited twice as two data points."""
        from echolens.textkit import tokenize
        exact = guards.normalise_quote(snippet)
        if exact:
            for e in evidence:
                if e["source"] == source and guards.normalise_quote(e["snippet"]) == exact:
                    return e["id"]
        a = set(tokenize(snippet))
        if len(a) < 3:
            return None
        for e in evidence:
            # Same-source only, deliberately. MERGING across sources would be
            # worse than the bug: it discards the second channel entirely and
            # destroys the corroboration signal the two-source rule depends on.
            # The real risk — one person cross-posting the same text — is
            # handled in two_source_rule, which now requires the copies to be
            # textually distinct as well as differently-sourced.
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
            if not guards.two_source_rule(h, state["evidence"], self._ignore_sources):
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
        if state.get("budget_stop_reason"):
            status, reason = "budget_exhausted", state["budget_stop_reason"]

        # A hypothesis blaming a release that shipped after its first complaint
        # is out of the running for either kind of support.
        eligible = []
        for h in state["hypotheses"]:
            if h["status"] not in ("rejected", "parked") and self._temporally_blocked(h, state["evidence"]):
                if h["status"] in ("supported", guards.SINGLE_CHANNEL_STATUS):
                    h["status"] = "active"   # later evidence dated it; support withdrawn
                    self._persist_hypotheses(state["hypotheses"])
                continue
            eligible.append(h)
        winner = guards.resolvable_hypothesis(eligible, state["evidence"],
                                              self._ignore_sources)
        # The full bar is out of reach on a single-channel product; the
        # stricter within-channel bar can still yield the LABELLED outcome.
        single = None
        if winner is None and self._single_channel:
            single = guards.single_channel_winner(eligible, state["evidence"])
            if single:
                winner = single[0]
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
        elif single:
            status, reason = "resolved", (f"{winner['id']} is {guards.SINGLE_CHANNEL_LABEL.lower()} "
                                          f"at {winner['confidence']:.2f}: {single[1]}")
        elif winner:
            status, reason = "resolved", f"{winner['id']} meets the two-source rule at {winner['confidence']:.2f}"

        if status == "running" and guards.conflicting_evidence(state["hypotheses"]):
            status, reason = "needs_human", "strong conflicting evidence on a live hypothesis"

        if status == "running":
            exhausted = guards.budget_exceeded(self.budget)
            if exhausted:
                best = guards.best_confidence(state["hypotheses"])
                status, reason = guards.classify_end_state(state["hypotheses"])
                if status == "needs_human":
                    status = "budget_exhausted"
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
            if status == "resolved" and single:
                # A distinct status and a hard cap — never the full "supported".
                winner["status"] = guards.SINGLE_CHANNEL_STATUS
                winner["confidence"] = min(winner["confidence"], guards.SINGLE_CHANNEL_CONFIDENCE_CAP)
                if "single channel" not in reason:
                    reason = f"{guards.SINGLE_CHANNEL_LABEL.lower()}: {single[1]}. {reason}".strip()
                self._trace("CHECK", {"text": (
                    f"{guards.SINGLE_CHANNEL_LABEL}: only one feedback channel is connected, so "
                    f"{winner['id']} cannot be corroborated independently. It meets the "
                    f"within-channel bar ({single[1]}); confidence capped at "
                    f"{guards.SINGLE_CHANNEL_CONFIDENCE_CAP:.2f}.")})
                self._persist_hypotheses(state["hypotheses"])
            elif status == "resolved":
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
            # `extended`/`extension_factor` MUST be checkpointed. Without them a
            # resumed run restored a budget already at the extended ceiling but
            # flagged un-extended, so the one-time 50% extension was granted
            # again on every resume — and resume_running() fires on every app
            # start, so a crash-loop during a deploy granted it without limit.
            "budget": {"iterations": self.budget.iterations, "tool_calls": self.budget.tool_calls,
                       "tokens": self.budget.tokens, "cost_usd": self.budget.cost_usd,
                       "elapsed_s": self.budget.elapsed_s(),
                       "extended": self.budget.extended,
                       "extension_factor": self.budget.extension_factor,
                       # v15: reviewer-granted headroom must survive the next
                       # checkpoint, or a crash mid-extension would silently
                       # take back what the human granted (and the per-case
                       # grant cap could be reset by a restart).
                       **_budget_grants(self.budget)},
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
                onset = self._simultaneous_onset(query)
                if onset and not _NAMES_A_VERSION.search(winner["statement"]):
                    # An outage hits every installed version on the same day, so
                    # an even spread is its signature, not a contradiction.
                    detail = (f"'{query}' is spread evenly across versions (ratio {ratio}), but it "
                              f"began on {onset['date']} on {onset['versions_with_onset']} of "
                              f"{onset['versions_active']} active versions within 48 h (each at "
                              "≥3× its prior daily rate). All versions at once is what a "
                              "server-side or back-end cause looks like, so the spread does NOT "
                              "undercut it — cause survives refutation.")
                elif onset:
                    detail = (f"'{query}' began on {onset['date']} on {onset['versions_with_onset']} of "
                              f"{onset['versions_active']} active versions at once — the signature of a "
                              "server-side cause, which UNDERCUTS a cause tied to one build.")
                    contradicted = True
                else:
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

    def _simultaneous_onset(self, term: str) -> dict | None:
        """tools/onset.py's verdict when it says simultaneous, else None. Any
        failure is None: the refutation then behaves exactly as it did."""
        from echolens.tools.onset import simultaneous_onset
        try:
            res = simultaneous_onset(self.session, term=term, product=self._product_name)
        except Exception as err:
            log.warning("onset_check_failed", error=str(err))
            return None
        return res if res.get("simultaneous") else None

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
            # The RETRY is discretionary and must respect the budget. The first
            # attempt is not: a case that spent its budget still owes the user an
            # answer, and refusing to draft one would turn every exhausted run
            # into a blank. But the second attempt is an optional improvement, so
            # it only happens if there is still budget for it — this call carries
            # the largest prompt in the run (full hypotheses + full evidence) and
            # used to fire unconditionally after the caps were already blown.
            if self.budget.auto_extensions and self._automatic_budget_stop(state):
                break
            if attempt > 0 and guards.budget_exceeded(self.budget):
                break
            try:
                res = self.llm.complete_json(FINDING_SYSTEM, context, FINDING_SCHEMA, "investigator.finding")
            except LLMError:
                break
            candidate = dict(res.parsed)
            corpus = " ".join(str(e.get("snippet", "")) for e in state["evidence"])
            candidate["summary"] = guards.tidy_summary(candidate.get("summary", ""))
            candidate["prose"] = guards.unseen_code_spans(
                guards.tidy_prose(candidate.get("prose", "")), corpus)
            violations = guards.unsupported_claims(candidate.get("prose", ""), evidence_ids)
            if not violations:
                finding = candidate
                break
            context += ("\n\nYOUR PREVIOUS DRAFT HAD UNCITED CAUSAL CLAIMS — every causal "
                        f"sentence must cite existing evidence ids inline: {violations}")
            finding = candidate | {"grounding_violations": violations}

        # An ungrounded draft is NOT publishable. Previously the last failing
        # candidate was kept and returned, so its uncited causal prose reached
        # the reviewer verbatim — and the only consequence was a status downgrade
        # gated on `status == "resolved"`, meaning a case already ending in
        # needs_human or insufficient_evidence published the violation with no
        # consequence at all. The violation marker was also never rendered.
        # Governing rule 2 is "no causal claim without an evidence chain"; a
        # guard that detects a violation and publishes it anyway is not a guard.
        violations = finding.get("grounding_violations") if finding else None
        if violations:
            # Partial publication first: drop only the uncited sentences. If what
            # is left still cites real evidence it is published, and the dropped
            # claims travel beside it under an explicit "not yet supported" label
            # — never in the prose, never as a conclusion. Only when nothing
            # grounded survives does the whole finding stay blocked, as before.
            kept, removed, grounded = guards.strip_ungrounded(finding.get("prose", ""), evidence_ids)
            if grounded:
                finding = {k: v for k, v in finding.items() if k != "grounding_violations"}
                finding["prose"] = kept
                finding["working_hypotheses"] = removed
                finding["working_hypothesis_label"] = guards.WORKING_HYPOTHESIS_LABEL
                self._trace("CHECK", {"text": (
                    f"Claim-grounding scan removed {len(removed)} uncited causal "
                    f"sentence{'s' if len(removed) != 1 else ''} from the finding. The rest is "
                    "grounded and published; the removed claims are shown separately as a "
                    "working hypothesis, not as conclusions.")})
                violations = None
        if violations:
            state["status"] = "needs_human"
            state["status_reason"] = "claim-grounding scan flagged uncited causal claims"
            finding = {
                "summary": (finding or {}).get("summary", "Cause could not be stated with evidence"),
                # The rejected prose is preserved for audit but is NOT the finding.
                "prose": ("A cause was drafted but could not be tied to specific evidence, so it "
                          "is not being presented as a conclusion. The reasoning trace and the "
                          "evidence below show what was actually established."),
                "confidence": guards.best_confidence(state["hypotheses"]),
                "supported_hypothesis": None,
                "checked": sorted({e["source"] for e in state["evidence"]}),
                "what_would_settle_it": ("Evidence directly linking the proposed cause to the "
                                         "symptom — the draft asserted it without a citation."),
                "grounding_violations": violations,
                "rejected_draft": (finding or {}).get("prose", ""),
            }
        elif finding is None:  # deterministic honest fallback, no causal claims
            finding = {
                "summary": f"Investigation ended: {state['status']}",
                "prose": f"Status: {state['status']}. {state['status_reason']}",
                "confidence": guards.best_confidence(state["hypotheses"]),
                "supported_hypothesis": None,
                "checked": sorted({e["source"] for e in state["evidence"]}),
                "what_would_settle_it": "Re-run with a larger budget or additional sources.",
            }
        return self._label_support(state, finding)

    def _label_support(self, state: InvState, finding: dict) -> dict:
        """Say in the payload HOW STRONGLY the cause is supported. A
        single-channel answer must never read as the full one, whatever the
        drafted text says, so the label and the cap are applied here in code."""
        if state["status"] != "resolved":
            return finding
        single = next((h for h in state["hypotheses"]
                       if h["status"] == guards.SINGLE_CHANNEL_STATUS), None)
        if single is None:
            if any(h["status"] == "supported" for h in state["hypotheses"]):
                finding["support_level"] = "supported"
            return finding
        basis = guards.single_channel_support(single, state["evidence"]) or "within-channel bar met"
        cap = guards.SINGLE_CHANNEL_CONFIDENCE_CAP
        finding["support_level"] = "single_channel"
        finding["support_label"] = guards.SINGLE_CHANNEL_LABEL
        finding["support_basis"] = basis
        finding["single_channel_note"] = (
            "Only one feedback channel is connected for this product, so this cause could not be "
            f"corroborated by an independent source. It rests on {basis}.")
        finding["confidence"] = min(float(finding.get("confidence") or single["confidence"]), cap)
        if not finding.get("supported_hypothesis"):
            finding["supported_hypothesis"] = single["id"]
        return finding

    # ── run ────────────────────────────────────────────────────────────

    @classmethod
    def resume(cls, session: Session, investigation: Investigation, llm: LLMClient | None = None,
               on_step=None, reason: str | None = None) -> Investigation:
        """Continue an interrupted investigation from its last checkpoint (v1.0).

        `reason` replaces the default trace line — a reviewer-granted extension
        (v15) is not an "interruption" and the trace must not call it one."""
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
        inv.budget.extended = bool(b.get("extended", False))
        inv.budget.extension_factor = float(b.get("extension_factor", 1.0))
        for k in _GRANT_FIELDS:
            default = getattr(inv.budget, k)
            setattr(inv.budget, k, type(default)(b.get(k, default) or 0))
        inv._executed_calls = set(ckpt.get("executed_calls", []))
        inv._recent = list(ckpt.get("recent", []))
        inv._trace("THINK", {"text": reason or (
            f"Resumed after interruption at iteration {inv.budget.iterations}; "
            "restored hypotheses and evidence from checkpoint.")})
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
            lambda s: "check" if s.get("over_budget")
            else "act" if s.get("pending_tool")
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
        if self._single_channel:
            trigger["single_channel"] = True
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
        seeded_hypotheses: list[dict] = []
        if seed_state is None:
            from echolens.patterns import matching_pattern
            pat = matching_pattern(self.session, self.anomaly)
            if pat:
                trigger["matching_pattern"] = pat
                if pat.get("cross_product"):
                    # v9.0 portfolio transfer: knowledge earned on one product is a
                    # place to look first on another — never a conclusion. It still
                    # has to clear the same two-source bar on THIS product's data.
                    self._trace("THINK", {
                        "text": f"This caused “{pat['cause']}” on {pat['from_product']}, where the "
                                f"fix was verified {pat['verified_count']}× — testing it here first. "
                                "Borrowed priors carry no evidence weight: it must be proven again "
                                "on this product's own data.",
                    })
                else:
                    self._trace("THINK", {"text": f"This matches a pattern verified {pat['verified_count']}× "
                                                  f"(cause: {pat['cause']} → fix that worked: {pat['fix']}). "
                                                  "Testing that hypothesis first before exploring alternatives."})
                # The shortcut is STRUCTURAL, not a suggestion in the prompt: the
                # loop starts with the proven cause already on the board, so it
                # skips the cold-start hypothesis-generation iteration.
                seeded_hypotheses = [{
                    "id": "H1",
                    "statement": pat["cause"] or f"the {pat['trigger']} pattern recurs here",
                    "confidence": SEEDED_PRIOR_CONFIDENCE,
                    "status": "active",
                    "evidence_for": [], "evidence_against": [],
                    "next_test": f"look for {', '.join(pat['terms'][:3])} in this product's own data",
                    "boost_if_rejected": [],
                }]
                self._persist_hypotheses(seeded_hypotheses)
                self.inv.seeded_from_pattern = {
                    "cause": pat["cause"], "fix": pat["fix"], "terms": pat["terms"],
                    "verified_count": pat["verified_count"],
                    "cross_product": bool(pat.get("cross_product")),
                    "from_product": pat.get("from_product"),
                }
        # v2.0 cross-investigation memory: seed with related past confirmed causes.
        if seed_state is None:
            from echolens.investigator.memory import digest_text
            prior = digest_text(self.session, self.anomaly, exclude_investigation_id=self.inv.id)
            if prior:
                trigger["prior_findings"] = prior
                self._trace("THINK", {"text": "Recalled related past cases:\n" + prior})
        init: InvState = {
            "trigger": (seed_state or {}).get("trigger") or trigger,
            "hypotheses": (seed_state or {}).get("hypotheses") or seeded_hypotheses,
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
        # The summary is the case's headline everywhere it is shown (cards,
        # briefs, Slack, email), so it is stored clean: no [ev_…] tags, no
        # "V3.2.0". The prose keeps its citations.
        if "summary" in finding:
            finding["summary"] = clean_headline(finding["summary"])
        try:  # v4.0 impact quantification — deterministic, never fail the run over it
            from echolens.impact import quantify
            # Scoped. This omitted `product`, so impact was quantified over the
            # WHOLE corpus — every other product's reviews included — while the
            # class docstring above promises "an investigation may only read ITS
            # product's corpus". impact_score drives severity, alert routing and
            # backlog rank, so a busy neighbour distorted this product's numbers.
            finding["impact"] = quantify(self.session, self.anomaly, finding,
                                         product=self._product_name)
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
        # Drafting can add spend after the last loop checkpoint. Preserve it
        # before considering a grant so it cannot be taken back on resume.
        ckpt = dict(self.inv.checkpoint_json or {})
        ckpt["budget"] = {**ckpt.get("budget", {}), "tokens": self.budget.tokens,
                          "cost_usd": self.budget.cost_usd, "elapsed_s": self.budget.elapsed_s()}
        self.inv.checkpoint_json = ckpt
        self.session.flush()
        self._final_state = final
        if final["status"] == "budget_exhausted":
            from echolens.investigator.recover import automatic_extension_offer, grant_extension
            offer = automatic_extension_offer(self.session, self.inv)
            if offer["eligible"]:
                try:
                    granted = grant_extension(self.session, self.inv, by="auto")
                except ValueError as err:
                    self._trace("CHECK", {"text": f"Automatic extension not granted: {err}."})
                    return self.inv
                return Investigator.resume(self.session, self.inv,
                    llm=None if self._owns_llm else self.llm, on_step=self.on_step,
                    reason=f"Automatic +{granted['steps']} steps: {offer['reason']}.")
            self._trace("CHECK", {"text": f"Automatic extension not granted: {offer['reason']}."})
        return self.inv
