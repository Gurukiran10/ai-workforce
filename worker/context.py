"""Context compaction for non-Anthropic adapters.

The stored transcript stays append-only (the Anthropic path relies on that for prompt caching and
thinking-block integrity). For adapters without those constraints the runtime sends a compacted
*copy*: observations older than the last few turns are cut to their first lines, because the
current page, plan and facts are always restated in the newest turns.
"""
from __future__ import annotations

MARKER = " …[older observation compacted]"


def _truncate(text: str, max_chars: int) -> str:
    """First line(s) of text up to max_chars, plus the marker. Short text is returned unchanged."""
    if len(text) <= max_chars + len(MARKER):
        return text
    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        if used + len(line) > max_chars:
            if not kept:  # a single very long first line: hard cut
                kept.append(line[:max_chars])
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept).rstrip() + MARKER


def _is_tool_turn(msg: dict) -> bool:
    c = msg.get("content")
    return msg.get("role") == "user" and isinstance(c, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def compact_history(messages: list[dict], keep_last: int = 3, max_old_chars: int = 300,
                    stats: dict | None = None) -> list[dict]:
    """Return a NEW message list where tool results (and the run-state text that rides with them)
    in all but the last `keep_last` tool-result user turns are truncated to `max_old_chars`.

    The input list and its messages are never mutated; untouched messages are shared by reference.
    If `stats` is given, stats["saved_chars"] is set to the approximate number of characters removed.
    """
    tool_turns = [i for i, m in enumerate(messages) if _is_tool_turn(m)]
    old = set(tool_turns[:-keep_last] if keep_last > 0 else tool_turns)
    saved = 0
    out: list[dict] = []
    for i, m in enumerate(messages):
        if i not in old:
            out.append(m)
            continue
        blocks = []
        for b in m["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("content"), str):
                short = _truncate(b["content"], max_old_chars)
                saved += len(b["content"]) - len(short)
                blocks.append({**b, "content": short})
            elif isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                short = _truncate(b["text"], max_old_chars)
                saved += len(b["text"]) - len(short)
                blocks.append({**b, "text": short})
            else:
                blocks.append(b)
        out.append({**m, "content": blocks})
    if stats is not None:
        stats["saved_chars"] = saved
    return out
