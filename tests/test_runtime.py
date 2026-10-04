"""Runtime loop tests with a scripted fake LLM: no browser, no network, no model cost."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import worker.runtime as runtime  # noqa: E402
from worker.context import MARKER, compact_history  # noqa: E402
from worker.human import ScriptedChannel  # noqa: E402
from worker.llm_converse import Block, Response, Usage  # noqa: E402

CRITERIA = ["The record exists", "No duplicate was created"]
CLAIMS = [{"criterion": c, "evidence": "seen on the list page"} for c in CRITERIA]


def call(name: str, i: int = 0, **inp) -> Response:
    return Response([Block(type="tool_use", id=f"t{name}{i}", name=name, input=inp)], "tool_use", Usage(100, 10))


PLAN = dict(steps=[{"id": "1", "description": "do it", "status": "done"}], success_criteria=CRITERIA)


class FakeLLM:
    converse = True
    model = "fake"
    prices = {"input": 1.0, "output": 1.0, "cache_read": 0.0, "cache_write": 0.0}

    def __init__(self, script: list[Response]):
        self.script = list(script)
        self.requests: list[list[dict]] = []

    def complete(self, system, messages, tools):
        self.requests.append(messages)
        if not self.script:  # keep the loop going harmlessly until a budget stops it
            return call("list_files", len(self.requests))
        return self.script.pop(0)


class DummyBrowser:
    def __init__(self, *a, **kw):
        self.last = None
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def make_worker(tmp_path, monkeypatch):
    verify_calls: list[dict] = []

    def fake_verify(llm, ctx, cfg, goal, criteria, facts, claims):
        verify_calls.append({"criteria": criteria, "claims": claims})
        return {"passed": True, "verdicts": [{"criterion": c, "verdict": "pass", "evidence": "ok"} for c in criteria],
                "side_effects": "", "steps": 1}

    monkeypatch.setattr(runtime, "Browser", DummyBrowser)
    monkeypatch.setattr(runtime, "verify", fake_verify)

    def build(script, max_steps=8, human=None):
        llm = FakeLLM(script)
        monkeypatch.setattr(runtime, "LLM", lambda cfg: llm)
        cfg = runtime.load_config()
        cfg["runtime"] = {**cfg["runtime"], "max_steps": max_steps}
        w = runtime.Worker(human or ScriptedChannel(), cfg=cfg, run_id="t", echo=False, runs_dir=tmp_path)
        w.verify_calls = verify_calls
        return w, llm

    return build


def _artifacts_exist(w) -> dict:
    assert (w.run_dir / "report.html").exists()
    return json.loads((w.run_dir / "result.json").read_text(encoding="utf-8"))


def _tool_results(messages) -> list[dict]:
    return [b for m in messages if m["role"] == "user" and isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_result"]


def test_malformed_finish_is_returned_to_model_then_valid_finish_succeeds(make_worker):
    w, llm = make_worker([call("update_plan", **PLAN),
                          call("finish", 1, status="success"),  # missing summary -> TypeError branch in run_tool
                          call("finish", 2, status="success", summary="done", claims=CLAIMS)])
    r = w.run("do the thing")
    assert r["status"] == "success" and r["verified"] is True
    errors = [b for b in _tool_results(llm.requests[-1]) if b["tool_use_id"] == "tfinish1"]
    assert errors and errors[0]["is_error"] and "summary" in errors[0]["content"]
    assert _artifacts_exist(w)["status"] == "success"


def test_invalid_finish_status_is_rejected(make_worker):
    w, llm = make_worker([call("update_plan", **PLAN),
                          call("finish", 1, status="done", summary="x"),
                          call("finish", 2, status="success", summary="done", claims=CLAIMS)])
    assert w.run("t")["status"] == "success"
    bad = [b for b in _tool_results(llm.requests[-1]) if b["tool_use_id"] == "tfinish1"][0]
    assert bad["is_error"] and "status must be one of" in bad["content"]


def test_exception_inside_loop_fails_run_but_writes_report(make_worker, monkeypatch):
    def boom(ctx, name, args):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(runtime, "run_tool", boom)
    w, _ = make_worker([call("list_files")])
    r = w.run("t")
    assert r["status"] == "failed" and r["summary"] == "Runtime error: RuntimeError: kaboom"
    saved = _artifacts_exist(w)
    assert saved["status"] == "failed"
    err = [e for e in w.tracer.events if e["kind"] == "error" and e.get("where") == "runtime"]
    assert err and "kaboom" in err[0]["traceback"]


def test_browser_close_failure_does_not_hide_outcome(make_worker, monkeypatch):
    class BadClose(DummyBrowser):
        def close(self):
            raise OSError("already gone")
    monkeypatch.setattr(runtime, "Browser", BadClose)
    w, _ = make_worker([call("finish", status="blocked", summary="need a human")])
    assert w.run("t")["status"] == "blocked"
    assert _artifacts_exist(w)["status"] == "blocked"


def test_step_budget_exhaustion_blocks(make_worker):
    w, llm = make_worker([], max_steps=3)  # fake LLM never finishes
    r = w.run("t")
    assert r["status"] == "blocked" and "Step budget" in r["summary"]
    assert len(llm.requests) == 3
    _artifacts_exist(w)


def test_approval_denial_is_binding(make_worker):
    w, _ = make_worker([call("update_plan", **PLAN),
                        call("request_approval", action="pay", details="x", reason="y"),  # scripted channel denies
                        call("finish", status="success", summary="done anyway", claims=CLAIMS)])
    r = w.run("t")
    assert r["status"] == "blocked" and r["claimed_status"] == "success"
    assert runtime.DENIAL_ISSUE in r["deterministic_issues"]
    assert w.verify_calls == []  # the verifier is not consulted
    _artifacts_exist(w)


def test_has_denial_hook_is_used(make_worker, monkeypatch):
    monkeypatch.setattr(runtime.RunState, "has_denial", lambda self: True, raising=False)
    w, _ = make_worker([call("update_plan", **PLAN), call("finish", status="partial", summary="s", claims=CLAIMS)])
    r = w.run("t")
    assert r["status"] == "blocked" and r["claimed_status"] == "partial"


def test_missing_claims_go_to_verifier_then_sent_back(make_worker):
    w, llm = make_worker([call("update_plan", **PLAN),
                          call("finish", 1, status="success", summary="done"),  # no claims for 2 criteria
                          call("finish", 2, status="success", summary="done", claims=CLAIMS)])
    r = w.run("t")
    assert len(w.verify_calls) == 2 and w.verify_calls[0]["claims"] == []
    sent_back = [b for b in _tool_results(llm.requests[-1]) if b["tool_use_id"] == "tfinish1"][0]
    assert "Not every success criterion has a claim" in sent_back["content"]
    assert r["status"] == "success" and r["verified"] is True


def test_compaction_applied_for_converse_adapter(make_worker):
    big = "".join(f"line {i} " + "y" * 60 + "\n" for i in range(100))
    w, llm = make_worker([call("write_file", path="a.txt", content=big)] +
                         [call("read_file", i, path="a.txt") for i in range(1, 6)], max_steps=7)
    r = w.run("t")
    results = _tool_results(llm.requests[-1])
    reads = [b["content"] for b in results if b["tool_use_id"].startswith("tread_file")]
    assert len(reads) == 5
    assert all(MARKER in c for c in reads[:2])  # older observations compacted in the request...
    assert all(MARKER not in c and len(c) > len(big) for c in reads[-3:])  # ...the last 3 kept in full
    assert r["usage"]["compacted_chars"] > 0
    # the stored transcript is never edited: an earlier request still saw the full observation
    assert any(MARKER not in b["content"] and len(b["content"]) > len(big)
               for b in _tool_results(llm.requests[2]) if b["tool_use_id"] == "tread_file1")


# ------------------------------------------------------------------ compact_history (pure)
def _turn(i: int, size: int = 1000) -> list[dict]:
    body = f"Observation {i}\n" + ("x" * 80 + "\n") * (size // 81)
    return [{"role": "assistant", "content": [Block(type="tool_use", id=f"u{i}", name="read_page")]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"u{i}", "content": body, "is_error": False},
                                         {"type": "text", "text": "[Run state] " + "p" * 500}]}]


def test_compact_history_keeps_recent_and_truncates_old():
    msgs = [{"role": "user", "content": "Task: t"}] + [m for i in range(6) for m in _turn(i)]
    snapshot = json.dumps(msgs, default=repr)
    stats: dict = {}
    out = compact_history(msgs, keep_last=3, max_old_chars=300, stats=stats)
    assert json.dumps(msgs, default=repr) == snapshot  # input untouched
    assert out is not msgs and len(out) == len(msgs)
    results = [b["content"] for m in out if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b["type"] == "tool_result"]
    old, recent = results[:3], results[3:]
    assert all(r.endswith(MARKER) and r.startswith("Observation") and len(r) <= 300 + len(MARKER) for r in old)
    assert all(MARKER not in r and len(r) > 900 for r in recent)
    assert stats["saved_chars"] > 3 * 600
    assert out[0] is msgs[0] and out[-1] is msgs[-1]  # unchanged messages shared, not copied


def test_compact_history_leaves_short_history_alone():
    msgs = [{"role": "user", "content": "Task: t"}] + _turn(0) + _turn(1)
    out = compact_history(msgs)
    assert all(a is b for a, b in zip(out, msgs))


def test_role_is_recorded_in_result_and_trace(make_worker, monkeypatch):
    w, llm = make_worker([call("finish", status="blocked", summary="not my job")])
    w.role = runtime.load_role("kabir")
    r = w.run("Enter the vendor bill")  # explicit role wins over routing
    assert (r["role"], r["role_name"]) == ("kabir", "Kabir")
    start = next(e for e in w.tracer.events if e["kind"] == "run_start")
    assert (start["role"], start["role_name"], start["role_title"]) == ("kabir", "Kabir", "Recruiting Coordinator")
    w2, _ = make_worker([call("finish", status="blocked", summary="x")])
    assert w2.run("Pay the vendor bill")["role"] == "diya"  # routed by the task text
