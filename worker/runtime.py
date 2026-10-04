"""The worker runtime: Goal -> Understand -> Plan -> Execute -> Observe -> Adapt -> Verify -> Complete.

One ReAct-style loop with explicit plan state. The LLM decides every next action; the runtime
owns safety (policy gate, idempotency, budgets), state, the audit trail, and verification.
"""
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from pathlib import Path

import yaml

from .browser import Browser
from .context import compact_history
from .guards import LoopGuard
from .human import HumanChannel
from .llm import LLM, LLMError, usage_cost
from .memory import CompanyMemory
from .policy import Policy
from .prompts import WORKER_SYSTEM
from .report import write_report
from .role import ROLES_DIR, Role, list_roles, load_role, route_task
from .state import RunState
from .tools import ALL_TOOLS, Finish, ToolContext, run_tool
from .trace import Tracer
from .verifier import _add_usage, verify

ROOT = Path(__file__).resolve().parent.parent
FINISH_STATUSES = ("success", "partial", "blocked", "failed")
DENIAL_ISSUE = "A human denied an approval during this task; it cannot be reported as success."


def _has_denial(state: RunState) -> bool:
    """True if a human said no to any approval in this run (binding on the final status)."""
    fn = getattr(state, "has_denial", None)
    if callable(fn):
        return bool(fn())
    # fallback for RunState versions without has_denial(): scan recorded escalations
    return any(e.get("type") == "approval_denied" or (e.get("type") == "approval" and e.get("approved") is False)
               for e in getattr(state, "escalations", []) if isinstance(e, dict))


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load((path or ROOT / "config" / "agent.yaml").read_text(encoding="utf-8"))


class Worker:
    def __init__(self, human: HumanChannel, cfg: dict | None = None, run_id: str | None = None,
                 headless: bool = True, echo: bool = True, runs_dir: Path | None = None, role: str | None = None):
        self.cfg = cfg or load_config()
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_dir = (runs_dir or ROOT / "runs") / self.run_id
        self.workspace = self.run_dir / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.tracer = Tracer(self.run_dir, echo=echo)
        self.llm = LLM(self.cfg["llm"])
        self.human = human
        self.headless = headless
        # which AI employee does the work: explicit role id, or routed from the task text in run()
        self.role: Role | None = load_role(role, ROLES_DIR) if role else None

    def run(self, goal: str) -> dict:
        rt = self.cfg["runtime"]
        state = RunState(goal=goal)
        role = self.role = self.role or route_task(goal, list_roles(ROLES_DIR))
        prices = getattr(self.llm, "prices", None)
        tools = [t.spec() for t in ALL_TOOLS]
        system = WORKER_SYSTEM.format(company=self.cfg["company"], today=self.cfg["today"],
                                      role_block=role.prompt_block(self.cfg["company"]))
        messages: list[dict] = [{"role": "user", "content": f"Task: {goal}"}]
        self.tracer.event("run_start", run_id=self.run_id, goal=goal, model=self.llm.model,
                          role=role.id, role_name=role.name, role_title=role.title)
        started = time.time()
        verifications: list[dict] = []
        final: dict | None = None
        browser = None

        try:
            browser = Browser(self.workspace, self.run_dir / "screens", rt["allowed_origins"], headless=self.headless)
            ctx = ToolContext(browser=browser, policy=Policy(ROOT / "config" / "policies.yaml", autonomy=role.autonomy),
                              human=self.human, memory=CompanyMemory(ROOT / "memory"), state=state, tracer=self.tracer,
                              workspace=self.workspace, allowed_apps=role.systems, knowledge_files=role.knowledge,
                              role_id=role.id, role_title=role.title, approver=role.approver, run_id=self.run_id)
            guard = LoopGuard()
            while final is None:
                state.step += 1
                if state.step > rt["max_steps"]:
                    final = self._stop(state, "blocked", f"Step budget ({rt['max_steps']}) exhausted before completion.")
                    break
                if usage_cost(state.usage, prices) > rt["max_cost_usd"]:
                    final = self._stop(state, "blocked", f"Cost budget (${rt['max_cost_usd']}) exhausted before completion.")
                    break
                # Anthropic path: send the append-only history (prompt caching + thinking integrity).
                # Other adapters: send a compacted copy; the stored history is never edited.
                request = messages
                if getattr(self.llm, "converse", False):
                    stats: dict = {}
                    request = compact_history(messages, stats=stats)
                    state.usage["compacted_chars"] = state.usage.get("compacted_chars", 0) + stats.get("saved_chars", 0)
                try:
                    resp = self.llm.complete(system, request, tools)
                except LLMError as e:
                    self.tracer.event("error", where="llm", message=str(e))
                    final = self._stop(state, "failed", f"LLM unavailable: {e}")
                    break
                _add_usage(state.usage, resp)
                messages.append({"role": "assistant", "content": resp.content})
                for b in resp.content:
                    if b.type == "text" and b.text.strip():
                        self.tracer.event("thought", text=b.text.strip(), step=state.step)
                    elif b.type == "thinking" and getattr(b, "thinking", ""):
                        self.tracer.event("thought", text=b.thinking.strip(), step=state.step, reasoning=True)

                if resp.stop_reason == "refusal":
                    final = self._stop(state, "failed", "The model declined to continue this task (refusal).")
                    break
                uses = [b for b in resp.content if b.type == "tool_use"]
                if not uses:
                    messages.append({"role": "user", "content": "Continue the task by calling a tool. Call finish() when the task is complete or blocked."})
                    continue

                # run non-terminal tools first, finish() last
                uses.sort(key=lambda u: u.name == "finish")
                results, notes = [], []
                for u in uses:
                    args = dict(u.input)
                    url = browser.last.url if browser.last else ""
                    self.tracer.event("tool_call", tool=u.name, input=args, step=state.step)
                    if u.name == "finish":
                        out, final = self._handle_finish(ctx, state, args, verifications)
                    else:
                        warning = guard.check(u.name, args, url)
                        out = run_tool(ctx, u.name, args)
                        if warning:
                            notes.append(warning)
                            self.tracer.event("guard", message=warning)
                    self.tracer.event("tool_result", tool=u.name, summary=out[:300], is_error=out.startswith("ERROR"))
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": out, "is_error": out.startswith("ERROR")})
                if final is not None:
                    break
                if guard.tripped:
                    final = self._stop(state, "blocked", "Stuck: the same action kept repeating without progress (circuit breaker). "
                                       "A human should review the trace; last plan:\n" + state.plan_text())
                    break
                stall = guard.progress(state.step, state.plan, state.facts)
                if stall:
                    notes.append(stall)
                    self.tracer.event("guard", message=stall)
                if state.step == 3 and not state.plan:
                    notes.append("REMINDER: you have no plan yet. Call update_plan with steps and success_criteria.")
                status = f"[Run state] step {state.step}/{rt['max_steps']}. Plan:\n{state.plan_text()}\nFacts:\n{state.facts_text()}"
                content = results + [{"type": "text", "text": "\n".join(notes + [status])}]
                messages.append({"role": "user", "content": content})
        except KeyboardInterrupt:
            final = self._stop(state, "failed", "Interrupted by the operator.")
        except Exception as e:  # never lose the audit trail: any crash still ends with a report
            reason = f"Runtime error: {type(e).__name__}: {e}"
            self.tracer.event("error", where="runtime", message=reason, traceback=traceback.format_exc()[-2000:])
            final = {"status": "failed", "summary": reason, "claims": [], "verified": None, "deterministic_issues": []}
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception as e:  # a failed close must not hide the run's outcome
                    self.tracer.event("error", where="browser.close", message=f"{type(e).__name__}: {e}")

        if final is None:  # defensive: the loop only exits with a final result
            final = self._stop(state, "failed", "Run ended without a final result.")
        final.update(run_id=self.run_id, goal=goal, role=role.id, role_name=role.name, duration_s=round(time.time() - started, 1),
                     usage=state.usage, cost_usd=round(usage_cost(state.usage, prices), 4), steps=state.step,
                     verifications=verifications, facts=state.facts, escalations=state.escalations, flags=state.flags,
                     ledger=[e.__dict__ for e in state.ledger], plan=state.plan, success_criteria=state.success_criteria)
        self.tracer.event("finish", status=final["status"], verified=final.get("verified"), cost_usd=final["cost_usd"])
        try:
            final["report"] = str(write_report(self.run_dir, final, self.tracer.events))
        except Exception as e:  # result.json is still written below
            final["report"] = None
            self.tracer.event("error", where="report", message=f"{type(e).__name__}: {e}",
                              traceback=traceback.format_exc()[-2000:])
        (self.run_dir / "result.json").write_text(json.dumps(final, indent=2, default=str), encoding="utf-8")
        return final

    # ------------------------------------------------------------------
    def _handle_finish(self, ctx: ToolContext, state: RunState, args: dict, verifications: list) -> tuple[str, dict | None]:
        payload = None
        out = ""
        try:
            out = run_tool(ctx, "finish", args)
        except Finish as f:
            payload = f.payload
        if payload is None:  # bad arguments etc.: let the model call finish correctly
            text = str(out) if str(out).startswith("ERROR") else f"ERROR [bad_arguments]: finish() did not complete: {out}"
            return text + "\nCall finish again with status, summary and claims.", None
        status = payload.get("status")
        if status not in FINISH_STATUSES:
            return (f"ERROR [bad_arguments]: finish status must be one of {', '.join(FINISH_STATUSES)}, got {status!r}. "
                    "Call finish again."), None
        claims = payload.get("claims")
        payload["claims"] = claims if isinstance(claims, list) else []
        problems = self._deterministic_checks(state, payload)
        if status in ("blocked", "failed"):
            return "Run ended.", {**payload, "verified": None, "deterministic_issues": problems}
        if DENIAL_ISSUE in problems:  # a human "no" is binding: never verify or report this as success
            self.tracer.event("guard", message=DENIAL_ISSUE, claimed_status=status)
            return "Run ended: a human denied an approval.", {**payload, "status": "blocked", "claimed_status": status,
                                                              "verified": None, "deterministic_issues": problems}

        rt = self.cfg["runtime"]
        result = verify(self.llm, ctx, self.cfg, state.goal, state.success_criteria, state.facts_text(), payload["claims"])
        verifications.append(result)
        if result["passed"] and not problems:
            return "Verified.", {**payload, "verified": True, "deterministic_issues": []}
        failing = [v for v in result["verdicts"] if v["verdict"] != "pass"]
        if len(verifications) <= rt["max_verify_rounds"]:
            msg = ("INDEPENDENT VERIFICATION FAILED. Do not finish yet. Issues:\n" +
                   "\n".join(f"- {v['criterion']}: {v['verdict']} ({v['evidence']})" for v in failing) +
                   ("\n" + "\n".join(f"- {p}" for p in problems) if problems else "") +
                   (f"\nSide effects noticed: {result.get('side_effects')}" if result.get("side_effects") else "") +
                   "\nInvestigate the live systems, fix what is wrong (without creating duplicates), then call finish again.")
            self.tracer.event("verifier", status="sent_back", issues=failing, problems=problems)
            return msg, None
        return "Verification failed after repair rounds.", {**payload, "status": "unverified", "claimed_status": status,
                                                              "verified": False, "deterministic_issues": problems}

    @staticmethod
    def _deterministic_checks(state: RunState, payload: dict) -> list[str]:
        problems = []
        claims = payload.get("claims") or []
        if payload["status"] in ("success", "partial"):
            if _has_denial(state):
                problems.append(DENIAL_ISSUE)
            if not state.success_criteria:
                problems.append("No success criteria were defined, so success cannot be checked.")
            if len(claims) < len(state.success_criteria):
                problems.append("Not every success criterion has a claim with evidence.")
        # an identical action that "succeeded" twice is suspicious unless the repeat was a deliberate,
        # evidence-backed retry (e.g. the first save was silently dropped); the verifier checks for real duplicates
        ok = [e for e in state.ledger if e.outcome == "ok"]
        dupes = {e.fingerprint for e in ok if not e.retry_reason and sum(x.fingerprint == e.fingerprint for x in ok) > 1}
        unexplained = {f for f in dupes if not any(x.fingerprint == f and x.retry_reason for x in ok)}
        if unexplained:
            problems.append(f"The same consequential action succeeded more than once without a justified retry: {sorted(unexplained)}")
        return problems

    def _stop(self, state: RunState, status: str, reason: str) -> dict:
        self.tracer.event("error" if status == "failed" else "guard", message=reason)
        return {"status": status, "summary": reason, "claims": [], "verified": None, "deterministic_issues": []}
