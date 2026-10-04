"""Explicit run state: the agent's working memory, kept outside the LLM transcript."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LedgerEntry:
    fingerprint: str
    url: str
    button: str
    fields: dict
    outcome: str  # ok | http_error | unknown
    step: int
    retry_reason: str = ""  # set when the agent deliberately repeated the action after checking


@dataclass
class RunState:
    goal: str
    plan: list[dict] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    facts: dict[str, dict] = field(default_factory=dict)  # key -> {value, source}
    ledger: list[LedgerEntry] = field(default_factory=list)
    approvals: dict[str, bool] = field(default_factory=dict)  # fingerprint -> approved
    escalations: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # suspicious things noticed (e.g. injection)
    step: int = 0
    # fingerprint -> form URL of an attempt that has not been checked yet (agent must view another page first)
    unverified_attempts: dict[str, str] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)  # texts the agent observed: files, pages, human answers
    denied_actions: list[str] = field(default_factory=list)  # actions a human refused; binding for the run
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "llm_calls": 0})

    def add_evidence(self, text: str, max_chars: int = 20000, max_entries: int = 60) -> None:
        if text:
            self.evidence.append(text[:max_chars])
            del self.evidence[:-max_entries]

    def has_denial(self) -> bool:
        """True if a human denied any approval: the run must not report success."""
        return bool(self.denied_actions)

    def plan_text(self) -> str:
        if not self.plan:
            return "(no plan yet)"
        icons = {"todo": "[ ]", "doing": "[~]", "done": "[x]", "blocked": "[!]"}
        lines = [f"{icons.get(s.get('status', 'todo'), '[ ]')} {s.get('id', i + 1)}. {s.get('description', '')}" for i, s in enumerate(self.plan)]
        if self.success_criteria:
            lines.append("Success criteria: " + " | ".join(self.success_criteria))
        return "\n".join(lines)

    def facts_text(self) -> str:
        if not self.facts:
            return "(none)"
        return "\n".join(f"- {k}: {v['value']} (source: {v['source']})" for k, v in self.facts.items())
