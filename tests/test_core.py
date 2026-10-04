"""Fast unit tests (no browser, no LLM):  python -m pytest -q"""
import re
from pathlib import Path

from worker.guards import LoopGuard
from worker.memory import CompanyMemory
from worker.policy import Policy

ROOT = Path(__file__).resolve().parent.parent
policy = Policy(ROOT / "config" / "policies.yaml")


def test_no_task_specific_code_in_worker():
    """Generalization guard: the agent code must not know about apps, vendors, people or task steps."""
    banned = re.compile(r"globex|initech|ledgerly|acmemail|hirehub|talentdesk|invoice|candidate|/erp|/ats|/mail|/jobs|GX-\d", re.I)
    offenders = []
    for f in (ROOT / "worker").glob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line):
                offenders.append(f"{f.name}:{i}: {line.strip()}")
    assert not offenders, "task-specific logic leaked into worker/:\n" + "\n".join(offenders)


def test_policy_requires_approval_above_limit():
    d = policy.evaluate("http://localhost:8000/erp/bills/new", "Save bill", {"Amount (INR, incl. GST)": "1,85,000.00"})
    assert d.action == "require_approval" and d.rule_id == "high_value_amount"


def test_policy_allows_below_limit_and_relabelled_fields():
    assert policy.evaluate("http://x/erp/bills/new", "Save bill", {"Amount": "48250.00"}).action == "allow"
    assert policy.evaluate("http://x/erp/bills/new", "Post to ledger", {"Total payable (INR)": "185000"}).action == "require_approval"


def test_policy_bank_change_and_delete():
    assert policy.evaluate("http://x/erp/vendors/2", "Update vendor bank details", {"Bank account number": "1"}).action == "require_approval"
    assert policy.evaluate("http://x/erp/bills/4", "Delete bill", {}).action == "deny"


def test_consequential_detection():
    assert policy.is_consequential({"tag": "button", "label": "Save bill"})
    assert policy.is_consequential({"tag": "button", "label": "Schedule interview"})
    assert not policy.is_consequential({"tag": "button", "label": "Search"})
    assert not policy.is_consequential({"tag": "a", "label": "Save bill"})  # links are navigation


def test_loop_guard_escalates_then_trips():
    g = LoopGuard()
    msgs = [g.check("read_page", {}, "u") for _ in range(8)]
    assert msgs[0] is None and "repeated" in msgs[2] and "Change approach" in msgs[4]
    assert g.tripped and "CIRCUIT BREAKER" in msgs[7]


def test_memory_retrieves_sops():
    mem = CompanyMemory(ROOT / "memory")
    assert any("1,00,000" in h["text"] for h in mem.search("approval limit for bills"))
    assert any(h["file"] == "jd_backend_engineer.md" for h in mem.search("backend engineer must-have criteria"))


def test_human_tools_do_not_crash(tmp_path):
    """Regression: ask_human once crashed inside the tracer (keyword clash) and the agent could never ask."""
    from worker.human import ScriptedChannel
    from worker.state import RunState
    from worker.tools import ToolContext, run_tool
    from worker.trace import Tracer
    human = ScriptedChannel(answers=[{"match": "due", "answer": "31-10-2026"}], approvals=[{"match": ".*", "decision": "approve"}])
    ctx = ToolContext(None, policy, human, CompanyMemory(ROOT / "memory"), RunState("t"), Tracer(tmp_path, echo=False), tmp_path)
    assert run_tool(ctx, "ask_human", {"question": "What is the due date?"}) == "Human answered: 31-10-2026"
    assert run_tool(ctx, "request_approval", {"action": "a", "details": "d", "reason": "r"}).startswith("APPROVED")
    assert run_tool(ctx, "flag_concern", {"concern": "c", "evidence": "e"}).startswith("Concern recorded")


def test_amount_parsing_indian_formats():
    from worker.policy import _number
    assert _number("Rs. 1,85,000") == 185000
    assert _number("INR 1,85,000.00") == 185000
    assert _number("₹1.85 lakh") == 185000
    assert _number("2 crore") == 20000000
    assert _number("185000") == 185000 and _number("48,250.00") == 48250
    assert _number("no amount here") is None


def test_post_form_submit_is_consequential_even_with_neutral_label():
    assert policy.is_consequential({"tag": "button", "label": "Continue", "submit": True, "form_method": "post"})
    assert not policy.is_consequential({"tag": "button", "label": "Go", "submit": True, "form_method": "get"})
    assert not policy.is_consequential({"tag": "a", "label": "Continue", "form_method": "post"})


def test_policy_tier_picks_cfo_for_very_high_amount():
    d = policy.evaluate("http://x/erp/bills/new", "Save bill", {"Amount": "6,00,000"})
    assert d.action == "require_approval" and d.rule_id == "very_high_value_amount" and d.approver == "CFO"
    assert policy.evaluate("http://x/erp/bills/new", "Save bill", {"Amount": "185000"}).approver == "Finance Manager"


def test_unsupported_values_provenance():
    from worker.tools import _unsupported_values
    evidence = ["Acme Supplies Pvt Ltd\nInvoice No: AB-12\nInvoice Date: 01-10-2026\nTOTAL PAYABLE 48,250.00"]
    ok = {"Supplier": "Acme Supplies Pvt Ltd", "Ref": "AB-12", "Amount": "48250.00", "Date": "01-10-2026", "Empty": ""}
    assert _unsupported_values(ok, evidence) == []
    assert _unsupported_values({"Amount": "500000"}, evidence) == ["Amount"]  # invented amount
    assert _unsupported_values({"Due date": "15-10-2026"}, evidence) == ["Due date"]  # date not in any source
    assert _unsupported_values({"Internal memo": "entered by AI worker"}, evidence) == []  # notes are free text
    assert _unsupported_values({"Stage": "Phone screen"}, evidence, ["New", "Phone screen"]) == []  # dropdown choice


def test_denied_approval_is_recorded(tmp_path):
    from worker.human import ScriptedChannel
    from worker.state import RunState
    from worker.tools import ToolContext, run_tool
    from worker.trace import Tracer
    state = RunState("t")
    ctx = ToolContext(None, policy, ScriptedChannel(approvals=[{"match": ".*", "decision": "deny"}]),
                      CompanyMemory(ROOT / "memory"), state, Tracer(tmp_path, echo=False), tmp_path)
    assert not state.has_denial()
    assert run_tool(ctx, "request_approval", {"action": "pay vendor", "details": "d", "reason": "r"}).startswith("DENIED")
    assert state.has_denial() and state.denied_actions == ["pay vendor"]
