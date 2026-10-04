"""Pure aggregation + markdown rendering for eval results (no I/O, no LLM) so it can be unit-tested.

A *row* is one run of one scenario (scenario id + repeat index). Key fields used here:
    id, about, rep, passed, status, expected, verified, oracle_failures, false_success,
    steps, cost_usd, seconds, approvals, questions, report

Metric definitions (also printed in the markdown header):
    pass_rate            = passed runs / runs
    pass^k (scenario)    = True iff it got all k requested repeats and every one passed
    false_success_rate   = runs where the agent reported verified success but did NOT pass / runs
    escalation_precision = blocked runs where blocked was an expected outcome AND the oracle passed
                           / all runs that ended blocked                      (None if no run ended blocked)
    cost_per_verified    = total cost of ALL runs / runs that passed           (None if nothing passed)
    human_touches        = approvals + questions asked of the human in a run
"""
from __future__ import annotations


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def aggregate(rows: list[dict], k: int | None = None) -> dict:
    """Group rows by scenario and compute per-scenario and suite-level metrics.

    k = repeats requested (defaults to the most runs any scenario got). A scenario that got fewer than k runs
    (suite stopped early) cannot claim pass^k.
    """
    by_id: dict[str, list[dict]] = {}
    for r in rows:  # dicts keep insertion order -> scenarios stay in suite order
        by_id.setdefault(r["id"], []).append(r)
    k = k or max((len(v) for v in by_id.values()), default=0)

    scenarios = []
    for sid, runs in by_id.items():
        passes = sum(bool(r["passed"]) for r in runs)
        statuses: dict[str, int] = {}
        for r in runs:
            statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        notes = list(dict.fromkeys(f for r in runs for f in r["oracle_failures"]))  # dedup, keep order
        scenarios.append({
            "id": sid, "about": runs[0].get("about", ""), "expected": runs[0].get("expected", []),
            "runs": len(runs), "passes": passes, "pass_rate": _ratio(passes, len(runs)),
            "pass_k": len(runs) >= k and passes == len(runs),
            "mean_steps": _mean([r["steps"] for r in runs]),
            "mean_cost": _mean([r["cost_usd"] for r in runs]),
            "mean_seconds": _mean([r["seconds"] for r in runs]),
            "false_success": sum(bool(r["false_success"]) for r in runs),
            "mean_human_touches": _mean([r["approvals"] + r["questions"] for r in runs]),
            "statuses": statuses, "notes": notes,
        })

    n = len(rows)
    passed = sum(bool(r["passed"]) for r in rows)
    total_cost = round(sum(r["cost_usd"] for r in rows), 4)
    blocked = [r for r in rows if r["status"] == "blocked"]
    correctly_blocked = [r for r in blocked if "blocked" in r["expected"] and r["passed"]]
    false_success = sum(bool(r["false_success"]) for r in rows)
    return {
        "k": k,
        "runs": n,
        "passed": passed,
        "pass_rate": _ratio(passed, n),
        "scenarios": len(scenarios),
        "scenarios_pass_k": sum(s["pass_k"] for s in scenarios),
        "false_success": false_success,
        "false_success_rate": _ratio(false_success, n),
        "blocked_runs": len(blocked),
        "correctly_blocked": len(correctly_blocked),
        "escalation_precision": _ratio(len(correctly_blocked), len(blocked)),
        "crashed": sum(r["status"] == "crashed" for r in rows),
        "total_cost": total_cost,
        "cost_per_verified": round(total_cost / passed, 4) if passed else None,
        "total_seconds": round(sum(r["seconds"] for r in rows), 1),
        "mean_human_touches": _mean([r["approvals"] + r["questions"] for r in rows]),
        "per_scenario": scenarios,
    }


def _fmt(x, suffix: str = "") -> str:
    if x is None:
        return "n/a"
    return f"{x:.0%}" if suffix == "%" else f"{x}{suffix}"


def render_markdown(summary: dict, rows: list[dict], meta: dict) -> str:
    s = summary
    k = s["k"]
    cpv = "n/a (nothing passed)" if s["cost_per_verified"] is None else f"${s['cost_per_verified']}"
    md = [
        f"# Eval results - {meta.get('tag', '')} ({meta.get('timestamp', '')})",
        "",
        f"Provider `{meta.get('provider', '?')}` · model `{meta.get('model', '?')}` · commit `{meta.get('commit', 'uncommitted')}` · "
        f"repeats requested: {meta.get('repeat', 1)}",
        "",
    ]
    if meta.get("stopped_early"):
        md += [f"> **Stopped early:** {meta['stopped_early']}", ""]
    md += [
        "| Metric | Value |", "|---|---|",
        f"| Runs passed | **{s['passed']}/{s['runs']}** ({_fmt(s['pass_rate'], '%')}) |",
        f"| Scenarios with pass^{k} (all repeats passed) | **{s['scenarios_pass_k']}/{s['scenarios']}** |",
        f"| **False-success rate** (verified success claimed, oracle disagrees) | **{s['false_success']}/{s['runs']}** ({_fmt(s['false_success_rate'], '%')}) |",
        f"| Escalation precision (correct blocks / all blocked outcomes) | {s['correctly_blocked']}/{s['blocked_runs']} ({_fmt(s['escalation_precision'], '%')}) |",
        f"| Crashed runs | {s['crashed']} |",
        f"| Cost per verified task (total cost / passed runs) | {cpv} |",
        f"| Total cost / total time | ${s['total_cost']} / {s['total_seconds']}s |",
        f"| Human touches per run (approvals + questions, mean) | {s['mean_human_touches']} |",
        "",
        "## Per scenario",
        "",
        "| Scenario | What it tests | pass k/N | pass^k | mean steps | mean cost | mean time | human touches | notes / failures |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for sc in s["per_scenario"]:
        statuses = ", ".join(f"{st}×{c}" for st, c in sc["statuses"].items())
        notes = f"statuses: {statuses} (expected {'/'.join(sc['expected'])})"
        if sc["false_success"]:
            notes += f"; FALSE SUCCESS ×{sc['false_success']}"
        if sc["notes"]:
            notes += "; " + "; ".join(sc["notes"])
        md.append(f"| {sc['id']} | {sc['about']} | {sc['passes']}/{sc['runs']} | {'✅' if sc['pass_k'] else '❌'} | "
                  f"{sc['mean_steps']} | ${sc['mean_cost']} | {sc['mean_seconds']}s | {sc['mean_human_touches']} | "
                  f"{notes.replace('|', '/')} |")

    md += ["", "## Failures (verbatim)", ""]
    failed = [r for r in rows if not r["passed"]]
    if not failed:
        md.append("None.")
    for r in failed:
        md.append(f"- **{r['id']}** rep {r.get('rep', '?')}: status `{r['status']}` (expected {'/'.join(r['expected'])}), "
                  f"verified={r.get('verified')} · report: `{r.get('report') or '-'}`")
        for f in r["oracle_failures"] or ["(oracle passed; final status was not an expected one)"]:
            md.append(f"  - {f}")
    return "\n".join(md) + "\n"
