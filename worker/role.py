"""AI employees: each one is a role defined in roles/<id>.yaml, not in code.

A role says who the employee is, what they are responsible for, which company systems they may use
(enforced by the tools as a data boundary), which memory files they read, how much autonomy they have,
and who approves their risky actions. The worker code stays generic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES_DIR = Path(__file__).resolve().parent.parent / "roles"


@dataclass
class Role:
    id: str
    name: str
    title: str
    reports_to: str = ""
    avatar_hue: int = 220
    autonomy: str = "standard"  # supervised | standard
    match: str = ""  # regex over the task text used to route work to this employee
    responsibilities: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)  # first URL path segment of each allowed app
    knowledge: list[str] = field(default_factory=list)  # memory/*.md files this employee searches
    business_rules: list[str] = field(default_factory=list)  # policy rule ids that govern this role (informational)
    escalation: dict = field(default_factory=dict)  # {approver, questions_to}
    human_checkpoints: list[str] = field(default_factory=list)

    @property
    def approver(self) -> str:
        return str(self.escalation.get("approver", ""))

    def prompt_block(self, company: str) -> str:
        """The part of the system prompt that makes the worker this specific employee."""
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items) or "- (none)"

        return (
            f"You are {self.name}, {self.title} at {company}. You report to {self.reports_to}.\n"
            f"Your responsibilities:\n{bullets(self.responsibilities)}\n"
            f"You may only use these company systems: {', '.join(self.systems) or '(none)'}.\n"
            f"Human checkpoints (a human must approve or decide):\n{bullets(self.human_checkpoints)}\n"
            "If a task is outside your responsibilities or systems, do not attempt it: finish(status='blocked') "
            "explaining which colleague/role should handle it."
        )


def load_role(role_id: str, roles_dir: Path = ROLES_DIR) -> Role:
    path = roles_dir / f"{role_id}.yaml"
    if not path.exists():
        known = ", ".join(r.id for r in list_roles(roles_dir))
        raise ValueError(f"Unknown role '{role_id}'. Known roles: {known or '(none)'}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Role(**{k: v for k, v in data.items() if k in Role.__dataclass_fields__})


def list_roles(roles_dir: Path = ROLES_DIR) -> list[Role]:
    return [load_role(p.stem, roles_dir) for p in sorted(roles_dir.glob("*.yaml"))]


def route_task(goal: str, roles: list[Role]) -> Role:
    """First role whose `match` regex hits the task text (case-insensitive); otherwise the first role."""
    if not roles:
        raise ValueError("No roles defined: add roles/<id>.yaml")
    for role in roles:
        if role.match and re.search(role.match, goal, re.I):
            return role
    return roles[0]
