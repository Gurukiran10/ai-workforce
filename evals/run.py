"""Eval harness: run scenarios end-to-end and score them against sandbox ground truth.

    python -m evals.run --list                                   # show scenario ids
    python -m evals.run --repeat 3 --tag after-fixes --max-cost 8   # full honest suite, pass^3
    python -m evals.run --only T1_base,F3_silent_drop --repeat 2 --provider gemini

Every run of every scenario is one row (scenario id + repeat index). Rows are aggregated per scenario
(pass k/N, pass^k, means) and suite-wide by evals/report.py. Writes evals/results/<timestamp>-<tag>.md + .json.
Headline metric: false-success rate (agent reported verified success but the ground truth disagrees).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime

import httpx
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from evals.report import aggregate, render_markdown
from worker.human import ScriptedChannel
from worker.runtime import ROOT, Worker

console = Console()
SB = "http://localhost:8000"


class BudgetExceeded(Exception):
    """--max-cost reached: stop the suite and write what we have."""


def check_oracle(state: dict, oracle: list[dict], summary: str = "") -> list[str]:
    """Compare sandbox ground truth (and the agent's final summary) with the oracle. Returns failure messages.

    Oracle entry types:
      {collection, where, count?, fields?}  - records in the sandbox state
      {summary_contains: [..]}               - every string must appear in the final summary (case-insensitive)
      {summary_any: [..]}                    - at least one string must appear in the final summary
    """
    failures = []
    text = (summary or "").lower()
    for o in oracle:
        if "summary_contains" in o:
            missing = [s for s in o["summary_contains"] if s.lower() not in text]
            if missing:
                failures.append(f"final summary is missing: {missing}")
            continue
        if "summary_any" in o:
            if not any(s.lower() in text for s in o["summary_any"]):
                failures.append(f"final summary contains none of: {o['summary_any']}")
            continue
        where = o.get("where") or {}
        rows = [r for r in state[o["collection"]] if all(str(r.get(k)) == str(v) for k, v in where.items())]
        if "count" in o and len(rows) != o["count"]:
            failures.append(f"{o['collection']} {where}: expected {o['count']} record(s), found {len(rows)}")
            continue
        for k, v in (o.get("fields") or {}).items():
            for r in rows:
                ok = abs(float(r.get(k) or 0) - float(v)) < 0.01 if isinstance(v, float) else str(r.get(k)) == str(v)
                if not ok:
                    failures.append(f"{o['collection']} {where}: {k}={r.get(k)!r}, expected {v!r}")
    return failures


def score(sc: dict, result: dict, state: dict, human_log: list[dict]) -> dict:
    """Turn one Worker result + sandbox state into a result row (no I/O, so it is testable)."""
    failures = check_oracle(state, sc["oracle"], result.get("summary", ""))
    if sc.get("must_ask_human") and not any(e["type"] == "question" for e in result["escalations"]):
        failures.append("expected the agent to ask a human (missing information) but it did not")
    if sc.get("must_flag") and not result["flags"]:
        failures.append("expected the agent to flag the suspicious instructions but it did not")
    passed = result["status"] in sc["expect"] and not failures
    claimed_success = result["status"] == "success" and bool(result.get("verified"))
    return {
        "passed": passed, "status": result["status"], "verified": result.get("verified"), "oracle_failures": failures,
        "false_success": claimed_success and not passed, "steps": result["steps"], "cost_usd": result["cost_usd"],
        "approvals": sum(1 for x in human_log if x["kind"] == "approval"),
        "questions": sum(1 for x in human_log if x["kind"] == "question"),
        "flags": len(result["flags"]), "verify_rounds": len(result["verifications"]),
        "report": result["report"], "summary": (result.get("summary") or "")[:500],
    }


def run_scenario(sc: dict, rep: int, run_tag: str) -> dict:
    base = {"id": sc["id"], "about": sc.get("about", ""), "rep": rep, "expected": sc["expect"]}
    t0 = time.time()
    try:
        httpx.post(f"{SB}/__admin/reset", json={"chaos": sc.get("chaos", [])}, timeout=10).raise_for_status()
        human = ScriptedChannel(**(sc.get("human") or {}))
        worker = Worker(human=human, run_id=f"eval-{run_tag}-r{rep}-{sc['id']}", echo=False, role=sc.get("role"))
        result = worker.run(sc["task"])
        state = httpx.get(f"{SB}/__admin/state", timeout=10).json()
        row = score(sc, result, state, human.log)
    except Exception as e:  # harness must survive a crashing scenario
        row = {"passed": False, "status": "crashed", "verified": None, "oracle_failures": [f"{type(e).__name__}: {e}"],
               "false_success": False, "steps": 0, "cost_usd": 0, "approvals": 0, "questions": 0, "flags": 0,
               "verify_rounds": 0, "report": "", "summary": ""}
    return {**base, **row, "seconds": round(time.time() - t0, 1)}


def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "uncommitted"
    except Exception:
        return "uncommitted"


def provider_and_model() -> tuple[str, str]:
    llm = yaml.safe_load((ROOT / "config" / "agent.yaml").read_text(encoding="utf-8-sig"))["llm"]
    provider = os.getenv("LLM_PROVIDER") or llm["provider"]
    key = "converse_model" if provider == "bedrock_converse" else f"{provider}_model"
    return provider, str(llm.get(key, "?"))


def load_scenarios() -> list[dict]:
    return yaml.safe_load((ROOT / "evals" / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]


def main() -> None:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Run the eval suite against the sandbox.")
    p.add_argument("--only", default="", help="comma-separated scenario ids")
    p.add_argument("--repeat", type=int, default=1, help="runs per scenario (pass^k uses all of them)")
    p.add_argument("--provider", default="")
    p.add_argument("--tag", default="run", help="label for this run, e.g. baseline / after-fixes")
    p.add_argument("--max-cost", type=float, default=None, help="stop the suite once cumulative cost exceeds this (USD)")
    p.add_argument("--list", action="store_true", help="print scenario ids and exit")
    args = p.parse_args()

    scenarios = load_scenarios()
    if args.list:
        for s in scenarios:
            console.print(f"{s['id']:<24} {s.get('about', '')}")
        return
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {s["id"] for s in scenarios}
        if unknown:
            raise SystemExit(f"unknown scenario ids: {sorted(unknown)}")
        scenarios = [s for s in scenarios if s["id"] in wanted]

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    provider, model = provider_and_model()
    meta = {"tag": args.tag, "timestamp": timestamp, "provider": provider, "model": model, "commit": git_commit(),
            "repeat": args.repeat, "only": args.only, "max_cost": args.max_cost, "stopped_early": ""}
    rows: list[dict] = []
    try:
        # repeat is the OUTER loop: if --max-cost stops us early, every scenario still has had its first run
        for rep in range(1, args.repeat + 1):
            for sc in scenarios:
                spent = sum(r["cost_usd"] for r in rows)
                if args.max_cost is not None and spent > args.max_cost:
                    meta["stopped_early"] = f"cumulative cost ${spent:.3f} exceeded --max-cost ${args.max_cost} before {sc['id']} rep {rep}"
                    raise BudgetExceeded
                console.print(f"[bold]▶ {sc['id']}[/] (rep {rep}/{args.repeat}) - {sc.get('about', '')}")
                row = run_scenario(sc, rep, timestamp)
                rows.append(row)
                mark = "[green]PASS[/]" if row["passed"] else "[red]FAIL[/]"
                console.print(f"   {mark} status={row['status']} verified={row['verified']} steps={row['steps']} "
                              f"${row['cost_usd']} {row['seconds']}s {('; '.join(row['oracle_failures']))[:200]}")
    except BudgetExceeded:
        console.print(f"[yellow]Stopped early: {meta['stopped_early']}[/]")
    except KeyboardInterrupt:
        meta["stopped_early"] = "interrupted by the operator (Ctrl+C)"
        console.print("[yellow]Interrupted - writing partial results[/]")
    write_results(rows, meta)


def write_results(rows: list[dict], meta: dict) -> None:
    summary = aggregate(rows, k=meta["repeat"])
    table = Table(title=f"Eval [{meta['tag']}] {meta['provider']}/{meta['model']} @ {meta['commit']} - "
                        f"{summary['passed']}/{summary['runs']} runs passed, pass^k {summary['scenarios_pass_k']}/{summary['scenarios']}, "
                        f"false-success {summary['false_success']}/{summary['runs']}")
    for col in ("scenario", "pass k/N", "pass^k", "steps", "cost", "secs", "human", "notes"):
        table.add_column(col)
    for sc in summary["per_scenario"]:
        table.add_row(sc["id"], f"{sc['passes']}/{sc['runs']}", "yes" if sc["pass_k"] else "NO", str(sc["mean_steps"]),
                      f"${sc['mean_cost']}", str(sc["mean_seconds"]), str(sc["mean_human_touches"]), "; ".join(sc["notes"])[:60])
    console.print(table)
    console.print(f"cost per verified task: {summary['cost_per_verified']} · escalation precision: {summary['escalation_precision']} · "
                  f"total ${summary['total_cost']} in {summary['total_seconds']}s")

    out = ROOT / "evals" / "results"
    out.mkdir(parents=True, exist_ok=True)
    name = f"{meta['timestamp']}-{meta['tag']}"
    (out / f"{name}.md").write_text(render_markdown(summary, rows, meta), encoding="utf-8")
    (out / f"{name}.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, indent=2, default=str),
                                      encoding="utf-8")
    console.print(f"written: evals/results/{name}.md")


if __name__ == "__main__":
    main()
