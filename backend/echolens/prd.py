"""A spec (PRD) from a feature request — what users asked for, written up so
engineering can estimate it.

A request theme already carries everything a first-draft spec needs: who is
asking, how many, how happy they are, and their own words. This module turns
that into Markdown with fixed sections — Problem, Who asks, User stories,
Acceptance criteria, Out of scope, Open questions, Evidence.

Two rules shape it:

* **Deterministic first.** The template alone is a complete spec. An injected
  `llm` may rewrite ONLY the user stories and acceptance criteria, and its
  output is thrown away (template kept, reason recorded) if it is empty, too
  long, off-format, or quotes anything that is not in the evidence. A spec
  that puts words in users' mouths is worse than a plain one.
* **Every quote is real.** Quotes are review text verbatim (whitespace
  collapsed, long ones clipped at a word with the ellipsis OUTSIDE the quote
  marks), so any quoted span can be found in the evidence it cites.
"""
from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy.orm import Session

from echolens.backlog import DEFAULT_EFFORT, HAPPY_WEIGHT, request_demand, request_themes
from echolens.db.models import Setting
from echolens.intent import count_intents
from echolens.logging import get_logger

log = get_logger("prd")

MAX_EVIDENCE = 12
QUOTE_CHARS = 280
# Limits on a model rewrite. Past these it is padding, not a better spec.
STORIES = (2, 4)
CRITERIA = (3, 6)
MAX_LINE = 300
MAX_REWRITE = 2400

_QUOTE_RE = re.compile(r"[“\"]([^“”\"]{3,})[”\"]")
_INTENT_NAMES = {"feature_request": "feature request", "ux_confusion": "confusion",
                 "bug": "bug report", "praise": "praise", "other": "other"}


def _plain(text: str) -> str:
    """Review text safe to put inside “…”: one line, no curly quotes of its own."""
    return " ".join((text or "").replace("“", '"').replace("”", '"').split())


def quote(text: str, limit: int = QUOTE_CHARS) -> str:
    t = _plain(text)
    if len(t) <= limit:
        return f"“{t}”"
    cut = t[:limit].rsplit(" ", 1)[0] or t[:limit]
    return f"“{cut}” …"


def _norm(text: str) -> str:
    return " ".join(text.replace("“", '"').replace("”", '"').lower().split())


def quotes_in(markdown: str) -> list[str]:
    """Every quoted span in a piece of text — what the evidence check compares."""
    return [m.group(1) for m in _QUOTE_RE.finditer(markdown or "")]


def quotes_are_real(text: str, evidence: list[str]) -> bool:
    corpus = [_norm(e) for e in evidence]
    return all(any(_norm(q) in e for e in corpus) for q in quotes_in(text))


# ── the template ────────────────────────────────────────────────────────


def _stories(phrase: str, product: str, happy: int, confused: int) -> list[str]:
    out = [f"As a {product} user, I want {phrase}, so that the app fits the way I already use it."]
    if happy:
        out.append(f"As a user who rates {product} 4–5★, I want {phrase}, "
                   "so that I have no reason to look at alternatives.")
    if confused:
        out.append(f"As a user who could not find this, I want {phrase} to be easy to discover, "
                   "so that I do not have to ask for it in a review.")
    out.append(f"As a user who does not need {phrase}, I want my current setup left as it is, "
               "so that the change costs me nothing.")
    return out


def _criteria(phrase: str, n: int, confused: int) -> list[str]:
    out = [
        f"Given a user on the release that ships it, when they look for {phrase}, "
        "then they find it without a workaround or a support request.",
        "Given a user who never turns it on, when they update, "
        "then their existing settings and flows behave exactly as before.",
        f"Given the release has been out for 30 days, when new 3–5★ reviews are grouped, "
        f"then fewer than {max(1, n // 2)} of them ask for {phrase}.",
    ]
    if confused:
        out.append(f"Given a first-time user, when they open the screen it belongs on, "
                   f"then {phrase} is visible without searching.")
    return out


def _facts(theme: dict) -> dict:
    reviews = theme["reviews"]
    demand = request_demand(reviews)
    ratings = [r["rating"] for r in reviews if r.get("rating")]
    intents = count_intents((r["text"], r["rating"]) for r in reviews)
    dates = sorted(r["date"] for r in reviews if r.get("date"))
    return {"demand": demand, "ratings": ratings, "intents": intents, "dates": dates,
            "avg": round(sum(ratings) / len(ratings), 1) if ratings else None}


def template_sections(theme: dict, product: str | None) -> dict:
    """The structured spec: every section as a list of lines."""
    f = _facts(theme)
    phrase, n, happy = theme["phrase"], f["demand"]["requesters"], f["demand"]["happy"]
    name = product or "the app"
    confused = f["intents"].get("ux_confusion", 0)

    problem = [f"{n} {'review asks' if n == 1 else 'reviews ask'} for {phrase}, "
               f"which {name} does not offer today. In their words:", ""]
    problem += [f"> {quote(r['text'])}" for r in theme["reviews"][:2] if r["text"]]

    breakdown = " · ".join(f"{s}★ ×{f['ratings'].count(s)}" for s in (5, 4, 3)
                           if f["ratings"].count(s))
    mix = " · ".join(f"{_INTENT_NAMES.get(k, k)} ×{v}" for k, v in f["intents"].items() if v)
    who = [f"- **{n}** distinct {'review' if n == 1 else 'reviews'} ask for this; "
           f"**{happy}** of them rate the app 4–5★."]
    if f["avg"] is not None:
        who.append(f"- Average rating of the requesters: **{f['avg']}★** ({breakdown}).")
    if mix:
        who.append(f"- Intent mix: {mix}.")
    if f["dates"]:
        who.append(f"- First asked {f['dates'][0]}, most recently {f['dates'][-1]}.")
    who.append(f"- Plan demand: {n} + {HAPPY_WEIGHT:g} × {happy} = "
               f"{f['demand']['value']:g} (each 4–5★ requester counts extra).")

    out_of_scope = [f"- {o['statement']} — a separate request ({len(o['reviews'])} reviews)."
                    for o in theme.get("others", [])[:3]]
    out_of_scope += ["- Bugs reported in the same reviews — those are on the Bugs plan.",
                     f"- Turning {phrase} on for users who did not ask, beyond an opt-in."]

    questions = ["- Which platforms and app versions get this first?",
                 f"- Is {phrase} for everyone, or an opt-in / paid feature?"]
    if confused:
        questions.append(f"- {confused} of these reviews read as confusion — is part of this "
                         "already possible but hard to find?")
    if f["avg"] is not None and f["avg"] < 4:
        questions.append(f"- Requesters rate the app {f['avg']}★ on average — is this what is "
                         "holding their rating back?")
    questions.append(f"- What does engineering estimate? The plan assumes {DEFAULT_EFFORT:g} "
                     "engineer-days until someone sets it.")

    evidence = []
    for r in theme["reviews"][:MAX_EVIDENCE]:
        if not r["text"]:
            continue
        meta = " · ".join(x for x in (f"{r['rating']}★" if r.get("rating") else "",
                                      r.get("date") or "", r.get("source") or "") if x)
        evidence.append(f"- {quote(r['text'])} — {meta}")
    if len(theme["reviews"]) > MAX_EVIDENCE:
        evidence.append(f"- …and {len(theme['reviews']) - MAX_EVIDENCE} more.")

    return {"problem": problem, "who": who,
            "stories": _stories(phrase, name, happy, confused),
            "criteria": _criteria(phrase, n, confused),
            "out_of_scope": out_of_scope, "questions": questions, "evidence": evidence}


def render(theme: dict, sections: dict) -> str:
    md = [f"# Spec: {theme['statement']}", "",
          "## Problem", *sections["problem"], "",
          "## Who asks", *sections["who"], "",
          "## User stories", *[f"- {s}" for s in sections["stories"]], "",
          "## Acceptance criteria", *[f"- {c}" for c in sections["criteria"]], "",
          "## Out of scope", *sections["out_of_scope"], "",
          "## Open questions", *sections["questions"], "",
          "## Evidence", *sections["evidence"]]
    return "\n".join(md)


# ── the optional rewrite ────────────────────────────────────────────────

_SYSTEM = (
    "You improve the user stories and acceptance criteria of a product spec "
    "built from app-store reviews that ask for a feature.\n\n"
    "Rules:\n"
    "- 2 to 4 user stories, each 'As a <user>, I want <goal>, so that <benefit>.'\n"
    "- 3 to 6 acceptance criteria, each 'Given <context>, when <action>, then <outcome>.'\n"
    "- Ground every line in the reviews supplied. Never invent a quote; if you "
    "quote a review, copy its words exactly.\n"
    "- Plain sentences, no markdown, at most 300 characters each."
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "user_stories": {"type": "array", "items": {"type": "string"}},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["user_stories", "acceptance_criteria"],
    "additionalProperties": False,
}


def check_rewrite(data, evidence: list[str]) -> tuple[list[str], list[str]]:
    """Validate a model rewrite; raise ValueError naming why it was refused."""
    if not isinstance(data, dict):
        raise ValueError("empty")
    stories = [" ".join(str(x).split()) for x in data.get("user_stories") or []]
    criteria = [" ".join(str(x).split()) for x in data.get("acceptance_criteria") or []]
    stories, criteria = [s for s in stories if s], [c for c in criteria if c]
    if not stories or not criteria:
        raise ValueError("empty")
    if len(stories) < STORIES[0] or len(criteria) < CRITERIA[0]:
        raise ValueError("too short")
    if (len(stories) > STORIES[1] or len(criteria) > CRITERIA[1]
            or any(len(x) > MAX_LINE for x in stories + criteria)
            or sum(len(x) for x in stories + criteria) > MAX_REWRITE):
        raise ValueError("too long")
    if not all(re.match(r"as an? ", s, re.IGNORECASE) for s in stories) or not all(
            all(w in c.lower() for w in ("given", "when", "then")) for c in criteria):
        raise ValueError("off-format")
    if not quotes_are_real("\n".join(stories + criteria), evidence):
        raise ValueError("quotes something not in the evidence")
    return stories, criteria


def _rewrite(llm, theme: dict, sections: dict, product: str | None) -> tuple[dict | None, str | None]:
    evidence = [r["text"] for r in theme["reviews"] if r["text"]]
    user = (f"PRODUCT: {product or 'this app'}\nREQUEST: {theme['statement']}\n\n"
            f"REVIEWS:\n{json.dumps([_plain(e)[:QUOTE_CHARS] for e in evidence[:8]], indent=1)}\n\n"
            f"CURRENT USER STORIES:\n{json.dumps(sections['stories'], indent=1)}\n\n"
            f"CURRENT ACCEPTANCE CRITERIA:\n{json.dumps(sections['criteria'], indent=1)}")
    try:
        res = llm.complete_json(_SYSTEM, user, _SCHEMA, "spec.rewrite")
        data = res.parsed if hasattr(res, "parsed") else res
        stories, criteria = check_rewrite(data, evidence)
    except ValueError as err:
        return None, str(err)
    except Exception as err:   # a failed call is the template, not a 500
        log.warning("spec_rewrite_failed", error=str(err))
        return None, "model call failed"
    return {**sections, "stories": stories, "criteria": criteria}, None


def build_spec(theme: dict, product: str | None = None, *, llm=None) -> dict:
    """{slug, title, markdown, engine, rejected} for one request theme."""
    sections = template_sections(theme, product)
    engine, rejected = "template", None
    if llm is not None:
        rewritten, rejected = _rewrite(llm, theme, sections, product)
        if rewritten is not None:
            sections, engine = rewritten, "model"
    return {"slug": theme["slug"], "title": theme["statement"],
            "markdown": render(theme, sections), "engine": engine, "rejected": rejected,
            "evidence_count": len(theme["reviews"])}


# ── lookup + cache ──────────────────────────────────────────────────────


def find_request(session: Session, product_id: int | None, slug: str) -> dict | None:
    """The request theme behind `slug`, only if it belongs to this product. The
    other themes ride along for the spec's Out of scope section."""
    if product_id is None or not slug.startswith(f"request-p{product_id}-"):
        return None
    themes = request_themes(session, product_id)
    theme = next((t for t in themes if t["slug"] == slug), None)
    if theme is None:
        return None
    return {**theme, "others": [t for t in themes if t is not theme]}


def get_spec(session: Session, product_id: int, product: str | None, slug: str, *,
             llm=None) -> dict | None:
    """build_spec behind a cache keyed by the evidence, so opening the spec twice
    (or filing what you just read) does not pay for — or reword — it again."""
    theme = find_request(session, product_id, slug)
    if theme is None:
        return None
    fp = json.dumps([sorted(r["id"] for r in theme["reviews"]), theme["statement"],
                     llm is not None])
    key = f"request_spec:{product_id}:{hashlib.sha1(slug.encode()).hexdigest()[:20]}"
    row = session.get(Setting, key)
    if row and isinstance(row.value, dict) and row.value.get("fingerprint") == fp:
        return {**row.value["spec"], "cached": True}
    spec = build_spec(theme, product, llm=llm)
    if row is None:
        session.add(Setting(key=key, value={"fingerprint": fp, "spec": spec}))
    else:
        row.value = {"fingerprint": fp, "spec": spec}
    session.flush()
    return {**spec, "cached": False}


def file_spec(tracker: str, spec: dict, *, repo: str | None = None, post_fn=None) -> dict:
    """File a spec as a ticket. `post_fn` follows the tracker's own contract
    (github_issue's for GitHub, trackers' for Linear/Jira)."""
    from echolens.exporting import request_ticket
    from echolens.integrations.trackers import create_ticket
    ticket = request_ticket(spec)
    return create_ticket(tracker, ticket["title"], ticket["body"], repo=repo, post_fn=post_fn)
