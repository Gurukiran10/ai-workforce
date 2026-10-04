"""Deterministic permission layer: decides allow / require_approval / deny for consequential actions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml


@dataclass
class Decision:
    action: str  # allow | require_approval | deny
    rule_id: str | None = None
    reason: str = ""
    approver: str = ""


# A number token ("1,85,000.00", "48250") optionally followed by an Indian unit word.
_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)(?:\s*(lakhs?|lacs?|crores?|cr)\b)?", re.I)
_UNITS = {"l": 1e5, "c": 1e7}  # lakh/lac -> 1e5, crore/cr -> 1e7


def numbers_in(text: str) -> list[float]:
    """All amounts in a text: "Rs. 1,85,000" -> 185000, "1.85 lakh" -> 185000, "2 crore" -> 20000000."""
    out = []
    for digits, unit in _NUM_RE.findall(str(text)):
        try:
            n = float(digits.replace(",", ""))
        except ValueError:
            continue
        out.append(round(n * _UNITS[unit[0].lower()], 2) if unit else n)
    return out


def _number(value: str) -> float | None:
    nums = numbers_in(value)
    return nums[0] if nums else None


def app_of(url: str) -> str:
    """The first path segment identifies the company system (mail, erp, ats...)."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    return parts[0] if parts else ""


class Policy:
    def __init__(self, path: Path, autonomy: str | None = None):
        """`autonomy` overrides the file's level for one run (each AI employee has its own)."""
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.autonomy = autonomy or cfg.get("autonomy", "standard")
        self.consequential_re = re.compile(cfg["consequential_pattern"], re.I)
        self.rules = cfg.get("rules", [])
        self.default = cfg.get("default", "allow")

    def is_consequential(self, element: dict | None) -> bool:
        """A submit-like click is consequential if its label says so, or if it submits a POST form
        (POST changes server data; search/filter forms use GET). Links are always navigation."""
        if not element:
            return False
        clickable_submit = element["tag"] == "button" or (element["tag"] == "input" and element.get("type") in ("submit", "button"))
        if not clickable_submit:
            return False
        posts_form = bool(element.get("submit")) and element.get("form_method", "get") == "post"
        return posts_form or bool(self.consequential_re.search(element.get("label", "")))

    def evaluate(self, url: str, button: str, fields: dict[str, str]) -> Decision:
        app = app_of(url)
        matched: list[tuple[Decision, float]] = []  # (decision, threshold) so the strictest tier wins
        for rule in self.rules:
            w = rule.get("when", {})
            if "app" in w and not re.fullmatch(w["app"], app, re.I):
                continue
            if "button" in w and not re.search(w["button"], button, re.I):
                continue
            if "field" in w:
                hits = {k: v for k, v in fields.items() if re.search(w["field"], k, re.I)}
                if not hits:
                    continue
                if "gt" in w and not any((n := _number(v)) is not None and n > w["gt"] for v in hits.values()):
                    continue
            d = Decision(rule["action"], rule["id"], rule.get("description", ""), rule.get("approver", ""))
            matched.append((d, w.get("gt", 0)))
        for severity in ("deny", "require_approval"):
            hits = [(d, gt) for d, gt in matched if d.action == severity]
            if hits:
                return max(hits, key=lambda h: h[1])[0]  # max() keeps the first on ties
        if self.autonomy == "supervised":
            return Decision("require_approval", "supervised_mode", "Supervised autonomy: every consequential action needs approval")
        return Decision(self.default)
