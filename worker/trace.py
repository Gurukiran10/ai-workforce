"""Append-only audit trail: every event of a run goes to runs/<id>/trace.jsonl (flushed per event)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from rich.console import Console

console = Console()

STYLE = {"plan": "cyan", "tool_call": "white", "tool_result": "dim", "policy": "magenta", "approval": "red",
         "human": "yellow", "guard": "bold yellow", "verifier": "bold blue", "finish": "bold green", "error": "bold red",
         "thought": "italic grey62"}


class Tracer:
    def __init__(self, run_dir: Path, echo: bool = True):
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "trace.jsonl"
        self.echo = echo
        self.events: list[dict] = []

    def event(self, kind: str, **data) -> dict:
        ev = {"ts": round(time.time(), 3), "kind": kind, **data}
        self.events.append(ev)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, default=str) + "\n")
        if self.echo:
            self._print(ev)
        return ev

    def _print(self, ev: dict) -> None:
        kind = ev["kind"]
        if kind == "tool_result":
            msg = str(ev.get("summary", ""))[:160]
        elif kind == "tool_call":
            msg = f"{ev['tool']} {json.dumps(ev.get('input', {}))[:200]}"
        elif kind == "thought":
            msg = str(ev.get("text", ""))[:300]
        else:
            msg = json.dumps({k: v for k, v in ev.items() if k not in ("ts", "kind")}, default=str)[:300]
        console.print(f"[{STYLE.get(kind, 'white')}]{kind:>11} │ {msg}[/]", highlight=False, markup=True, soft_wrap=True)
