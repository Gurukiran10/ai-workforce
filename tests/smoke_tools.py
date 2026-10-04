"""No-LLM smoke test: drive the worker's tools by hand through the invoice task with chaos.

Run with the sandbox up:  python tests/smoke_tools.py
"""
import re
import shutil
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker.browser import Browser  # noqa: E402
from worker.human import ScriptedChannel  # noqa: E402
from worker.memory import CompanyMemory  # noqa: E402
from worker.policy import Policy  # noqa: E402
from worker.state import RunState  # noqa: E402
from worker.tools import ToolContext, run_tool  # noqa: E402
from worker.trace import Tracer  # noqa: E402

SB = "http://localhost:8000"


def ids(text: str, pattern: str) -> list[int]:
    return [int(m.group(1)) for m in re.finditer(r"\[(\d+)\][^\n]*" + pattern, text)]


def main() -> None:
    httpx.post(f"{SB}/__admin/reset", json={"chaos": ["flaky_submit", "over_threshold"]}).raise_for_status()
    rd = Path("runs/_smoke")
    shutil.rmtree(rd, ignore_errors=True)
    ws = rd / "workspace"
    ws.mkdir(parents=True)
    b = Browser(ws, rd / "screens", [SB])
    human = ScriptedChannel(approvals=[{"match": "high_value", "decision": "approve"}])
    ctx = ToolContext(b, Policy(Path("config/policies.yaml")), human, CompanyMemory(Path("memory")),
                      RunState("smoke"), Tracer(rd, echo=False), ws)
    t = lambda name, **a: run_tool(ctx, name, a)  # noqa: E731
    try:
        assert "1,00,000" in t("search_memory", query="approval limit bill")
        assert t("type_text", element_id=1, text="x").startswith("ERROR")
        o = t("open_url", url=f"{SB}/mail")
        o = t("type_text", element_id=ids(o, '"Search mail"')[0], text="Globex", submit=True)
        o = t("click", element_id=ids(o, "Invoice GX-1042")[0])
        o = t("click", element_id=ids(o, '"GX-1042.pdf"')[0])
        assert "downloads/GX-1042.pdf" in o, o[:500]
        assert "1,85,000.00" in t("read_file", path="downloads/GX-1042.pdf")
        assert "not_allowed" in t("open_url", url="https://evil.example.com")

        o = t("open_url", url=f"{SB}/erp/bills/new")
        t("select_option", element_id=ids(o, '"Vendor"')[0], option="Globex Ltd")
        for label, val in [("Invoice number", "GX-1042"), ("Invoice date", "01-10-2026"), ("Amount", "185000.00"), ("Due date", "15-10-2026")]:
            o = t("type_text", element_id=ids(o, '"' + label)[0], text=val)
        o = t("click", element_id=ids(o, '"Save bill"')[0])
        print("SUBMIT 1 ->", o.splitlines()[0])
        assert "outcome: http_error" in o
        assert human.log and human.log[0]["approved"], "approval should have been requested"

        o = t("go_back")
        save = ids(o, '"Save bill"')[0]
        o = t("click", element_id=save)
        print("RETRY w/o reason ->", o.splitlines()[0])
        assert "possible_duplicate" in o
        o = t("click", element_id=save, retry_reason="500 error")
        print("RETRY w/o checking ->", o.splitlines()[0])
        assert "verify_before_retry" in o
        o = t("open_url", url=f"{SB}/erp/bills?vendor=Globex")
        assert "GX-1042" not in o
        o = t("go_back")
        o = t("click", element_id=ids(o, '"Save bill"')[0], retry_reason="bills list shows no GX-1042 after the 500")
        print("RETRY after check ->", o.splitlines()[0])
        assert "outcome: ok" in o
        assert len(human.log) == 1, "approval must be reused for the identical action"
        bills = [x for x in httpx.get(f"{SB}/__admin/state").json()["bills"] if x["invoice_no"] == "GX-1042"]
        assert len(bills) == 1 and bills[0]["amount"] == 185000.0, bills
        print("ledger:", [(e.button, e.outcome) for e in ctx.state.ledger])
        print("SMOKE OK")
    finally:
        b.close()


if __name__ == "__main__":
    main()
