"""Tool registry: name → callable + JSON arg schema + description.

The investigator's plan step picks from THIS list; the act node executes
deterministically. No LLM inside any tool.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from echolens.tools.analyze_trend import analyze_trend
from echolens.tools.compare_cohorts import compare_cohorts
from echolens.tools.compare_periods import compare_periods
from echolens.tools.get_release_notes import get_release_notes
from echolens.tools.search_github_issues import search_github_issues
from echolens.tools.search_reddit import search_reddit
from echolens.tools.search_reviews import search_reviews
from echolens.tools.review_stats import review_stats

_DATE = {"type": "string", "description": "ISO date YYYY-MM-DD"}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    fn: Callable
    description: str
    args_schema: dict
    source: str  # evidence source label


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec(
            "search_reviews", search_reviews,
            "Keyword search over app-store reviews. Supports date range, rating and "
            "version/OS segmentation (e.g. version_prefix='3.1', os_version='Android 15').",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "date_from": _DATE, "date_to": _DATE,
                    "rating_max": {"type": "integer"}, "rating_min": {"type": "integer"},
                    "version_prefix": {"type": "string"}, "os_version": {"type": "string"},
                    "product": {"type": "string"}, "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            "play_store",
        ),
        ToolSpec(
            "review_stats", review_stats,
            "Daily counts of reviews mentioning a term and its share of negative (<=2 star) "
            "reviews; segmentable by version/OS. Use for rates, not anecdotes.",
            {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "date_from": _DATE, "date_to": _DATE,
                    "version_prefix": {"type": "string"}, "os_version": {"type": "string"},
                    "product": {"type": "string"},
                },
                "required": ["term"],
            },
            "play_store",
        ),
        ToolSpec(
            "compare_periods", compare_periods,
            "Before/after stats for a metric: means, delta %, z-score. Metrics: "
            "'one_star_volume', 'avg_rating', or 'term_share:<term>' (% of negatives mentioning term).",
            {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "before_from": _DATE, "before_to": _DATE,
                    "after_from": _DATE, "after_to": _DATE,
                },
                "required": ["metric", "before_from", "before_to", "after_from", "after_to"],
            },
            "play_store",
        ),
        ToolSpec(
            "search_github_issues", search_github_issues,
            "Keyword search over GitHub issues (title + body), ranked by relevance then reactions.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "state": {"type": "string", "enum": ["open", "closed"]},
                    "since": _DATE, "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            "github",
        ),
        ToolSpec(
            "get_release_notes", get_release_notes,
            "Fetch release notes by version prefix or date range.",
            {
                "type": "object",
                "properties": {
                    "version": {"type": "string"},
                    "date_from": _DATE, "date_to": _DATE,
                },
            },
            "release_notes",
        ),
        ToolSpec(
            "search_reddit", search_reddit,
            "Keyword search over Reddit posts.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "subreddit": {"type": "string"},
                    "since": _DATE, "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            "reddit",
        ),
        ToolSpec(
            "compare_cohorts", compare_cohorts,
            "Prove version/OS-specific causation in ONE call: compares a term's complaint "
            "rate across cohorts (dimension='version' or 'os'), optionally holding the other "
            "dimension fixed (os_version=..., version_prefix=...). Returns the highest cohort "
            "and how many times worse it is than the next — the fastest decoy-killer.",
            {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "dimension": {"type": "string", "enum": ["version", "os"]},
                    "date_from": _DATE, "date_to": _DATE,
                    "os_version": {"type": "string"}, "version_prefix": {"type": "string"},
                },
                "required": ["term"],
            },
            "play_store",
        ),
        ToolSpec(
            "analyze_trend", analyze_trend,
            "Statistical decomposition of a term's daily signal: baseline, peak, and a "
            "deterministic changepoint (the date the rate shifted and by how many x). Stronger "
            "than a single z-score for pinpointing WHEN a problem started.",
            {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "date_from": _DATE, "date_to": _DATE,
                    "negatives_only": {"type": "boolean"},
                },
                "required": ["term"],
            },
            "play_store",
        ),
    ]
}


def run_tool(session: Session, name: str, args: dict) -> dict:
    """Execute a registered tool. Raises KeyError/TypeError/ValueError on bad
    calls — the investigator records those as FAIL trace steps."""
    spec = TOOLS[name]
    allowed = set(spec.args_schema.get("properties", {}))
    clean = {k: v for k, v in args.items() if k in allowed and v is not None}
    missing = [k for k in spec.args_schema.get("required", []) if k not in clean]
    if missing:
        raise ValueError(f"{name}: missing required args {missing}")
    return spec.fn(session, **clean)


def tool_catalog() -> str:
    """Compact tool list for the plan prompt."""
    lines = []
    for t in TOOLS.values():
        props = ", ".join(t.args_schema.get("properties", {}))
        lines.append(f"- {t.name}({props}): {t.description}")
    return "\n".join(lines)
