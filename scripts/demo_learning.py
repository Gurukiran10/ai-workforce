"""End-to-end check of the learning loop (costs ~2 agent runs):

    1. Diya gets an invoice with no due date -> asks a human -> human gives a general rule -> she proposes it.
    2. A human accepts the proposal (here: programmatically) -> it lands in memory/learned_rules.md.
    3. Same situation again -> she should apply the learned rule without asking.

    python scripts/demo_learning.py
"""
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from worker.human import ScriptedChannel  # noqa: E402
from worker.learning import accept_proposal, list_proposals  # noqa: E402
from worker.runtime import Worker  # noqa: E402

TASK = "Find the latest invoice from Globex, extract the amount and due date, enter it into our accounts system, and tell me once it is done."
ANSWER = "Globex invoices never print a due date. Our standing rule: for Globex, the due date is 15 days after the invoice date."
SB = "http://localhost:8000"
STAMP = datetime.now().strftime("%H%M%S")  # unique run ids per demo


def run(tag: str) -> dict:
    httpx.post(f"{SB}/__admin/reset", json={"chaos": ["missing_due_date"]}, timeout=10).raise_for_status()
    human = ScriptedChannel(answers=[{"match": ".*", "answer": ANSWER}])
    result = Worker(human=human, role="diya", run_id=f"learning-{STAMP}-{tag}", echo=False).run(TASK)
    bill = [b for b in httpx.get(f"{SB}/__admin/state").json()["bills"] if b["invoice_no"] == "GX-1042"]
    asked = sum(1 for x in human.log if x["kind"] == "question")
    print(f"[{tag}] status={result['status']} verified={result.get('verified')} questions_asked={asked} "
          f"steps={result['steps']} cost=${result['cost_usd']} bill={bill}")
    return {"asked": asked, "result": result}


if __name__ == "__main__":
    first = run("1-before-learning")
    pending = [p for p in list_proposals(ROOT / "memory", status="pending") if p.get("run_id") == f"learning-{STAMP}-1-before-learning"]
    print("proposals:", [p["rule"] for p in pending])
    if not pending:
        sys.exit("No rule was proposed in run 1; the learning loop did not trigger.")
    accept_proposal(ROOT / "memory", pending[0]["id"])
    print("accepted ->", (ROOT / "memory" / "learned_rules.md").read_text(encoding="utf-8").strip().splitlines()[-1])
    second = run("2-after-learning")
    print("RESULT:", "learned (no question in run 2)" if second["asked"] == 0 and first["asked"] > 0 else "did not learn")

