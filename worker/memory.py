"""Company Memory: SOPs, policies and notes as markdown, retrieved with BM25.

Deliberately simple and inspectable. Everything task-specific lives here, not in code.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from rank_bm25 import BM25Okapi

TOKEN = re.compile(r"[a-z0-9]+")
LEARNED_RULES = "learned_rules.md"  # human-approved rules from the learning loop; always searchable
LEARNED_RULES_HEADING = "# Learned rules (human-approved)"


def ensure_learned_rules(directory: Path) -> Path:
    path = directory / LEARNED_RULES
    if not path.exists():
        path.write_text(LEARNED_RULES_HEADING + "\n", encoding="utf-8")
    return path


def _tok(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


class CompanyMemory:
    def __init__(self, directory: Path):
        self.dir = directory
        self.reindex()

    def reindex(self) -> None:
        self.chunks: list[dict] = []
        ensure_learned_rules(self.dir)
        # top-level *.md only: unapproved proposals in _proposed/ are never company memory
        for f in sorted(self.dir.glob("*.md")):
            title, heading, buf = f.stem, "", []
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("#"):
                    if buf:
                        self.chunks.append({"file": f.name, "heading": heading or title, "text": "\n".join(buf).strip()})
                    heading, buf = line.lstrip("# ").strip(), [line]
                else:
                    buf.append(line)
            if buf:
                self.chunks.append({"file": f.name, "heading": heading or title, "text": "\n".join(buf).strip()})
        self.chunks = [c for c in self.chunks if c["text"]]
        self._bm25 = BM25Okapi([_tok(c["file"] + " " + c["heading"] + " " + c["text"]) for c in self.chunks])

    def search(self, query: str, k: int = 4, files: list[str] | None = None) -> list[dict]:
        """BM25 search. `files` scopes it to an employee's knowledge (learned rules are always included)."""
        scores = self._bm25.get_scores(_tok(query))
        ranked = sorted(zip(scores, self.chunks), key=lambda x: -x[0])
        if files is not None:
            allowed = set(files) | {LEARNED_RULES}
            ranked = [(s, c) for s, c in ranked if c["file"] in allowed]
        return [c for s, c in ranked[:k] if s > 0]

    def learn(self, fact: str, source: str) -> None:
        """Persist a durable company fact learned during work (e.g. a human's clarification)."""
        path = self.dir / "learned_facts.md"
        if not path.exists():
            path.write_text("# Learned facts (written by the AI worker, review periodically)\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"- {fact} (source: {source}; {datetime.now():%d-%m-%Y %H:%M})\n")
        self.reindex()
