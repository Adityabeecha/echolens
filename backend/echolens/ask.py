from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from echolens.db.models import Finding, Investigation
from echolens.llm.client import LLMClient, LLMError
from echolens.tools.registry import TOOLS, run_tool

MAX_STEPS = 4
MAX_TOOL_CALLS = 3
MAX_FINDINGS_IN_PROMPT = 12
MAX_RESULT_CHARS = 1800

ASK_SYSTEM = """You are EchoLens's analyst. Answer the user's question about their product's \
feedback.

You have two sources:
1. VERIFIED FINDINGS — conclusions EchoLens already investigated and a human approved. These are \
the strongest evidence. Prefer them.
2. TOOLS — deterministic queries over the raw feedback corpus. Use these when the findings do not \
cover the question, or when the user asks for numbers, trends or segments.

Rules:
- Ground every claim. Cite findings by their case number. If a number comes from a tool, say which.
- If neither the findings nor the tools support an answer, say so plainly. Never guess a cause.
- A finding is a VERIFIED cause; a tool result is raw data. Do not present raw data as a proven \
cause — say what the data shows and what would settle it.
- Be concise: 2-4 sentences unless the user asks for detail.

Respond with JSON only."""

ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["tool", "answer"]},
        "tool": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "args": {"type": "object"},
                "why": {"type": "string"},
            },
        },
        "answer": {"type": "string"},
        "cites_cases": {"type": "array", "items": {"type": "integer"}},
        "confident": {"type": "boolean"},
    },
    "required": ["action"],
}


@dataclass
class AskResult:
    text: str
    citations: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    confident: bool = True
    steps: int = 0


def _knowledge(session: Session, product_id: int | None) -> list[tuple[Finding, Investigation]]:
    from sqlalchemy import select

    stmt = select(Finding)
    if product_id is not None:
        stmt = stmt.where(Finding.product_id == product_id)
    out = []
    for f in session.scalars(stmt.order_by(Finding.id.desc())).all():
        inv = session.get(Investigation, f.investigation_id)
        if inv is None:
            continue
        if inv.status == "resolved" or f.status == "approved":
            out.append((f, inv))
    return out


def _findings_block(rows: list[tuple[Finding, Investigation]]) -> str:
    if not rows:
        return "VERIFIED FINDINGS: none yet — nothing has been investigated for this product."
    lines = []
    for f, inv in rows[:MAX_FINDINGS_IN_PROMPT]:
        fj = f.json or {}
        impact = fj.get("impact", {})
        pct = impact.get("affected_pct")
        lines.append(json.dumps({
            "case": inv.id,
            "summary": f.summary,
            "detail": (fj.get("prose") or "")[:400],
            "confidence": round(f.confidence or 0.0, 2),
            "status": f.status,
            "affected_pct": pct,
        }))
    return "VERIFIED FINDINGS:\n" + "\n".join(lines)


def _tools_block() -> str:
    lines = [f"- {s.name}: {s.description}" for s in TOOLS.values()]
    return "TOOLS AVAILABLE:\n" + "\n".join(lines)


def _cite(f: Finding, inv: Investigation) -> dict:
    impact = (f.json or {}).get("impact", {})
    return {"investigation_id": inv.id, "finding_id": f.id, "summary": f.summary,
            "affected_pct": impact.get("affected_pct")}


def answer(session: Session, message: str, llm: LLMClient,
           product_id: int | None = None, product_name: str | None = None) -> AskResult:
    rows = _knowledge(session, product_id)
    by_case = {inv.id: (f, inv) for f, inv in rows}

    transcript: list[str] = []
    tool_calls: list[dict] = []
    steps = 0

    for _ in range(MAX_STEPS):
        steps += 1
        prompt = "\n\n".join([
            f"PRODUCT: {product_name or 'this product'}",
            _findings_block(rows),
            _tools_block(),
            ("WHAT YOU HAVE ALREADY DONE:\n" + "\n".join(transcript)) if transcript else "",
            f"QUESTION: {message}",
            (f"You have used {len(tool_calls)} of {MAX_TOOL_CALLS} tool calls."
             if tool_calls else ""),
            ("You have no tool calls left — answer from what you have."
             if len(tool_calls) >= MAX_TOOL_CALLS else ""),
        ]).strip()

        try:
            res = llm.complete_json(ASK_SYSTEM, prompt, ASK_SCHEMA, "ask")
            parsed = res.parsed
        except LLMError:
            break

        if parsed.get("action") == "tool" and len(tool_calls) < MAX_TOOL_CALLS:
            spec = parsed.get("tool") or {}
            name = spec.get("name", "")
            args = spec.get("args") or {}
            if name not in TOOLS:
                transcript.append(f"Tool '{name}' does not exist. Choose from: {list(TOOLS)}")
                continue
            try:
                out = run_tool(session, name, args, product=product_name)
                blob = json.dumps(out)[:MAX_RESULT_CHARS]
                tool_calls.append({"name": name, "args": args, "why": spec.get("why", "")})
                transcript.append(f"Called {name}({json.dumps(args)}) -> {blob}")
            except Exception as err:
                transcript.append(f"Called {name} -> FAILED: {type(err).__name__}: {err}")
            continue

        text = (parsed.get("answer") or "").strip()
        if not text:
            break
        cites = []
        for case_id in parsed.get("cites_cases", []) or []:
            hit = by_case.get(case_id)
            if hit is not None:
                cites.append(_cite(*hit))
        return AskResult(text=text, citations=cites, tool_calls=tool_calls,
                         confident=bool(parsed.get("confident", True)), steps=steps)

    return AskResult(
        text="I couldn't work that out from the findings or the feedback data. "
             "Try rephrasing, or ask me to investigate it.",
        citations=[], tool_calls=tool_calls, confident=False, steps=steps)


def has_anything_to_say(session: Session, product_id: int | None) -> bool:
    from sqlalchemy import select

    from echolens.db.models import Product, Review

    if _knowledge(session, product_id):
        return True
    stmt = select(Review.id).limit(1)
    if product_id is not None:
        prod = session.get(Product, product_id)
        if prod is None:
            return False
        stmt = stmt.where(Review.product == prod.name)
    return session.scalars(stmt).first() is not None


def best_existing_answer(session: Session, message: str,
                         product_id: int | None = None) -> tuple[Finding, Investigation] | None:
    from echolens.chat import retrieve

    hits = retrieve(session, message, k=1, product_id=product_id)
    return hits[0] if hits else None
