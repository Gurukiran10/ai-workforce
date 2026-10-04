"""Human-approved learning and the trust ladder.

Learning loop: when a human answer settles something the SOPs don't cover, the worker calls propose_rule.
The proposal waits in memory/_proposed/<id>.json (never searched). Only when a human accepts it is the rule
appended to memory/learned_rules.md, which every employee's memory search includes from then on.

Trust ladder: an employee's track record (runs/*/result.json) decides whether it should stay supervised.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .memory import ensure_learned_rules

PROPOSED_DIR = "_proposed"
MIN_VERIFIED_FOR_STANDARD = 3
RECENT_WINDOW = 10


# ------------------------------------------------------------------ proposals
def _proposal_path(memory_dir: Path, proposal_id: str) -> Path:
    return memory_dir / PROPOSED_DIR / f"{proposal_id}.json"


def write_proposal(memory_dir: Path, role: str, rule: str, applies_to: str, reason: str, run_id: str) -> dict:
    proposal = {"id": uuid.uuid4().hex[:8], "role": role, "rule": rule.strip(), "applies_to": applies_to.strip(),
                "reason": reason.strip(), "run_id": run_id, "created": int(time.time()), "status": "pending"}
    path = _proposal_path(memory_dir, proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return proposal


def list_proposals(memory_dir: Path, status: str | None = None) -> list[dict]:
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((memory_dir / PROPOSED_DIR).glob("*.json"))]
    return [p for p in out if status is None or p.get("status") == status]


def learned_line(proposal: dict) -> str:
    return f"- [{proposal['role']}] {proposal['rule']} (learned from run {proposal['run_id']}, approved by a human)"


def _decide(memory_dir: Path, proposal_id: str, status: str) -> dict:
    path = _proposal_path(memory_dir, proposal_id)
    if not path.exists():
        raise FileNotFoundError(f"No proposal {proposal_id}")
    proposal = json.loads(path.read_text(encoding="utf-8"))
    if proposal.get("status") != "pending":  # already decided: idempotent, the first decision stands
        return proposal
    if status == "accepted":
        rules = ensure_learned_rules(memory_dir)
        line = learned_line(proposal)
        if line not in rules.read_text(encoding="utf-8").splitlines():
            with rules.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    proposal["status"] = status
    path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    return proposal


def accept_proposal(memory_dir: Path, proposal_id: str) -> dict:
    """Human said yes: append the rule to learned_rules.md and mark the proposal accepted."""
    return _decide(memory_dir, proposal_id, "accepted")


def reject_proposal(memory_dir: Path, proposal_id: str) -> dict:
    """Human said no: mark the proposal rejected; company memory is unchanged."""
    return _decide(memory_dir, proposal_id, "rejected")


# ------------------------------------------------------------------ trust ladder
def trust_record(runs_dir: Path, role_id: str) -> dict:
    """Track record of one AI employee, from the result.json of every run it did (oldest first)."""
    results = []
    for f in runs_dir.glob("*/result.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if r.get("role") == role_id:
            results.append((f.stat().st_mtime, r))
    results = [r for _, r in sorted(results, key=lambda x: x[0])]
    statuses = [r.get("status") for r in results]
    return {
        "role": role_id,
        "tasks": len(results),
        "verified": sum(1 for r in results if r.get("verified") is True),
        "unverified": statuses.count("unverified"),
        "escalated": statuses.count("blocked"),
        "failed": statuses.count("failed"),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in results), 4),
        "last_run": results[-1].get("run_id") if results else None,
        "recent_statuses": statuses[-RECENT_WINDOW:],
    }


def recommended_autonomy(record: dict) -> tuple[str, str]:
    """Earn autonomy with evidence: supervised until enough verified work and no recent unverified claims."""
    if record["verified"] < MIN_VERIFIED_FOR_STANDARD:
        return "supervised", f"Only {record['verified']} verified task(s); needs {MIN_VERIFIED_FOR_STANDARD} before standard autonomy."
    if "unverified" in record.get("recent_statuses", []):
        return "supervised", f"A claim failed independent verification in the last {RECENT_WINDOW} runs."
    return "standard", f"{record['verified']} verified task(s) and no unverified claims in the last {RECENT_WINDOW} runs."
