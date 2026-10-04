"""Adapter for OpenAI-compatible chat APIs (Google Gemini via AI Studio, Groq, and others).

Like llm_converse.py, it translates the runtime's Anthropic-style messages to the provider's
format and returns objects with the same shape, so the agent loop stays unchanged.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import openai

from .llm_converse import Block, Response, Usage, _as_dict

ENDPOINTS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}
FINISH = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


def _clean_schema(schema: Any) -> Any:
    """Some providers reject JSON-Schema keywords like additionalProperties; drop them recursively."""
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_clean_schema(v) for v in schema]
    return schema


def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        blocks = [_as_dict(b) for b in content]
        if m["role"] == "assistant":
            text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                     for b in blocks if b.get("type") == "tool_use"]
            msg: dict = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            for b in blocks:  # tool results must directly follow the assistant tool calls
                if b.get("type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                "content": b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])})
            text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            if text:
                out.append({"role": "user", "content": text})
    return out


class OpenAICompatClient:
    def __init__(self, provider: str, api_key: str, model: str, max_tokens: int, temperature: float = 0.0,
                 requests_per_minute: float | None = None):
        base_url, _ = ENDPOINTS[provider]
        self.client = openai.OpenAI(base_url=base_url, api_key=api_key, max_retries=2, timeout=180)
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        self.min_interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._last_call = 0.0

    def _call(self, kwargs: dict):
        """Client-side rate limiting for free tiers: pace requests and wait out 429s instead of failing the run."""
        for attempt in range(8):
            wait = self._last_call + self.min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            try:
                return self.client.chat.completions.create(**kwargs)
            except openai.RateLimitError as e:
                m = re.search(r"retry in ([\d.]+)s", str(e)) or re.search(r"try again in ([\d.]+)s", str(e))
                delay = float(m.group(1)) + 1 if m else min(60, 5 * 2 ** attempt)
                if "per day" in str(e).lower() or "PerDay" in str(e):
                    raise  # daily quota: waiting won't help
                time.sleep(delay)
        return self.client.chat.completions.create(**kwargs)

    def create(self, system: str, messages: list[dict], tools: list[dict]) -> Response:
        kwargs = dict(model=self.model, messages=_to_openai_messages(system, messages),
                      max_tokens=self.max_tokens, temperature=self.temperature)
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                                 "parameters": _clean_schema(t["input_schema"])}} for t in tools]
        r = self._call(kwargs)
        choice = r.choices[0]
        blocks: list[Block] = []
        if choice.message.content:
            blocks.append(Block(type="text", text=choice.message.content))
        for tc in choice.message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unparseable_arguments": tc.function.arguments}
            blocks.append(Block(type="tool_use", id=tc.id, name=tc.function.name, input=args))
        u = r.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0 if u else 0
        usage = Usage((u.prompt_tokens - cached) if u else 0, u.completion_tokens if u else 0, cached, 0)
        stop = "tool_use" if choice.message.tool_calls else FINISH.get(choice.finish_reason, "end_turn")
        return Response(blocks, stop, usage)


Errors = (openai.APIError,)
