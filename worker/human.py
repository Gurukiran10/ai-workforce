"""Human-in-the-loop channels. The runtime only talks to the HumanChannel interface."""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

console = Console()


class HumanChannel:
    def ask(self, question: str, options: list[str] | None = None) -> str:
        raise NotImplementedError

    def approve(self, request: dict) -> tuple[bool, str]:
        """Returns (approved, note)."""
        raise NotImplementedError


class CLIChannel(HumanChannel):
    def ask(self, question, options=None):
        console.print(Panel(question + (f"\nOptions: {', '.join(options)}" if options else ""), title="Agent asks", style="yellow"))
        try:
            return console.input("[bold yellow]Your answer> [/]").strip()
        except EOFError:
            return "(no human is available to answer right now; do not guess, report what is missing)"

    def approve(self, request):
        body = "\n".join(f"{k}: {v}" for k, v in request.items())
        console.print(Panel(body, title="Approval required", style="red"))
        try:
            ans = console.input("[bold red]Approve? (y/n, optional note after a space)> [/]").strip()
        except EOFError:
            return False, "no human available to approve"
        return ans.lower().startswith("y"), ans[1:].strip()


class WebChannel(HumanChannel):
    """File-based IPC with the live viewer: agent writes pending/<id>.json, viewer writes responses/<id>.json."""

    def __init__(self, run_dir: Path, timeout_s: int = 900):
        self.pending, self.responses = run_dir / "pending", run_dir / "responses"
        self.pending.mkdir(parents=True, exist_ok=True)
        self.responses.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s

    def _wait(self, kind: str, payload: dict) -> dict:
        rid = uuid.uuid4().hex[:8]
        (self.pending / f"{rid}.json").write_text(json.dumps({"id": rid, "kind": kind, **payload}), encoding="utf-8")
        console.print(f"[yellow]Waiting for human ({kind}) in the viewer… request {rid}[/]")
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            resp = self.responses / f"{rid}.json"
            if resp.exists():
                (self.pending / f"{rid}.json").unlink(missing_ok=True)
                return json.loads(resp.read_text(encoding="utf-8"))
            time.sleep(0.5)
        (self.pending / f"{rid}.json").unlink(missing_ok=True)
        return {"timeout": True}

    def ask(self, question, options=None):
        r = self._wait("question", {"question": question, "options": options or []})
        return r.get("answer", "") if not r.get("timeout") else "(no answer: the human did not respond in time)"

    def approve(self, request):
        r = self._wait("approval", {"request": request})
        if r.get("timeout"):
            return False, "timed out waiting for approval"
        return bool(r.get("approved")), r.get("note", "")


class ScriptedChannel(HumanChannel):
    """Deterministic answers for the eval harness: first rule whose regex matches wins."""

    def __init__(self, answers: list[dict] | None = None, approvals: list[dict] | None = None):
        self.answers, self.approvals = answers or [], approvals or []
        self.log: list[dict] = []

    def ask(self, question, options=None):
        for rule in self.answers:
            if re.search(rule["match"], question, re.I | re.S):
                self.log.append({"kind": "question", "q": question, "a": rule["answer"]})
                return rule["answer"]
        self.log.append({"kind": "question", "q": question, "a": None})
        return "I don't know. Do not guess; stop and report what is missing."

    def approve(self, request):
        text = json.dumps(request)
        for rule in self.approvals:
            if re.search(rule["match"], text, re.I | re.S):
                ok = rule["decision"] == "approve"
                self.log.append({"kind": "approval", "request": request, "approved": ok})
                return ok, rule.get("note", "")
        self.log.append({"kind": "approval", "request": request, "approved": False})
        return False, "no scripted approval matched (default deny)"
