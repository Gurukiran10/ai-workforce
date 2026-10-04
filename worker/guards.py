"""Runtime guards that keep the loop honest: repetition, lack of progress, budgets."""
from __future__ import annotations

import json
from collections import Counter


class LoopGuard:
    def __init__(self, warn_at: int = 3, escalate_at: int = 5, hard_stop_at: int = 8, stall_steps: int = 10):
        self.counts: Counter = Counter()
        self.warn_at, self.escalate_at, self.hard_stop_at, self.stall_steps = warn_at, escalate_at, hard_stop_at, stall_steps
        self.tripped = False
        self.last_progress_step = 0
        self._last_signature = ("", 0)

    def check(self, tool: str, args: dict, url: str) -> str | None:
        key = (tool, json.dumps(args, sort_keys=True), url)
        self.counts[key] += 1
        n = self.counts[key]
        if n >= self.hard_stop_at:  # circuit breaker: the model is ignoring warnings
            self.tripped = True
            return f"CIRCUIT BREAKER: {tool} repeated {n} times on {url} despite warnings. Stopping the run."
        if n >= self.escalate_at:
            return (f"GUARD: you have made this exact call {n} times ({tool} on {url}). It is not working. "
                    "Change approach now, or ask_human for help, or finish(status='blocked') with what you learned.")
        if n >= self.warn_at:
            return (f"GUARD: repeated action detected ({tool} x{n} on the same page). State why the previous attempts "
                    "failed and try a different approach.")
        return None

    def progress(self, step: int, plan: list[dict], facts: dict) -> str | None:
        signature = (json.dumps(plan, sort_keys=True), len(facts))
        if signature != self._last_signature:
            self._last_signature = signature
            self.last_progress_step = step
            return None
        if step - self.last_progress_step >= self.stall_steps:
            self.last_progress_step = step
            return ("GUARD: no plan progress or new facts for several steps. Re-read your plan, update step statuses, "
                    "and decide whether to change approach or escalate.")
        return None
