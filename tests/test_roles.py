"""AI employees: roles, data boundary, scoped memory, learning loop, trust ladder (no browser, no LLM)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from worker.human import ScriptedChannel
from worker.learning import accept_proposal, list_proposals, recommended_autonomy, reject_proposal, trust_record
from worker.memory import CompanyMemory
from worker.policy import Policy
from worker.role import ROLES_DIR, list_roles, load_role, route_task
from worker.state import RunState
from worker.tools import READ_ONLY_TOOLS, ToolContext, run_tool
from worker.trace import Tracer

ROOT = Path(__file__).resolve().parent.parent
POLICY_FILE = ROOT / "config" / "policies.yaml"


class FakeBrowser:
    last = None

    def goto(self, url):  # must never be reached when the boundary refuses
        raise AssertionError(f"browser opened {url}")


def make_ctx(tmp_path, **kw) -> ToolContext:
    mem = tmp_path / "memory"
    if not mem.exists():
        shutil.copytree(ROOT / "memory", mem, ignore=shutil.ignore_patterns("_proposed", "learned_*.md"))
    return ToolContext(FakeBrowser(), Policy(POLICY_FILE), ScriptedChannel(), CompanyMemory(mem), RunState("t"),
                       Tracer(tmp_path / "run", echo=False), tmp_path, **kw)


# ------------------------------------------------------------------ roles
def test_load_list_and_route_roles():
    diya = load_role("diya")
    assert diya.title == "Accounts Payable Associate" and diya.systems == ["mail", "erp"]
    assert diya.approver == "Meera Rao (Finance Manager)" and diya.autonomy == "standard"
    roles = list_roles(ROLES_DIR)
    assert [r.id for r in roles] == ["diya", "kabir"]
    assert route_task("Enter the latest Globex invoice into the accounts system", roles).id == "diya"
    assert route_task("Screen the new applicants for the Backend Engineer role", roles).id == "kabir"
    assert route_task("Something unrelated", roles).id == roles[0].id
    block = load_role("kabir").prompt_block("Acme")
    assert "You are Kabir, Recruiting Coordinator at Acme" in block and "mail, jobs, ats" in block


# ------------------------------------------------------------------ data boundary
def test_role_boundary_refuses_other_systems(tmp_path):
    ctx = make_ctx(tmp_path, allowed_apps=["mail", "ats"], role_id="kabir", role_title="Recruiting Coordinator")
    out = run_tool(ctx, "open_url", {"url": "http://localhost:8000/erp/bills"})
    assert out.startswith("ERROR [outside_role_boundary]")
    assert "Your role (Recruiting Coordinator) is not permitted to use the 'erp' system." in out
    assert any(e["kind"] == "boundary" for e in ctx.tracer.events)


def test_boundary_skipped_for_verifier_and_unrestricted(tmp_path):
    from worker.tools import _outside_role
    ctx = make_ctx(tmp_path, allowed_apps=["mail"])
    assert _outside_role(ctx, "http://localhost:8000/mail/inbox") is None
    assert _outside_role(ctx, "http://localhost:8000/") is None  # root / empty app is allowed
    ctx.read_only = True
    assert _outside_role(ctx, "http://localhost:8000/erp") is None
    assert _outside_role(make_ctx(tmp_path), "http://localhost:8000/erp") is None  # allowed_apps=None


# ------------------------------------------------------------------ scoped memory
def test_scoped_memory_search_returns_only_role_files_and_learned_rules(tmp_path):
    ctx = make_ctx(tmp_path)
    (ctx.memory.dir / "learned_rules.md").write_text(
        "# Learned rules (human-approved)\n- [kabir] Backend engineer approval limit questions go to Vikram\n", encoding="utf-8")
    ctx.memory.reindex()
    files = load_role("kabir").knowledge
    hits = ctx.memory.search("approval limit for bills backend engineer", k=10, files=files)
    assert hits and {h["file"] for h in hits} <= set(files) | {"learned_rules.md"}
    assert any(h["file"] == "learned_rules.md" for h in hits)
    assert any(h["file"] == "sop_accounts_payable.md" for h in ctx.memory.search("approval limit for bills", k=10))


def test_memory_creates_learned_rules_and_ignores_proposals(tmp_path):
    (tmp_path / "_proposed").mkdir()
    (tmp_path / "_proposed" / "x.md").write_text("# secret unapproved zebra rule\n", encoding="utf-8")
    mem = CompanyMemory(tmp_path)
    assert (tmp_path / "learned_rules.md").read_text(encoding="utf-8").startswith("# Learned rules (human-approved)")
    assert mem.search("zebra") == []


# ------------------------------------------------------------------ learning loop
def test_propose_rule_writes_pending_json(tmp_path):
    ctx = make_ctx(tmp_path, role_id="diya", run_id="run-1")
    out = run_tool(ctx, "propose_rule", {"rule": "Vendor X bills default to 30-day terms.",
                                         "applies_to": "sop_accounts_payable.md", "reason": "Meera said so"})
    assert "NOT a rule" in out
    [p] = list_proposals(ctx.memory.dir)
    assert set(p) == {"id", "role", "rule", "applies_to", "reason", "run_id", "created", "status"}
    assert (p["role"], p["run_id"], p["status"], len(p["id"])) == ("diya", "run-1", "pending", 8)
    assert any(e["kind"] == "learning" and e["status"] == "proposed" for e in ctx.tracer.events)
    assert "propose_rule" not in READ_ONLY_TOOLS


def test_accept_and_reject_are_idempotent(tmp_path):
    ctx = make_ctx(tmp_path, role_id="diya", run_id="run-7")
    mem = ctx.memory.dir
    for rule in ("Rule A.", "Rule B."):
        run_tool(ctx, "propose_rule", {"rule": rule, "applies_to": "sop_accounts_payable.md", "reason": "r"})
    a, b = sorted(list_proposals(mem), key=lambda p: p["rule"])
    assert accept_proposal(mem, a["id"])["status"] == "accepted"
    assert accept_proposal(mem, a["id"])["status"] == "accepted"
    assert reject_proposal(mem, a["id"])["status"] == "accepted"  # first decision stands
    assert reject_proposal(mem, b["id"])["status"] == "rejected"
    assert accept_proposal(mem, b["id"])["status"] == "rejected"
    lines = (mem / "learned_rules.md").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Learned rules (human-approved)"
    assert lines.count("- [diya] Rule A. (learned from run run-7, approved by a human)") == 1
    assert not any("Rule B." in ln for ln in lines)
    assert json.loads((mem / "_proposed" / f"{a['id']}.json").read_text(encoding="utf-8"))["status"] == "accepted"


# ------------------------------------------------------------------ trust ladder
def _result(runs: Path, run_id: str, role: str, status: str, verified, cost=0.1):
    (runs / run_id).mkdir(parents=True)
    (runs / run_id / "result.json").write_text(json.dumps(
        {"run_id": run_id, "role": role, "status": status, "verified": verified, "cost_usd": cost}), encoding="utf-8")


def test_trust_record_and_recommended_autonomy(tmp_path):
    _result(tmp_path, "r1", "diya", "success", True)
    _result(tmp_path, "r2", "diya", "blocked", None)
    _result(tmp_path, "r3", "kabir", "success", True)
    rec = trust_record(tmp_path, "diya")
    assert (rec["tasks"], rec["verified"], rec["escalated"], rec["failed"], rec["cost_usd"]) == (2, 1, 1, 0, 0.2)
    assert recommended_autonomy(rec)[0] == "supervised"  # too few verified tasks
    _result(tmp_path, "r4", "diya", "success", True)
    _result(tmp_path, "r5", "diya", "success", True)
    assert recommended_autonomy(trust_record(tmp_path, "diya"))[0] == "standard"
    _result(tmp_path, "r6", "diya", "unverified", False)
    rec = trust_record(tmp_path, "diya")
    assert rec["unverified"] == 1 and recommended_autonomy(rec)[0] == "supervised"


# ------------------------------------------------------------------ autonomy
def test_supervised_autonomy_requires_approval_for_any_consequential_action():
    url, button, fields = "http://x/erp/bills/new", "Save bill", {"Amount": "48250.00"}
    assert Policy(POLICY_FILE).evaluate(url, button, fields).action == "allow"
    d = Policy(POLICY_FILE, autonomy="supervised").evaluate(url, button, fields)
    assert d.action == "require_approval" and d.rule_id == "supervised_mode"
    assert Policy(POLICY_FILE, autonomy="supervised").evaluate("http://x/erp/bills/4", "Delete bill", {}).action == "deny"


def test_supervised_click_asks_role_approver(tmp_path):
    from worker.browser import Observation
    button = {"id": 1, "tag": "button", "label": "Save record", "form": "f1"}
    page = Observation("http://localhost:8000/app/records/new", "New", "Amount 100", [], [button])

    class FormBrowser(FakeBrowser):
        last = page

        def form_values(self, eid):
            return {"Amount": "100"}

    ctx = make_ctx(tmp_path, approver="Meera Rao (Finance Manager)")
    ctx.browser = FormBrowser()
    ctx.policy = Policy(POLICY_FILE, autonomy="supervised")
    ctx.state.add_evidence("Amount 100")
    out = run_tool(ctx, "click", {"element_id": 1})
    assert out.startswith("ERROR [approval_denied]")  # ScriptedChannel denies by default
    [request] = [x["request"] for x in ctx.human.log if x["kind"] == "approval"]
    assert request["policy_rule"] == "supervised_mode" and request["approver"] == "Meera Rao (Finance Manager)"


def test_calculate_is_done_by_code_and_becomes_evidence(tmp_path):
    from worker.human import ScriptedChannel
    from worker.memory import CompanyMemory
    from worker.policy import Policy
    from worker.state import RunState
    from worker.tools import ToolContext, _unsupported_values, run_tool
    from worker.trace import Tracer
    root = Path(__file__).resolve().parent.parent
    mem = tmp_path / "mem"; mem.mkdir()
    ctx = ToolContext(None, Policy(root / "config" / "policies.yaml"), ScriptedChannel(), CompanyMemory(mem),
                      RunState("t"), Tracer(tmp_path, echo=False), tmp_path)
    out = run_tool(ctx, "calculate", {"reason": "learned rule: due = invoice date + 15 days", "date": "01-10-2026", "add_days": 15})
    assert out.startswith("16-10-2026")
    assert _unsupported_values({"Due date": "16-10-2026"}, ctx.state.evidence) == []
    assert run_tool(ctx, "calculate", {"reason": "r", "expression": "40,889.83 * 1.18"}).startswith("48250.00")
    assert run_tool(ctx, "calculate", {"reason": "r", "expression": "__import__('os')"}).startswith("ERROR")
