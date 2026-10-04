"""Check that the configured LLM credentials work with one tiny request. Never prints secrets.

    python scripts/check_llm.py
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from worker.llm import LLM, LLMError  # noqa: E402
from worker.runtime import load_config  # noqa: E402

found = [k for k in ("ANTHROPIC_AWS_API_KEY", "ANTHROPIC_AWS_WORKSPACE_ID", "AWS_BEARER_TOKEN_BEDROCK", "AWS_ACCESS_KEY_ID", "AWS_REGION") if os.getenv(k)]
print("credentials present:", found or "none")
try:
    llm = LLM(load_config()["llm"])
    print("provider:", llm.provider, "| model:", llm.model)
    resp = llm.complete("You are a test.", [{"role": "user", "content": "Reply with exactly: OK"}], [])
    text = next((b.text for b in resp.content if b.type == "text"), "")
    print("SUCCESS - model replied:", text.strip(), "| tokens in/out:", resp.usage.input_tokens, resp.usage.output_tokens)
except (LLMError, Exception) as e:  # show the reason, not the key
    print("FAILED:", type(e).__name__, str(e)[:600])
    sys.exit(1)
