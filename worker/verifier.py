"""Independent verifier: different model, fresh context, its own browser session and workspace.

Independence, layer by layer (so the worker can't grade its own homework):
- Model: a different LLM (config `llm.verifier_provider` / `llm.verifier_model`), falling back to the worker's.
- Context: it sees the goal, criteria and the worker's facts/claims (labelled unverified hints) - never the
  worker's reasoning.
- Evidence: its own browser context and its own workspace (<run_dir>/verifier_workspace), so it must
  re-open and re-download source documents itself instead of reading the worker's copies.
- Read-only: enforced at the network layer - every non-GET/HEAD request from its browser is aborted and
  recorded in `blocked_writes` (on top of the tool-level read_only flag).
- Criteria: besides the worker's criteria it adds up to 3 of its own derived from the company SOP, and
  checks for regressions and unexpected extra records.
"""
from __future__ import annotations

import json

from . import llm as llm_module
from .human import ScriptedChannel
from .llm import LLM
from .prompts import VERIFIER_SYSTEM
from .tools import READ_ONLY_TOOLS, TOOLS, ToolContext, _obj, run_tool

MAX_SOP_CRITERIA = 3

VERDICT_TOOL = {
    "name": "report_verdict",
    "description": "Report your final verdict for every success criterion (the worker's and your own SOP-derived ones).",
    "input_schema": _obj({"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "criterion": {"type": "string"}, "verdict": {"type": "string", "enum": ["pass", "fail", "unknown"]},
        "evidence": {"type": "string"},
        "source": {"type": "string", "enum": ["worker", "sop"],
                   "description": "worker = a criterion you were given; sop = one you added from company SOPs"}},
        "required": ["criterion", "verdict", "evidence"], "additionalProperties": False}},
        "side_effects": {"type": "string", "description": "Regressions or unexpected extra/changed records, or 'none found'."}},
        ["verdicts"]),
}


def verifier_llm(cfg: dict, fallback: LLM) -> LLM:
    """An independent model for verification; falls back to the worker's model if it can't be built."""
    c = cfg.get("llm", {})
    if not (c.get("verifier_provider") or c.get("verifier_model")):
        return fallback
    saved_prices = llm_module.PRICES  # LLM() resets the global price table; keep the worker's for cost accounting
    try:
        return LLM({**c, "provider": c.get("verifier_provider", c.get("provider")),
                    "converse_model": c.get("verifier_model", c.get("converse_model"))})
    except Exception:
        return fallback
    finally:
        llm_module.PRICES = saved_prices


def audit_facts(events: list[dict]) -> str:
    """Human decisions recorded by the runtime itself (not by the worker), so the verifier may trust them."""
    lines = []
    for ev in events:
        if ev["kind"] == "approval" and ev.get("status") in ("approved", "denied"):
            lines.append(f"- approval {ev['status']}" + (f" (note: {ev['note']})" if ev.get("note") else ""))
        elif ev["kind"] == "approval" and ev.get("status") == "requested":
            req = ev.get("request") or {}
            lines.append(f"- approval requested: {req.get('action', '')} ({req.get('policy_rule') or req.get('why_needed', '')})")
        elif ev["kind"] == "human" and ev.get("type") == "answer":
            lines.append(f"- human answered a question: {ev.get('answer', '')}")
    return "\n".join(lines) or "(no human approvals or answers in this task)"


def build_first_message(goal: str, criteria: list[str], facts: str, claims: list[dict], audit: str = "") -> str:
    crit = criteria or ["(The worker defined no criteria. Derive the checkable end-state criteria from the goal yourself.)"]
    return (
        f"Goal given to the worker:\n{goal}\n\n"
        "Success criteria to check (source \"worker\"):\n" + "\n".join(f"- {c}" for c in crit) +
        "\n\nAUDIT TRAIL (recorded by the runtime, trustworthy) - use it for criteria about human approvals or answers:\n"
        f"{audit or '(none)'}\n"
        "Criteria about messages to the requester cannot be observed in company systems: mark them pass only if the "
        "goal needs nothing beyond the final report, otherwise unknown." +
        "\n\nUNVERIFIED HINTS from the worker - use them only to know where to look, never as evidence:\n"
        f"Facts the worker recorded:\n{facts or '(none)'}\n\nWorker's claims:\n{json.dumps(claims, indent=1)}\n\n"
        "Do this now:\n"
        f"1. search_memory for the SOP that governs this kind of task. Add up to {MAX_SOP_CRITERIA} criteria of your own "
        "that the SOP implies (e.g. no duplicate records, superseded documents not entered, values match the source "
        "document) and report them with source \"sop\".\n"
        "2. Find the ORIGINAL source document(s) in the source system and open/download them yourself "
        "(your workspace starts empty). Check every value against the source, not against the worker's facts.\n"
        "3. Check side effects: records touched earlier in the task were not changed back or regressed, and no "
        "unexpected extra records (duplicates, wrong targets) exist.\n"
        "4. Call report_verdict with a verdict for every criterion above plus your SOP criteria.")


def verify(llm: LLM, base_ctx: ToolContext, cfg: dict, goal: str, criteria: list[str], facts: str, claims: list[dict]) -> dict:
    tracer = base_ctx.tracer
    vllm = verifier_llm(cfg, llm)
    model = getattr(vllm, "model", None) or "unknown"
    workspace = base_ctx.workspace.parent / "verifier_workspace"
    browser = base_ctx.browser.new_isolated_page(workspace)
    ctx = ToolContext(browser=browser, policy=base_ctx.policy, human=ScriptedChannel(), memory=base_ctx.memory,
                      state=base_ctx.state, tracer=tracer, workspace=browser.workspace, read_only=True)
    tools = [TOOLS[n].spec() for n in READ_ONLY_TOOLS] + [VERDICT_TOOL]
    system = VERIFIER_SYSTEM.format(company=cfg["company"], today=cfg["today"])
    crit = criteria or ["(derived from the goal)"]
    messages = [{"role": "user", "content": build_first_message(goal, criteria, facts, claims, audit_facts(tracer.events))}]
    max_steps = cfg["runtime"]["verifier_max_steps"]
    tracer.event("verifier", status="started", criteria=crit, model=model)
    try:
        for step in range(max_steps):
            resp = vllm.complete(system, messages, tools)
            _add_usage(base_ctx.state.usage, resp)
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if b.type == "tool_use"]
            if not uses:
                messages.append({"role": "user", "content": "Use your tools, then call report_verdict."})
                continue
            results = []
            for u in uses:
                if u.name == "report_verdict":
                    out = _result(u.input, criteria, step + 1, model, browser)
                    tracer.event("verifier", status="done", **out)
                    return out
                tracer.event("tool_call", tool=f"verifier.{u.name}", input=u.input)
                text = run_tool(ctx, u.name, dict(u.input))
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": text, "is_error": text.startswith("ERROR")})
            if step == max_steps - 3:  # budget nearly spent: report what was checked instead of timing out empty-handed
                results.append({"type": "text", "text": "Only 2 steps left. Call report_verdict now with what you have "
                                "verified; use unknown for anything you could not check."})
            messages.append({"role": "user", "content": results})
    finally:
        browser.close_isolated()
    out = {"passed": False, "verdicts": [{"criterion": c, "verdict": "unknown", "evidence": "verifier ran out of steps", "source": "worker"}
                                         for c in crit],
           "side_effects": "", "steps": cfg["runtime"]["verifier_max_steps"], "model": model,
           "blocked_writes": list(browser.blocked_writes)}
    tracer.event("verifier", status="exhausted", **out)
    return out


def _result(inp: dict, criteria: list[str], steps: int, model: str, browser) -> dict:
    verdicts = []
    sop_count = 0
    for v in inp.get("verdicts", []):
        v = {"criterion": str(v.get("criterion", "")), "verdict": v.get("verdict", "unknown"),
             "evidence": str(v.get("evidence", "")), "source": v.get("source") or "worker"}
        if v["source"] == "sop":
            sop_count += 1
            if sop_count > MAX_SOP_CRITERIA:
                continue
        verdicts.append(v)
    # every worker criterion must be answered; a silently dropped one counts as unknown
    answered = " ".join(v["criterion"].lower() for v in verdicts if v["source"] == "worker")
    for c in criteria:
        if c.lower()[:40] not in answered:
            verdicts.append({"criterion": c, "verdict": "unknown", "evidence": "verifier gave no verdict for this criterion",
                             "source": "worker"})
    # blocked write attempts mean the verifier misbehaved, not the worker: report them, don't fail on them
    passed = bool(verdicts) and all(v["verdict"] == "pass" for v in verdicts)
    return {"passed": passed, "verdicts": verdicts, "side_effects": inp.get("side_effects", ""), "steps": steps,
            "model": model, "blocked_writes": list(browser.blocked_writes)}


def _add_usage(usage: dict, resp) -> None:
    u = resp.usage
    usage["input"] += u.input_tokens or 0
    usage["output"] += u.output_tokens or 0
    usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
    usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
    usage["llm_calls"] += 1
