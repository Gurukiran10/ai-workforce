"""Adapter for Bedrock's Converse API (Amazon Nova and other non-Anthropic Bedrock models).

The runtime speaks the Anthropic Messages format. This adapter translates requests to Converse
and translates responses back into objects with the same shape (content blocks with
.type/.text/.id/.name/.input, .stop_reason, .usage), so the rest of the system is unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    thinking: str = ""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Response:
    content: list[Block]
    stop_reason: str
    usage: Usage


STOP = {"end_turn": "end_turn", "tool_use": "tool_use", "max_tokens": "max_tokens",
        "stop_sequence": "end_turn", "guardrail_intervened": "refusal", "content_filtered": "refusal"}


def _as_dict(block: Any) -> dict:
    if isinstance(block, dict):
        return block
    if isinstance(block, Block):
        return {"type": block.type, "text": block.text, "id": block.id, "name": block.name, "input": block.input, "thinking": block.thinking}
    return block.model_dump()  # anthropic SDK block


def _to_converse_content(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    out = []
    for raw in content:
        b = _as_dict(raw)
        t = b.get("type")
        if t == "text" and b.get("text", "").strip():
            out.append({"text": b["text"]})
        elif t == "tool_use":
            out.append({"toolUse": {"toolUseId": b["id"], "name": b["name"], "input": b.get("input") or {}}})
        elif t == "tool_result":
            text = b["content"] if isinstance(b["content"], str) else "\n".join(c.get("text", "") for c in b["content"])
            out.append({"toolResult": {"toolUseId": b["tool_use_id"], "content": [{"text": text or "(empty)"}],
                                       "status": "error" if b.get("is_error") else "success"}})
        # thinking blocks are model-private; not replayed to a different API
    return out or [{"text": "(continue)"}]


class ConverseLLMClient:
    def __init__(self, region: str, model: str, max_tokens: int, temperature: float = 0.0):
        self.model, self.max_tokens, self.temperature = model, max_tokens, temperature
        # boto3 picks up AWS_BEARER_TOKEN_BEDROCK (Bedrock API key) or normal AWS credentials automatically
        self.client = boto3.client("bedrock-runtime", region_name=region,
                                   config=Config(retries={"max_attempts": 6, "mode": "adaptive"}, read_timeout=300))
        self.use_cache_points = True
        self.use_temperature = True

    def create(self, system: str, messages: list[dict], tools: list[dict]) -> Response:
        conv_msgs = [{"role": m["role"], "content": _to_converse_content(m["content"])} for m in messages]
        sys_blocks: list[dict] = [{"text": system}]
        tool_specs = [{"toolSpec": {"name": t["name"], "description": t["description"],
                                    "inputSchema": {"json": {k: v for k, v in t["input_schema"].items()}}}} for t in tools]
        if self.use_cache_points:
            sys_blocks.append({"cachePoint": {"type": "default"}})
        inference = {"maxTokens": self.max_tokens}
        if self.use_temperature:
            inference["temperature"] = self.temperature
        kwargs = dict(modelId=self.model, messages=conv_msgs, system=sys_blocks, inferenceConfig=inference)
        if tool_specs:
            kwargs["toolConfig"] = {"tools": tool_specs}
        try:
            r = self.client.converse(**kwargs)
        except ClientError as e:
            msg = str(e).lower()
            # models differ in what they accept: drop the optional feature and retry once
            if self.use_cache_points and ("cach" in msg or "unsupported model" in msg):
                self.use_cache_points = False
                return self.create(system, messages, tools)
            if self.use_temperature and "temperature" in msg:
                self.use_temperature = False
                return self.create(system, messages, tools)
            raise
        blocks: list[Block] = []
        for c in r["output"]["message"]["content"]:
            if "text" in c:
                blocks.append(Block(type="text", text=c["text"]))
            elif "toolUse" in c:
                tu = c["toolUse"]
                blocks.append(Block(type="tool_use", id=tu["toolUseId"], name=tu["name"], input=tu.get("input") or {}))
            elif "reasoningContent" in c:
                txt = c["reasoningContent"].get("reasoningText", {}).get("text", "")
                blocks.append(Block(type="thinking", thinking=txt))
        u = r.get("usage", {})
        usage = Usage(u.get("inputTokens", 0), u.get("outputTokens", 0), u.get("cacheReadInputTokens", 0), u.get("cacheWriteInputTokens", 0))
        return Response(blocks, STOP.get(r.get("stopReason", "end_turn"), "end_turn"), usage)


ConverseErrors = (ClientError, BotoCoreError)


def region_default(cfg: dict) -> str:
    return os.getenv("AWS_REGION") or cfg.get("region", "us-east-1")
