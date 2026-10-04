"""LLM adapter: one `LLM.complete(system, messages, tools)` interface over several providers.

The provider is chosen in config/agent.yaml (`llm.provider`, overridable with LLM_PROVIDER); the
configured default is Amazon Bedrock's Converse API with Moonshot Kimi K3 (`converse_model`).
Non-Anthropic adapters (bedrock_converse, gemini, groq, openrouter; `LLM.converse == True`) translate
to/from the Anthropic Messages shape, so the runtime sees the same response objects either way.
Claude endpoints (bedrock, bedrock_mantle, claude_platform_aws, anthropic) receive the history
append-only (never edited) so prompt caching and thinking-block integrity both hold; the runtime
only compacts old observations for the non-Anthropic adapters.
"""
from __future__ import annotations

import copy
import os

import anthropic

# USD per 1M tokens (list prices; Bedrock global endpoints match first-party pricing)
PRICE_TABLE = {
    "sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "kimi": {"input": 0.60, "output": 2.50, "cache_read": 0.15, "cache_write": 0.60},  # approx.
    "glm": {"input": 0.60, "output": 2.20, "cache_read": 0.15, "cache_write": 0.60},  # approx.
    "deepseek": {"input": 0.60, "output": 1.70, "cache_read": 0.15, "cache_write": 0.60},  # approx.
    "nova-pro": {"input": 0.80, "output": 3.20, "cache_read": 0.20, "cache_write": 0.80},
    "nova-2-lite": {"input": 0.30, "output": 2.50, "cache_read": 0.075, "cache_write": 0.30},  # approx.
    "nova-lite": {"input": 0.06, "output": 0.24, "cache_read": 0.015, "cache_write": 0.06},
    "gemini": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},  # free tier
    "gpt-oss": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},  # Groq free tier
    ":free": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
    "llama": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "cache_write": 0.0},
}
DEFAULT_PRICES = PRICE_TABLE["sonnet-4-6"]
# Backward-compatible module default used by usage_cost() when no price table is passed.
# Never mutated by LLM(); each instance carries its own `prices`.
PRICES = DEFAULT_PRICES


class LLMError(Exception):
    pass


class LLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        provider = os.getenv("LLM_PROVIDER") or cfg.get("provider", "auto")
        region = os.getenv("AWS_REGION") or cfg.get("region", "us-east-1")
        token = os.getenv("AWS_BEARER_TOKEN_BEDROCK") or os.getenv("BEDROCK_API_KEY")
        if provider == "auto":
            provider = "claude_platform_aws" if os.getenv("ANTHROPIC_AWS_API_KEY") else "bedrock"
        self.provider = provider

        self.converse = provider in ("bedrock_converse", "gemini", "groq", "openrouter")  # non-Anthropic adapters
        if provider == "bedrock_converse":  # Amazon Nova etc. via the Converse API (no AWS Marketplace subscription needed)
            from .llm_converse import ConverseErrors, ConverseLLMClient
            self.model = cfg.get("converse_model", "us.amazon.nova-pro-v1:0")
            self.client = ConverseLLMClient(region, self.model, min(int(cfg.get("max_tokens", 16000)), 10000))
            self.errors = ConverseErrors
        elif provider in ("gemini", "groq", "openrouter"):  # free tiers via OpenAI-compatible endpoints
            from .llm_openai import ENDPOINTS, Errors, OpenAICompatClient
            key = os.getenv(ENDPOINTS[provider][1])
            if not key:
                raise ValueError(f"Set {ENDPOINTS[provider][1]} in .env to use {provider}")
            self.model = cfg.get(f"{provider}_model")
            self.client = OpenAICompatClient(provider, key, self.model, min(int(cfg.get("max_tokens", 16000)), 8000),
                                             requests_per_minute=cfg.get(f"{provider}_rpm"))
            self.errors = Errors
        elif provider == "bedrock":  # bedrock-runtime InvokeModel endpoint
            self.client = anthropic.AnthropicBedrock(api_key=token, aws_region=region, max_retries=4) if token \
                else anthropic.AnthropicBedrock(aws_region=region, max_retries=4)
            self.model = cfg.get("bedrock_model", "global.anthropic.claude-sonnet-4-6")
        elif provider == "bedrock_mantle":  # Messages-API Bedrock endpoint (newest models, if the account has access)
            base_url = f"https://bedrock-mantle.{region}.api.aws/anthropic"
            self.client = anthropic.AnthropicBedrockMantle(api_key=token, aws_region=region, base_url=base_url, max_retries=4) if token \
                else anthropic.AnthropicBedrockMantle(aws_region=region, base_url=base_url, max_retries=4)
            self.model = cfg.get("mantle_model", "anthropic.claude-sonnet-5-5")
        elif provider == "claude_platform_aws":  # Anthropic-operated, AWS Marketplace billing
            self.client = anthropic.AnthropicAWS(api_key=os.getenv("ANTHROPIC_AWS_API_KEY"), aws_region=region,
                                                 workspace_id=os.getenv("ANTHROPIC_AWS_WORKSPACE_ID"), max_retries=4)
            self.model = cfg.get("anthropic_model", "claude-sonnet-5-5")
        elif provider == "anthropic":
            # explicit base_url so a stray ANTHROPIC_BASE_URL in the shell can't redirect traffic
            self.client = anthropic.Anthropic(base_url="https://api.anthropic.com", max_retries=4)
            self.model = cfg.get("anthropic_model", "claude-sonnet-5-5")
        else:
            raise ValueError(f"unknown provider {provider}")

        self.prices = prices_for(self.model)
        self.effort = cfg.get("effort", "medium")
        self.max_tokens = int(cfg.get("max_tokens", 16000))
        # optional request features; dropped automatically if an endpoint rejects them
        self.optional = {"thinking": {"type": "adaptive", "display": "summarized"},
                         "output_config": {"effort": self.effort}}

    def complete(self, system: str, messages: list[dict], tools: list[dict]):
        if self.converse:
            try:
                return self.client.create(system, messages, tools)
            except self.errors as e:
                raise LLMError(f"{self.provider} error for {self.model}: {e}") from e
        return self._complete_anthropic(system, messages, tools)

    def _complete_anthropic(self, system: str, messages: list[dict], tools: list[dict]) -> anthropic.types.Message:
        # Cache breakpoints: tools + system (stable prefix) and the newest message (rolling).
        tools = copy.deepcopy(tools)
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}
        req_messages = list(messages)
        last = copy.deepcopy(req_messages[-1])
        if isinstance(last["content"], str):
            last["content"] = [{"type": "text", "text": last["content"]}]
        last["content"][-1]["cache_control"] = {"type": "ephemeral"}
        req_messages[-1] = last

        kwargs = dict(model=self.model, max_tokens=self.max_tokens, tools=tools, messages=req_messages,
                      system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}])
        while True:
            try:
                return self.client.messages.create(**kwargs, **self.optional)
            except anthropic.BadRequestError as e:
                msg = str(e).lower()
                dropped = next((k for k in self.optional if k.split("_")[0] in msg or (k == "output_config" and "effort" in msg)), None)
                if dropped is None:
                    raise LLMError(f"Bad request: {e}") from e
                self.optional.pop(dropped)  # endpoint doesn't support it: degrade gracefully, keep going
            except anthropic.AuthenticationError as e:
                raise LLMError("Authentication failed. Check AWS_BEARER_TOKEN_BEDROCK / AWS credentials and region.") from e
            except anthropic.PermissionDeniedError as e:
                raise LLMError(f"Permission denied for {self.model}: {e}") from e
            except anthropic.NotFoundError as e:
                raise LLMError(f"Model {self.model} not found in this region: {e}") from e
            except anthropic.APIConnectionError as e:
                raise LLMError(f"Could not reach the model endpoint: {e}") from e


def prices_for(model: str | None) -> dict:
    """USD-per-1M-token prices for a model id (first PRICE_TABLE key contained in it)."""
    return next((p for k, p in PRICE_TABLE.items() if k in (model or "")), DEFAULT_PRICES)


def usage_cost(usage: dict, prices: dict | None = None) -> float:
    """Cost in USD of a usage dict. Pass the worker's `llm.prices`; defaults to the module table."""
    prices = prices or PRICES
    return sum(usage.get(k, 0) * prices[k] for k in prices) / 1_000_000
