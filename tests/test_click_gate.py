"""Unit tests for the consequential-click safety gate in worker/tools.py and its helpers.

No browser, no network, no LLM: a FakeBrowser stands in for Playwright, the human is a ScriptedChannel,
and Policy / RunState / Tracer / CompanyMemory are the real objects.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker import tools  # noqa: E402
from worker.browser import BrowserActionError, Observation  # noqa: E402
from worker.human import ScriptedChannel  # noqa: E402
from worker.memory import CompanyMemory  # noqa: E402
from worker.policy import Policy  # noqa: E402
from worker.state import RunState  # noqa: E402
from worker.tools import ToolContext, calculate, click, open_url, press_key, propose_rule, request_approval, type_text  # noqa: E402
from worker.trace import Tracer  # noqa: E402

FORM_URL = "http://localhost/erp/bills/new"
LIST_URL = "http://localhost/erp/bills"
SAVE = 1
APPROVE_ALL = [{"match": ".", "decision": "approve", "note": "ok"}]
DENY_ALL = [{"match": ".", "decision": "deny", "note": "no"}]


def form_page(url=FORM_URL, submit_label="Save bill", form_method="post", extra=()) -> Observation:
    elements = [
        {"id": 0, "tag": "input", "type": "text", "label": "Amount", "form": 1, "value": ""},
        {"id": SAVE, "tag": "button", "label": submit_label, "submit": True, "form": 1, "form_method": form_method},
        *extra,
    ]
    return Observation(url=url, title="New bill", text="New bill form", alerts=[], elements=elements)


class FakeBrowser:
    def __init__(self, values: dict | None = None, http_error=False, raise_on_click=None):
        self.pages = {FORM_URL: form_page(), LIST_URL: Observation(LIST_URL, "Bills", "Bill list", [], [])}
        self.last = self.pages[FORM_URL]
        self.values = values if values is not None else {"Amount": "48,250.00"}
        self.http_error, self.raise_on_click = http_error, raise_on_click
        self.clicks: list[int] = []

    def form_values(self, eid):
        return dict(self.values)

    def click(self, eid):
        self.clicks.append(eid)
        if self.raise_on_click:
            raise self.raise_on_click
        net = ["POST http://localhost/erp/bills 500"] if self.http_error else ["POST http://localhost/erp/bills 200"]
        return Observation(LIST_URL, "Bills", "Saved", [], [], network=net)

    def goto(self, url):
        self.last = self.pages.get(url) or Observation(url, "page", "text " + url, [], [])
        return self.last

    def observe(self):
        return self.last

    def type_text(self, eid, text, clear=True, submit=False):
        return self.last

    def press_key(self, key):
        return self.last


@pytest.fixture
def make_ctx(tmp_path):
    def build(browser=None, approvals=None, autonomy=None, evidence=("Invoice total 48,250.00",), **kw) -> ToolContext:
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir(exist_ok=True)
        (mem_dir / "sop.md").write_text("# SOP\nPay vendor bills within terms.\n", encoding="utf-8")
        state = RunState(goal="Enter the bill")
        for e in evidence:
            state.add_evidence(e)
        return ToolContext(browser=browser or FakeBrowser(), policy=Policy(ROOT / "config" / "policies.yaml", autonomy=autonomy),
                           human=ScriptedChannel(approvals=approvals or []), memory=CompanyMemory(mem_dir), state=state,
                           tracer=Tracer(tmp_path / "run", echo=False), workspace=tmp_path, **kw)
    return build


def events(ctx, kind):
    return [e for e in ctx.tracer.events if e["kind"] == kind]


# ---------------------------------------------------------------- approval tiers
def test_low_amount_executes_without_approval(make_ctx):
    ctx = make_ctx()
    out = click(ctx, SAVE)
    assert "executed" in out and ctx.browser.clicks == [SAVE]
    assert [e.outcome for e in ctx.state.ledger] == ["ok"]
    assert ctx.human.log == []


def test_high_value_asks_finance_manager_and_executes_when_approved(make_ctx):
    ctx = make_ctx(browser=FakeBrowser({"Amount": "1,50,000.00"}), approvals=APPROVE_ALL, evidence=("Total 1,50,000.00",))
    out = click(ctx, SAVE)
    req = ctx.human.log[0]["request"]
    assert req["approver"] == "Finance Manager" and req["policy_rule"] == "high_value_amount"
    assert "executed" in out and ctx.browser.clicks == [SAVE]


def test_denied_approval_blocks_click_and_records_denial(make_ctx):
    ctx = make_ctx(browser=FakeBrowser({"Amount": "1,50,000.00"}), approvals=DENY_ALL, evidence=("Total 1,50,000.00",))
    out = click(ctx, SAVE)
    assert out.startswith("ERROR [approval_denied]")
    assert ctx.browser.clicks == [] and ctx.state.has_denial()
    assert ctx.state.escalations[0]["approved"] is False


def test_very_high_value_goes_to_cfo(make_ctx):
    ctx = make_ctx(browser=FakeBrowser({"Amount": "6,00,000"}), approvals=APPROVE_ALL, evidence=("Total 6,00,000",))
    click(ctx, SAVE)
    req = ctx.human.log[0]["request"]
    assert req["approver"] == "CFO" and req["policy_rule"] == "very_high_value_amount"


def test_approval_does_not_carry_over_to_a_different_amount(make_ctx):
    ctx = make_ctx(browser=FakeBrowser({"Amount": "1,50,000"}), approvals=APPROVE_ALL, evidence=("1,50,000 and 1,60,000",))
    click(ctx, SAVE)
    ctx.browser.values = {"Amount": "1,60,000"}
    click(ctx, SAVE)
    assert len(ctx.human.log) == 2
    assert len(set(ctx.state.approvals)) == 2


# ---------------------------------------------------------------- duplicate / retry ladder
def test_retry_ladder(make_ctx):
    ctx = make_ctx()
    assert "executed" in click(ctx, SAVE)
    assert click(ctx, SAVE).startswith("ERROR [possible_duplicate]")
    assert click(ctx, SAVE, retry_reason="x" * 20).startswith("ERROR [verify_before_retry]")
    open_url(ctx, LIST_URL)  # looking at another page counts as checking
    ctx.browser.last = ctx.browser.pages[FORM_URL]
    assert click(ctx, SAVE, retry_reason="too short").startswith("ERROR [retry_reason_too_short]")
    out = click(ctx, SAVE, retry_reason="list page shows no such bill")
    assert "executed" in out and ctx.browser.clicks == [SAVE, SAVE]
    assert ctx.state.ledger[-1].retry_reason == "list page shows no such bill"


def test_http_error_is_ledgered_and_warns_agent(make_ctx):
    ctx = make_ctx(browser=FakeBrowser(http_error=True))
    out = click(ctx, SAVE)
    assert ctx.state.ledger[0].outcome == "http_error"
    assert "outcome: http_error" in out and "check before retrying" in out


def test_browser_exception_is_ledgered_as_unknown(make_ctx):
    ctx = make_ctx(browser=FakeBrowser(raise_on_click=BrowserActionError("timeout", "page hung", "wait")))
    out = click(ctx, SAVE)
    assert out.startswith("ERROR [timeout]") and "verify before retrying" in out
    assert ctx.state.ledger[0].outcome == "unknown"
    assert click(ctx, SAVE).startswith("ERROR [possible_duplicate]")


# ---------------------------------------------------------------- provenance
def test_unsupported_value_blocked_with_trace_event(make_ctx):
    ctx = make_ctx(browser=FakeBrowser({"Amount": "99,999.00"}))
    out = click(ctx, SAVE)
    assert out.startswith("ERROR [unsupported_value]") and "Amount" in out
    assert ctx.browser.clicks == []
    assert events(ctx, "provenance")[0]["unsupported"] == ["Amount"]


@pytest.mark.parametrize("typed", ["48250.00", "48,250.00", "48250"])
def test_numbers_compare_by_value_not_formatting(typed):
    assert tools._unsupported_values({"Amount": typed}, ["Invoice total Rs. 48,250.00"]) == []


def test_notes_and_select_options_are_exempt():
    fields = {"Internal note": "anything at all", "Category": "Travel", "Vendor": "Unseen Corp"}
    assert tools._unsupported_values(fields, ["x"], choices=["Travel"]) == ["Vendor"]


def test_text_value_must_appear_in_evidence_case_insensitively():
    assert tools._unsupported_values({"Vendor": "ACME  Ltd"}, ["vendor: acme ltd"]) == []
    assert tools._unsupported_values({"Vendor": "Other"}, ["vendor: acme ltd"]) == ["Vendor"]


def test_select_choices_from_page_are_exempt_in_click(make_ctx):
    sel = {"id": 2, "tag": "select", "label": "Category", "form": 1, "options": ["Travel", "Rent"]}
    b = FakeBrowser({"Amount": "48,250.00", "Category": "Rent"})
    b.last = b.pages[FORM_URL] = form_page(extra=[sel])
    assert "executed" in click(make_ctx(browser=b), SAVE)


# ---------------------------------------------------------------- policy / mode gates
def test_delete_button_is_policy_denied(make_ctx):
    b = FakeBrowser()
    b.last = form_page(submit_label="Delete", form_method="get")
    ctx = make_ctx(browser=b)
    assert ctx.policy.is_consequential(b.last.element(SAVE))
    assert click(ctx, SAVE).startswith("ERROR [policy_denied]")
    assert b.clicks == []


def test_read_only_context_blocks_consequential_click(make_ctx):
    ctx = make_ctx(read_only=True)
    assert click(ctx, SAVE).startswith("ERROR [read_only]")
    assert ctx.browser.clicks == []


def test_non_consequential_click_passes_straight_through(make_ctx):
    b = FakeBrowser()
    b.last = form_page(submit_label="Search", form_method="get")
    ctx = make_ctx(browser=b)
    out = click(ctx, SAVE)
    assert "executed" not in out and b.clicks == [SAVE]
    assert ctx.state.ledger == [] and ctx.human.log == []


def test_stale_element_id(make_ctx):
    assert click(make_ctx(), 99).startswith("ERROR [stale_element]")


def test_supervised_autonomy_asks_even_for_low_amount(make_ctx):
    ctx = make_ctx(autonomy="supervised", approvals=APPROVE_ALL, approver="Team Lead")
    click(ctx, SAVE)
    req = ctx.human.log[0]["request"]
    assert req["policy_rule"] == "supervised_mode" and req["approver"] == "Team Lead"
    assert ctx.browser.clicks == [SAVE]


# ---------------------------------------------------------------- role boundary
def test_role_boundary(make_ctx):
    ctx = make_ctx(allowed_apps=["mail"], role_id="diya")
    assert open_url(ctx, "http://localhost/erp/bills").startswith("ERROR [outside_role_boundary]")
    assert events(ctx, "boundary")[0]["app"] == "erp"
    assert not open_url(ctx, "http://localhost/mail/inbox").startswith("ERROR")
    assert not open_url(ctx, "http://localhost/").startswith("ERROR")  # root has no app segment


def test_read_only_context_skips_role_boundary(make_ctx):
    ctx = make_ctx(allowed_apps=["mail"], read_only=True)
    assert not open_url(ctx, "http://localhost/erp/bills").startswith("ERROR")


def test_link_click_into_other_app_is_blocked(make_ctx):
    b = FakeBrowser()
    b.last = form_page(extra=[{"id": 5, "tag": "a", "label": "ERP", "href": "http://localhost/erp/bills"}])
    ctx = make_ctx(browser=b, allowed_apps=["mail"])
    assert click(ctx, 5).startswith("ERROR [outside_role_boundary]")
    assert b.clicks == []


# ---------------------------------------------------------------- bypass routes
def test_submit_via_typing_or_enter_is_refused(make_ctx):
    ctx = make_ctx()
    assert type_text(ctx, 0, "100", submit=True).startswith("ERROR [use_click_to_submit]")
    assert press_key(ctx, "Enter").startswith("ERROR [use_click_to_submit]")
    assert not press_key(ctx, "Tab").startswith("ERROR")


def test_type_submit_allowed_in_non_consequential_form(make_ctx):
    b = FakeBrowser()
    b.last = form_page(submit_label="Search", form_method="get")
    assert not type_text(make_ctx(browser=b), 0, "acme", submit=True).startswith("ERROR")


# ---------------------------------------------------------------- request_approval, calculate, propose_rule
def test_request_approval_denial_is_recorded(make_ctx):
    ctx = make_ctx(approvals=DENY_ALL)
    out = request_approval(ctx, "Wire money", "details", "reason")
    assert out.startswith("DENIED") and ctx.state.has_denial()
    assert ctx.state.escalations[-1]["type"] == "approval" and ctx.state.escalations[-1]["approved"] is False


def test_calculate_dates_expressions_and_rejection(make_ctx):
    ctx = make_ctx()
    assert calculate(ctx, "net 30", date="01-01-2025", add_days=30).startswith("31-01-2025")
    assert calculate(ctx, "gst", expression="1,00,000 * 1.18").startswith("118000.00")
    assert calculate(ctx, "x", expression="__import__('os')").startswith("ERROR [bad_expression]")
    assert calculate(ctx, "x", date="2025-01-01").startswith("ERROR [bad_date]")
    assert calculate(ctx, "x").startswith("ERROR [bad_arguments]")


def test_calculated_value_passes_provenance_in_click(make_ctx):
    ctx = make_ctx(browser=FakeBrowser({"Amount": "59,000.00"}), evidence=())
    assert click(ctx, SAVE).startswith("ERROR [unsupported_value]")
    calculate(ctx, "half of base", expression="118000 / 2")
    assert "executed" in click(ctx, SAVE)


def test_propose_rule_writes_pending_file_never_indexed(make_ctx, tmp_path):
    ctx = make_ctx(role_id="diya", run_id="r1")
    out = propose_rule(ctx, "Always zebra-quokka verify GSTIN", "sop.md", "human said so")
    files = list((tmp_path / "memory" / "_proposed").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["status"] == "pending"
    assert files[0].stem in out
    ctx.memory.reindex()
    assert ctx.memory.search("zebra-quokka") == []
    assert propose_rule(ctx, "  ", "sop.md", "r").startswith("ERROR [bad_arguments]")
