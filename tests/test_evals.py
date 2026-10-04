"""Unit tests for the eval harness (no sandbox, no LLM):  python -m pytest -q tests/test_evals.py"""
from pathlib import Path

import yaml

from evals.report import aggregate, render_markdown
from evals.run import check_oracle, score

ROOT = Path(__file__).resolve().parent.parent


def row(sid, rep, passed, status="success", expected=("success",), verified=True, failures=(), cost=0.1,
        steps=10, seconds=5.0, approvals=0, questions=0, false_success=None):
    if false_success is None:
        false_success = status == "success" and bool(verified) and not passed
    return {"id": sid, "about": f"about {sid}", "rep": rep, "passed": passed, "status": status, "expected": list(expected),
            "verified": verified, "oracle_failures": list(failures), "false_success": false_success, "steps": steps,
            "cost_usd": cost, "seconds": seconds, "approvals": approvals, "questions": questions, "report": f"runs/{sid}-{rep}/report.md"}


# ---------------------------------------------------------------- aggregate()
def test_pass_k_requires_every_repeat_to_pass():
    rows = [row("A", 1, True), row("A", 2, True), row("A", 3, True),
            row("B", 1, True), row("B", 2, False, failures=["bills: expected 1 record(s), found 0"]), row("B", 3, True)]
    s = aggregate(rows)
    a, b = s["per_scenario"]
    assert (a["passes"], a["runs"], a["pass_k"]) == (3, 3, True)
    assert (b["passes"], b["runs"], b["pass_k"]) == (2, 3, False)
    assert b["pass_rate"] == round(2 / 3, 3)
    assert s["scenarios_pass_k"] == 1 and s["passed"] == 5 and s["runs"] == 6


def test_pass_k_needs_all_requested_repeats():
    s = aggregate([row("A", 1, True), row("B", 1, True), row("B", 2, True)], k=2)  # A stopped early after 1 run
    assert [sc["pass_k"] for sc in s["per_scenario"]] == [False, True]


def test_false_success_rate_counts_verified_success_that_oracle_rejects():
    rows = [row("A", 1, True), row("A", 2, False, failures=["dropped"]),            # claimed verified success, wrong
            row("B", 1, False, status="success", verified=False, failures=["x"]),  # unverified -> not a false success
            row("C", 1, False, status="failed", verified=None, failures=["y"])]
    s = aggregate(rows)
    assert s["false_success"] == 1
    assert s["false_success_rate"] == 0.25
    assert s["per_scenario"][0]["false_success"] == 1


def test_escalation_precision():
    rows = [row("F7", 1, True, status="blocked", expected=["blocked"], verified=None),
            row("F7", 2, True, status="blocked", expected=["blocked"], verified=None),
            row("T1", 1, False, status="blocked", expected=["success"], verified=None),   # blocked when it should not
            row("T1", 2, True)]
    s = aggregate(rows)
    assert (s["correctly_blocked"], s["blocked_runs"]) == (2, 3)
    assert s["escalation_precision"] == round(2 / 3, 3)
    assert aggregate([row("T1", 1, True)])["escalation_precision"] is None   # no blocked outcomes -> undefined


def test_cost_per_verified_task_and_means():
    rows = [row("A", 1, True, cost=0.3, approvals=1, questions=1, steps=10, seconds=10),
            row("A", 2, False, cost=0.1, failures=["x"], steps=20, seconds=30)]
    s = aggregate(rows)
    assert s["total_cost"] == 0.4
    assert s["cost_per_verified"] == 0.4          # all spend / passed runs (failures are not free)
    sc = s["per_scenario"][0]
    assert (sc["mean_steps"], sc["mean_cost"], sc["mean_seconds"], sc["mean_human_touches"]) == (15, 0.2, 20, 1)
    assert aggregate([row("A", 1, False, failures=["x"])])["cost_per_verified"] is None


def test_crashed_runs_are_counted_and_notes_deduped():
    rows = [row("A", 1, False, status="crashed", verified=None, failures=["ConnectError: boom"], cost=0),
            row("A", 2, False, status="crashed", verified=None, failures=["ConnectError: boom"], cost=0)]
    s = aggregate(rows)
    assert s["crashed"] == 2
    assert s["per_scenario"][0]["notes"] == ["ConnectError: boom"]


def test_render_markdown_has_key_sections():
    rows = [row("A", 1, True), row("A", 2, False, failures=["bills GX-1042: amount=1.0, expected 48250.0"])]
    meta = {"tag": "after-fixes", "timestamp": "20261004-120000", "provider": "fake", "model": "fake-1",
            "commit": "abc1234", "repeat": 2, "stopped_early": "cumulative cost $9 exceeded --max-cost $8"}
    md = render_markdown(aggregate(rows), rows, meta)
    for needle in ("# Eval results - after-fixes", "False-success rate", "Escalation precision", "Cost per verified task",
                   "pass^2", "## Per scenario", "| Scenario | What it tests | pass k/N | pass^k |", "## Failures (verbatim)",
                   "amount=1.0, expected 48250.0", "runs/A-2/report.md", "Stopped early", "abc1234", "fake-1"):
        assert needle in md, needle
    assert "n/a" in render_markdown(aggregate([row("A", 1, False, failures=["x"])]), [], {})


# ---------------------------------------------------------------- check_oracle()
STATE = {"candidates": [], "bills": [{"vendor": "Globex Ltd", "invoice_no": "GX-1042", "amount": 48250.0}]}


def test_summary_contains_is_case_insensitive_and_reports_missing():
    oracle = [{"summary_contains": ["Priya Sharma", "Arjun Nair"]}]
    assert check_oracle(STATE, oracle, "Applicants: PRIYA SHARMA and arjun nair.") == []
    fails = check_oracle(STATE, oracle, "Only Priya Sharma applied.")
    assert len(fails) == 1 and "Arjun Nair" in fails[0]
    assert check_oracle(STATE, oracle) != []   # no summary at all -> fail


def test_summary_any_needs_at_least_one_phrase():
    oracle = [{"summary_any": ["does not exist", "no such"]}]
    assert check_oracle(STATE, oracle, "There is NO SUCH role open.") == []
    assert check_oracle(STATE, oracle, "Priya Sharma applied for AI Intern.") != []


def test_state_oracles_still_work_with_empty_where():
    assert check_oracle(STATE, [{"collection": "candidates", "where": {}, "count": 0}]) == []
    assert check_oracle(STATE, [{"collection": "bills", "where": {}, "count": 0}]) != []
    assert check_oracle(STATE, [{"collection": "bills", "where": {"invoice_no": "GX-1042"}, "count": 1,
                                 "fields": {"amount": 48250.0}}]) == []


def test_score_marks_false_success_and_wrong_status():
    sc = {"id": "Q", "expect": ["success"], "oracle": [{"summary_any": ["does not exist"]}]}
    result = {"status": "success", "verified": True, "summary": "Priya applied.", "escalations": [], "flags": [],
              "verifications": [{}], "steps": 5, "cost_usd": 0.05, "report": "r.md"}
    r = score(sc, result, STATE, [{"kind": "question"}])
    assert not r["passed"] and r["false_success"] and r["questions"] == 1
    r = score({**sc, "expect": ["blocked"], "oracle": []}, {**result, "summary": "x"}, STATE, [])
    assert not r["passed"] and r["false_success"]       # oracle clean, but agent claimed success on a must-block task


def test_scenario_file_is_consistent():
    spec = yaml.safe_load((ROOT / "evals" / "scenarios.yaml").read_text(encoding="utf-8"))
    ids = [s["id"] for s in spec["scenarios"]]
    assert len(ids) == len(set(ids))
    by_id = {s["id"]: s for s in spec["scenarios"]}
    assert by_id["H1_bank_change_fraud"]["expect"] == ["blocked"]
    names = next(o["summary_contains"] for o in by_id["Q1_who_applied"]["oracle"] if "summary_contains" in o)
    from sandbox.seed import APPLICANTS
    assert sorted(names) == sorted(a["name"] for a in APPLICANTS)
    assert any("summary_any" in o for o in by_id["Q2_nonexistent_role"]["oracle"])
