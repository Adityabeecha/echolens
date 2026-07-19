"""EchoLens CLI (Milestone 1).

    python -m echolens.cli seed
    python -m echolens.cli investigate --anomaly demo1 [--tier standard]
"""
from __future__ import annotations

import argparse
import json
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from echolens.db.models import AnomalyEvent, Review
from echolens.db.session import init_db, session_scope

console = Console()

KIND_STYLE = {
    "THINK": "grey70",
    "TOOL": "bright_cyan",
    "EVID": "orange1",
    "UPDT": "green3",
    "FAIL": "red",
    "CHECK": "grey42",
    "SPEC": "gold1",
    "REFUTE": "magenta",
}


def cmd_seed(_args) -> int:
    init_db()
    with session_scope() as session:
        if session.query(Review).count() > 0:
            console.print("[yellow]Database already seeded — delete backend/echolens.db to regenerate.[/]")
            return 0
        from echolens.synthetic.generate import generate
        counts = generate(session)
    console.print(f"[green]Seeded synthetic Lumo dataset:[/] {counts}")
    return 0


def _print_step(kind: str, content: dict) -> None:
    style = KIND_STYLE.get(kind, "white")
    if kind == "THINK":
        body = content.get("text", "")
    elif kind == "TOOL":
        body = f"{content.get('code', '')}\n→ {content.get('preview', '')}"
    elif kind == "EVID":
        body = (f"{content.get('id')} · {content.get('source')} · {content.get('ref')}\n"
                f"“{content.get('text', '')}”  supports {content.get('supports')} "
                f"contradicts {content.get('contradicts')}")
    elif kind == "UPDT":
        body = f"{content.get('code', '')}  {content.get('text', '')}"
    elif kind == "FAIL":
        body = f"{content.get('code', '')}\n✕ {content.get('error', '')}\n{content.get('text', '')}"
    else:  # CHECK
        body = f"{content.get('text', '')}  budget={json.dumps(content.get('budget', {}))}"
    console.print(f"[bold {style}]\\[{kind}][/] [{style}]{escape(body)}[/]")


def cmd_investigate(args) -> int:
    init_db()
    with session_scope() as session:
        anomaly = session.query(AnomalyEvent).filter_by(slug=args.anomaly).first()
        if anomaly is None:
            console.print(f"[red]No anomaly with slug '{args.anomaly}'. Run `seed` first "
                          f"(available: demo1, demo2).[/]")
            return 1

        console.print(Panel(
            f"[bold]{anomaly.description}[/]\n"
            f"type={anomaly.type} · metric={anomaly.metric} · Δ={anomaly.delta:+.0%} · z={anomaly.z}",
            title=f"Investigating anomaly '{args.anomaly}'", border_style="orange1",
        ))

        from echolens.investigator.graph import Investigator
        inv = Investigator(session, anomaly, tier=args.tier, on_step=_print_step)
        result = inv.run()
        final = inv._final_state
        finding = final["finding"]

        color = {"resolved": "green3", "insufficient_evidence": "yellow",
                 "needs_human": "orange1", "budget_exhausted": "red"}.get(result.status, "white")
        lines = [
            f"[bold {color}]{result.status.upper()}[/] — {final['status_reason']}",
            "",
            f"[bold]{escape(finding.get('summary', ''))}[/]",
            escape(finding.get("prose", "")),
            "",
            f"confidence: {finding.get('confidence')} · "
            f"supported hypothesis: {finding.get('supported_hypothesis')}",
            f"checked: {', '.join(finding.get('checked', []))}",
        ]
        if result.status != "resolved":
            lines.append(f"what would settle it: {finding.get('what_would_settle_it', '')}")
        lines += ["", "[bold]Hypotheses[/]"]
        for h in final["hypotheses"]:
            lines.append(f"  {h['id']} [{h['status']:<9}] {h['confidence']:.2f}  {h['statement']}"
                         f"  (+{len(h['evidence_for'])}/−{len(h['evidence_against'])})")
        lines += ["", "[bold]Evidence chain[/]"]
        for e in final["evidence"]:
            lines.append(f"  {e['id']} · {e['source']} · {e['ref']} · via {e['retrieved_by']}")
        lines += ["", f"[bold]Budget[/] {json.dumps(inv.budget.as_dict())}"]
        console.print(Panel("\n".join(lines), title=f"FINDING · investigation #{result.id}",
                            border_style=color))
    return 0


def cmd_scan(_args) -> int:
    init_db()
    from echolens.detector.detect import scan
    with session_scope() as session:
        events = scan(session)
        console.print("[bold]Detected anomalies[/]")
        for e in events:
            sev = "SEV1" if e.z >= 3 else "SEV2" if e.z >= 2 else "SEV3"
            console.print(f"  [orange1]{e.slug}[/] [{sev}] z={e.z} · {escape(e.description)}")
    return 0


def cmd_triage(args) -> int:
    init_db()
    from echolens.orchestrator.triage import Orchestrator, run_triaged
    with session_scope() as session:
        decisions = Orchestrator(session).triage()
        if not decisions:
            console.print("[yellow]No pending anomalies to triage. Run `scan` first.[/]")
            return 0
        console.print("[bold]Orchestrator triage[/]")
        for d in decisions:
            col = {"investigate": "green3", "merge": "bright_cyan", "ignore": "grey62"}[d.decision]
            extra = f" → {d.budget_tier}" if d.budget_tier else ""
            extra += f" (into {d.merge_into.slug})" if d.merge_into else ""
            console.print(f"  [{col}]{d.decision:<11}[/]{extra} [orange1]{d.anomaly.slug}[/] "
                          f"— {escape(d.reason)}")
        if args.run:
            console.print("\n[bold]Running triaged investigations…[/]")
            invs = run_triaged(session, decisions, on_step=_print_step)
            console.print(f"[green]Ran {len(invs)} investigation(s).[/]")
    return 0


def cmd_eval(_args) -> int:
    from echolens.eval import run_all
    report = run_all()
    console.print("[bold]EchoLens eval harness[/] (PRD §11)\n")
    for sc in report["scenarios"]:
        mark = "[green3]PASS[/]" if sc["passed"] else "[red]FAIL[/]"
        console.print(f"{mark} [bold]{sc['name']}[/]  status={sc['status']} "
                      f"supported={sc['supported']} tools={sc['tool_calls']}")
        for name, ok in sc["checks"]:
            console.print(f"     {'✓' if ok else '✗'} {escape(name)}")
    console.print("\n[bold]Metrics[/]")
    console.print(f"  scenario pass rate   : {report['scenario_pass_rate_pct']}%")
    console.print(f"  claim grounding      : {report['claim_grounding_pct']}%  (target 100)")
    console.print(f"  honesty              : {report['honesty_pct']}%  (target 100)")
    console.print(f"  budget compliance    : {report['budget_compliance_pct']}%  (target 100)")
    console.print(f"  median tool calls/win: {report['efficiency_median_tool_calls_resolved']}")
    ok = report["all_passed"]
    console.print(f"\n{'[green3]ALL SCENARIOS PASSED[/]' if ok else '[red]SOME SCENARIOS FAILED[/]'}")
    return 0 if ok else 1


def cmd_connect(args) -> int:
    init_db()
    from echolens.collectors.registry import add_source
    with session_scope() as session:
        st = add_source(session, args.source, args.identifier, args.product)
        console.print(f"[green]Connected[/] {st.source} · {st.identifier} (product={st.product})")
    return 0


def cmd_collect(args) -> int:
    init_db()
    from echolens.collectors.registry import run_all
    with session_scope() as session:
        results = run_all(session, limit=args.limit)
        if not results:
            console.print("[yellow]No sources configured. Use `connect` first.[/]")
            return 0
        for r in results:
            col = "green3" if r.ok else "red"
            console.print(f"  [{col}]{r.source}[/] {r.identifier}: fetched {r.fetched}, "
                          f"inserted {r.inserted}" + (f" [red]({r.error})[/]" if r.error else ""))
    return 0


def cmd_embed(_args) -> int:
    init_db()
    from echolens.search.semantic import embed_corpus
    with session_scope() as session:
        counts = embed_corpus(session)
    console.print(f"[green]Embedded[/] {counts}")
    return 0


def cmd_resume(_args) -> int:
    init_db()
    from echolens.investigator.recover import resume_running
    with session_scope() as session:
        acted = resume_running(session, on_step=_print_step)
    console.print(f"[green]Recovery:[/] acted on {len(acted)} interrupted investigation(s): {acted}")
    return 0


def cmd_createuser(args) -> int:
    init_db()
    from echolens.auth import create_user
    with session_scope() as session:
        try:
            u = create_user(session, args.email, args.password, args.role)
        except ValueError as err:
            console.print(f"[red]{err}[/]")
            return 1
        console.print(f"[green]Created user[/] {u.email} (role={u.role})")
    return 0


def cmd_preflight(_args) -> int:
    from echolens.config import settings
    console.print(f"[bold]Preflight[/] · env={settings.echolens_env}")
    problems = settings.check_production_ready()
    console.print(f"  OPENAI_API_KEY set : {bool(settings.openai_api_key)}")
    console.print(f"  DB                 : {'postgres' if not settings.echolens_db_url.startswith('sqlite') else 'sqlite'}")
    console.print(f"  CORS origins       : {settings.cors_list or '(none)'}")
    console.print(f"  JWT secret         : {'strong' if settings.jwt_secret not in settings._INSECURE_SECRETS else 'INSECURE default'}")
    if problems:
        console.print("\n[red]Not production-ready:[/]")
        for p in problems:
            console.print(f"  [red]✗[/] {escape(p)}")
        return 1
    console.print("\n[green3]✓ Ready to deploy[/]")
    return 0


def cmd_serve(args) -> int:
    import uvicorn
    console.print(f"[green]Starting EchoLens API on http://{args.host}:{args.port}[/]")
    if args.schedule:
        from echolens.collectors.scheduler import start_scheduler
        start_scheduler()
    uvicorn.run("echolens.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="echolens")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="generate the synthetic Lumo dataset")
    sub.add_parser("scan", help="run the deterministic anomaly detector")

    p_inv = sub.add_parser("investigate", help="run an investigation")
    p_inv.add_argument("--anomaly", required=True, help="anomaly slug (demo1, demo2)")
    p_inv.add_argument("--tier", default="standard", choices=["quick", "standard", "deep"])

    p_tri = sub.add_parser("triage", help="orchestrator triage of pending anomalies")
    p_tri.add_argument("--run", action="store_true", help="also run the triaged investigations")

    sub.add_parser("eval", help="run the golden-scenario eval harness")

    p_con = sub.add_parser("connect", help="register a real data source (v1.0)")
    p_con.add_argument("source", choices=["play_store", "github"])
    p_con.add_argument("identifier", help="package name / repo")
    p_con.add_argument("--product", default=None)

    p_col = sub.add_parser("collect", help="run all configured collectors once")
    p_col.add_argument("--limit", type=int, default=200)

    sub.add_parser("embed", help="backfill embeddings so semantic search activates")
    sub.add_parser("resume", help="resume investigations interrupted by a crash")
    sub.add_parser("preflight", help="check production config before deploying")

    p_usr = sub.add_parser("createuser", help="create an auth user")
    p_usr.add_argument("email")
    p_usr.add_argument("password")
    p_usr.add_argument("--role", default="viewer", choices=["admin", "reviewer", "viewer"])

    p_srv = sub.add_parser("serve", help="run the FastAPI server")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.add_argument("--reload", action="store_true")
    p_srv.add_argument("--schedule", action="store_true", help="also run the collector scheduler")

    args = parser.parse_args(argv)
    return {
        "seed": cmd_seed, "scan": cmd_scan, "investigate": cmd_investigate,
        "triage": cmd_triage, "eval": cmd_eval, "serve": cmd_serve,
        "connect": cmd_connect, "collect": cmd_collect, "embed": cmd_embed,
        "resume": cmd_resume, "createuser": cmd_createuser, "preflight": cmd_preflight,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
