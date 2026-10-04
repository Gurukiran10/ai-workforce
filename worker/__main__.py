"""CLI:  python -m worker run "<task>" [--role diya] [--scenario T1] [--chaos flaky_submit,over_threshold] [--headed] [--human cli|web]"""
from __future__ import annotations

import argparse
import sys

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from .human import CLIChannel, WebChannel
from .role import ROLES_DIR, list_roles, load_role, route_task
from .runtime import Worker

console = Console()


def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser(prog="worker")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a task")
    r.add_argument("task")
    r.add_argument("--chaos", default="", help="comma-separated sandbox chaos flags (resets the sandbox)")
    r.add_argument("--reset", action="store_true", help="reset the sandbox before running")
    r.add_argument("--headed", action="store_true", help="show the browser")
    r.add_argument("--human", choices=["cli", "web"], default="cli", help="where approvals/questions go")
    r.add_argument("--sandbox", default="http://localhost:8000")
    r.add_argument("--run-id", default=None, help="explicit run id (used by the dashboard launcher)")
    r.add_argument("--role", choices=[x.id for x in list_roles(ROLES_DIR)], default=None,
                   help="which AI employee does the task (default: routed by the task text)")
    args = p.parse_args()

    if args.chaos or args.reset:
        chaos = [c for c in args.chaos.split(",") if c]
        resp = httpx.post(f"{args.sandbox}/__admin/reset", json={"chaos": chaos}, timeout=10)
        resp.raise_for_status()
        console.print(f"[dim]sandbox reset, chaos={chaos}[/]")

    role = load_role(args.role) if args.role else route_task(args.task, list_roles(ROLES_DIR))
    console.print(f"[bold]{role.name}[/] ({role.title}, reports to {role.reports_to}) took the task "
                  f"[dim]- autonomy: {role.autonomy}, systems: {', '.join(role.systems)}[/]")
    worker = Worker(human=CLIChannel(), headless=not args.headed, run_id=args.run_id, role=role.id)
    if args.human == "web":
        worker.human = WebChannel(worker.run_dir)
    console.print(f"[bold]Run {worker.run_id}[/] - live view: {args.sandbox}/runs/{worker.run_id}")
    result = worker.run(args.task)
    style = "green" if result.get("verified") else ("yellow" if result["status"] in ("blocked", "partial") else "red")
    console.print(Panel(f"status: {result['status']}  verified: {result.get('verified')}\n\n{result['summary']}\n\n"
                        f"cost ${result['cost_usd']} · {result['steps']} steps · {result['duration_s']}s\nreport: {result['report']}",
                        title="Result", style=style))
    sys.exit(0 if result["status"] in ("success", "blocked") else 1)


if __name__ == "__main__":
    main()
