"""A minimal Model Context Protocol server: ask EchoLens from your editor.

    echolens mcp            # stdio; launched by Claude Code / Cursor / VS Code

It speaks JSON-RPC 2.0 over stdio — one JSON message per line, as the MCP
stdio transport specifies — and implements just enough of the protocol for a
client to discover and call tools: `initialize`, `tools/list`, `tools/call`
(plus `ping`, and silently accepting notifications). No MCP SDK: the surface
is small and a dependency would be heavier than the code it replaces.

Every tool is read-only and goes through the DEPLOYED EchoLens API over HTTP
(ECHOLENS_API_URL + ECHOLENS_API_TOKEN), so it sees exactly what that token's
role and product scope allow — no database credentials on a laptop. The HTTP
transport is injectable so tests run against an httpx.MockTransport.

stdout is the protocol channel. Nothing else may be written to it; diagnostics
go to stderr.
"""
from __future__ import annotations

import json
import sys
from typing import IO, Any

PROTOCOL_VERSION = "2025-06-18"
# Versions whose request/response shapes for these methods are identical. A
# client asking for one of these gets it echoed back; anything else gets ours,
# which the spec allows (the client then decides whether to proceed).
SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "echolens", "title": "EchoLens", "version": "0.1.0"}

# Case statuses that are finished business. Everything else is still a problem
# someone may need to act on — including `resolved`, which has a diagnosis but
# no verified fix yet.
_CLOSED = {"dismissed", "verified_fixed"}

_PRODUCT_ARG = {
    "product_id": {
        "type": "integer",
        "description": "EchoLens product id (see list_products). Omit to use the "
                       "token's active product.",
    }
}

TOOLS: list[dict] = [
    {
        "name": "list_products",
        "title": "List products",
        "description": "Every product this EchoLens token can see, with its id. "
                       "Use the id as product_id in the other tools.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_open_problems",
        "title": "List open problems",
        "description": "Open cases for a product — problems users are reporting that are "
                       "not dismissed or verified fixed — most severe first.",
        "inputSchema": {"type": "object", "properties": {
            **_PRODUCT_ARG,
            "limit": {"type": "integer", "minimum": 1, "maximum": 100,
                      "description": "Max cases to return (default 20)."},
        }},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_finding",
        "title": "Get a case's finding",
        "description": "The finding for one case: what's broken, root cause, confidence, "
                       "recommended actions and the evidence behind it.",
        "inputSchema": {"type": "object", "properties": {
            "case_id": {"type": "integer", "description": "The case number (e.g. 34 for case #34)."},
            **_PRODUCT_ARG,
        }, "required": ["case_id"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "search_findings",
        "title": "Search findings",
        "description": "Search finished cases by words in their root cause or summary, "
                       "e.g. 'login crash' or 'battery'.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to look for."},
            **_PRODUCT_ARG,
            "limit": {"type": "integer", "minimum": 1, "maximum": 50,
                      "description": "Max results (default 10)."},
        }, "required": ["query"]},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "product_health",
        "title": "Product health",
        "description": "A product's health overview: fixes shipped and verified, regressions, "
                       "time to diagnosis, and what is trending.",
        "inputSchema": {"type": "object", "properties": {**_PRODUCT_ARG}},
        "annotations": {"readOnlyHint": True},
    },
]


class ToolError(Exception):
    """A tool failed in a way the model should read (isError result), as opposed
    to a protocol error."""


class ApiClient:
    """Thin read-only client for the deployed EchoLens API."""

    def __init__(self, base_url: str | None = None, token: str | None = None,
                 transport=None, timeout: float = 20.0):
        from echolens.config import settings
        self.base_url = (base_url if base_url is not None else settings.echolens_api_url).rstrip("/")
        self.token = token if token is not None else settings.echolens_api_token
        self._transport = transport
        self._timeout = timeout

    def get(self, path: str, params: dict | None = None) -> Any:
        import httpx

        if not self.base_url:
            raise ToolError("ECHOLENS_API_URL is not set — point it at your deployed EchoLens API.")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            with httpx.Client(base_url=self.base_url, headers=headers, timeout=self._timeout,
                              transport=self._transport) as c:
                r = c.get(path, params=clean)
        except httpx.HTTPError as err:
            raise ToolError(f"Couldn't reach EchoLens at {self.base_url}: {type(err).__name__}")
        if r.status_code == 401:
            raise ToolError("EchoLens rejected the token — set ECHOLENS_API_TOKEN to a fresh one.")
        if r.status_code == 404:
            raise ToolError("Not found (or not visible to this token's product scope).")
        if r.status_code >= 300:
            detail = ""
            try:
                detail = str(r.json().get("detail", ""))[:200]
            except Exception:  # noqa: BLE001
                pass
            raise ToolError(f"EchoLens API {r.status_code}{': ' + detail if detail else ''}")
        return r.json()


# ── tools ───────────────────────────────────────────────────────────────

def _int(args: dict, key: str, default: int | None = None, lo: int = 1, hi: int = 100) -> int | None:
    v = args.get(key, default)
    if v is None:
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ToolError(f"{key} must be an integer")
    return max(lo, min(hi, v))


def _list_products(api: ApiClient, args: dict) -> dict:
    data = api.get("/products")
    return {"active_product_id": data.get("active_product_id"),
            "products": [{"id": p.get("id"), "name": p.get("name"),
                          "package_name": p.get("package_name"),
                          "github_repo": p.get("github_repo")}
                         for p in data.get("products", [])]}


def _list_open_problems(api: ApiClient, args: dict) -> dict:
    limit = _int(args, "limit", 20)
    data = api.get("/cases", {"product_id": _int(args, "product_id", hi=10**9)})
    open_cases = [c for c in data.get("cases", []) if c.get("status") not in _CLOSED]
    open_cases.sort(key=lambda c: -(c.get("severity_score") or 0))
    return {
        "product": data.get("product"),
        "product_id": data.get("product_id"),
        "open_count": len(open_cases),
        "cases": [{
            "case_id": c.get("id"), "title": c.get("title"), "status": c.get("status"),
            "why": c.get("why"), "severity": c.get("severity"),
            "confidence": c.get("confidence"), "age_days": c.get("age_days"),
            "issue_url": c.get("issue_url"),
        } for c in open_cases[:limit]],
    }


def _get_finding(api: ApiClient, args: dict) -> dict:
    case_id = _int(args, "case_id", hi=10**9)
    if case_id is None:
        raise ToolError("case_id is required")
    inv = api.get(f"/investigations/{case_id}",
                  {"product_id": _int(args, "product_id", hi=10**9)})
    f = inv.get("finding") or {}
    return {
        "case_id": inv.get("id"),
        "title": inv.get("title"),
        "status": inv.get("case_status") or inv.get("status"),
        "why": inv.get("case_why"),
        "finding": None if not f else {
            "summary": f.get("summary"),
            "confidence": f.get("confidence"),
            "root_cause": f.get("prose"),
            "severity": f.get("severity"),
            "impact": f.get("impact"),
            "decision": f.get("decision"),
            "fix": f.get("fix"),
        },
        "recommendations": inv.get("recommendations", []),
        "evidence": [{"source": e.get("source"), "ref": e.get("ref"), "snippet": e.get("snippet")}
                     for e in (inv.get("evidence") or [])[:12]],
    }


def _search_findings(api: ApiClient, args: dict) -> dict:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    limit = _int(args, "limit", 10, hi=50)
    data = api.get("/archive", {"product_id": _int(args, "product_id", hi=10**9)})
    terms = [t for t in query.lower().split() if t]

    def score(row: dict) -> int:
        hay = f"{row.get('cause', '')} {row.get('summary', '')}".lower()
        return sum(1 for t in terms if t in hay)

    ranked = sorted(((score(r), r) for r in data.get("rows", [])), key=lambda x: -x[0])
    hits = [r for s, r in ranked if s > 0][:limit]
    return {"query": query, "count": len(hits), "results": [{
        "case_id": int(str(r.get("id", "")).lstrip("#") or 0) or None,
        "cause": r.get("cause"), "status": r.get("status"),
        "confidence": r.get("conf"), "reviewed": r.get("human"),
        "summary": (r.get("summary") or "")[:600],
    } for r in hits]}


def _product_health(api: ApiClient, args: dict) -> dict:
    return api.get("/overview", {"product_id": _int(args, "product_id", hi=10**9)})


_HANDLERS = {
    "list_products": _list_products,
    "list_open_problems": _list_open_problems,
    "get_finding": _get_finding,
    "search_findings": _search_findings,
    "product_health": _product_health,
}


def call_tool(api: ApiClient, name: str, args: dict | None) -> dict:
    """A tools/call result. Tool failures are results with isError — the spec
    keeps protocol errors for malformed requests, not for "the API said 404"."""
    try:
        data = _HANDLERS[name](api, args or {})
    except ToolError as err:
        return {"content": [{"type": "text", "text": str(err)}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2, default=str)}],
            "structuredContent": data if isinstance(data, dict) else {"result": data},
            "isError": False}


# ── JSON-RPC ────────────────────────────────────────────────────────────

def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def handle(message: Any, api: ApiClient) -> dict | None:
    """One JSON-RPC message in, one response out — or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" \
            or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None,
                      -32600, "Invalid Request")
    method = message["method"]
    msg_id = message.get("id")
    is_notification = "id" not in message
    params = message.get("params") or {}
    if is_notification:
        return None  # notifications/initialized, notifications/cancelled, …

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return _result(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": "Read-only access to EchoLens findings. Call list_products "
                            "first to find a product_id.",
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name not in _HANDLERS:
            return _error(msg_id, -32602, f"Unknown tool: {name}")
        args = params.get("arguments")
        if args is not None and not isinstance(args, dict):
            return _error(msg_id, -32602, "arguments must be an object")
        return _result(msg_id, call_tool(api, name, args))
    return _error(msg_id, -32601, f"Method not found: {method}")


def _safe_handle(message: Any, api: ApiClient) -> dict | None:
    try:
        return handle(message, api)
    except Exception as err:  # noqa: BLE001 — never kill the session
        print(f"echolens mcp: internal error: {err!r}", file=sys.stderr)
        return _error(message.get("id") if isinstance(message, dict) else None,
                      -32603, "Internal error")


def serve(stdin: IO[str] | None = None, stdout: IO[str] | None = None,
          api: ApiClient | None = None) -> int:
    """Read newline-delimited JSON-RPC from stdin until EOF."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    api = api or ApiClient()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: Any = _error(None, -32700, "Parse error")
        else:
            if isinstance(message, list):  # a batch (2025-03-26); answer each
                response = [r for r in (_safe_handle(m, api) for m in message)
                            if r is not None] or None
            else:
                response = _safe_handle(message, api)
        if response is not None:
            stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            stdout.flush()
    return 0
