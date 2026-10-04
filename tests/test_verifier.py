"""Verifier isolation tests: network-level read-only browser, separate workspace, result shape.

Browser tests need the sandbox at http://localhost:8000 (python -m sandbox) and are skipped otherwise.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker import llm as llm_module  # noqa: E402
from worker import verifier  # noqa: E402

BASE = "http://localhost:8000"


def _state() -> dict | None:
    try:
        with urllib.request.urlopen(BASE + "/__admin/state", timeout=2) as r:
            return json.loads(r.read())
    except Exception:
        return None


@pytest.fixture
def clone(tmp_path):
    if _state() is None:
        pytest.skip("sandbox not reachable at " + BASE)
    from worker.browser import Browser
    run_dir = tmp_path / "run"
    b = Browser(run_dir / "workspace", run_dir / "screens", [BASE], headless=True)
    c = b.new_isolated_page()
    try:
        yield b, c, run_dir
    finally:
        c.close_isolated()
        b.close()


def test_clone_blocks_writes_at_network_level(clone):
    _, c, _ = clone
    before = _state()
    c.goto(BASE + "/erp/bills/new")
    res = c.page.evaluate("fetch('/erp/bills',{method:'POST',body:new URLSearchParams({vendor:'x'})})"
                          ".then(r=>r.status).catch(e=>'blocked')")
    assert res == "blocked"
    assert c.blocked_writes and c.blocked_writes[0].startswith("POST ")
    after = _state()
    assert after["bills"] == before["bills"] and after["counters"] == before["counters"]


def test_clone_reads_and_downloads_into_its_own_workspace(clone):
    b, c, run_dir = clone
    st = _state()
    email = next(e for e in st["emails"] if e["attachments"])
    obs = c.goto(f"{BASE}/mail/{email['id']}")
    assert obs.url.startswith(BASE) and not c.blocked_writes  # plain GET navigation works
    obs = c.goto(f"{BASE}/mail/{email['id']}/attachments/{email['attachments'][0]}")
    assert obs.downloads, "GET download should still work through the read-only route"
    assert c.workspace == run_dir / "verifier_workspace"
    assert (c.workspace / obs.downloads[0]).exists()
    assert not any((run_dir / "workspace" / "downloads").iterdir()), "must not write into the worker's workspace"
    c.close_isolated()
    assert b.goto(BASE + "/mail").url.startswith(BASE), "closing the clone must not close the worker's browser"


def test_result_shape_and_sop_criteria_cap():
    fake_browser = SimpleNamespace(blocked_writes=["POST /x"])
    inp = {"verdicts": [{"criterion": "A is done", "verdict": "pass", "evidence": "seen"}] +
                       [{"criterion": f"sop {i}", "verdict": "pass", "evidence": "e", "source": "sop"} for i in range(5)],
           "side_effects": "none found"}
    out = verifier._result(inp, ["A is done", "B is done"], 3, "m", fake_browser)
    assert set(out) >= {"passed", "verdicts", "side_effects", "steps", "model", "blocked_writes"}
    assert sum(v["source"] == "sop" for v in out["verdicts"]) == verifier.MAX_SOP_CRITERIA
    missing = [v for v in out["verdicts"] if v["criterion"] == "B is done"]
    assert missing and missing[0]["verdict"] == "unknown"  # dropped worker criterion is not silently passed
    assert out["passed"] is False and out["blocked_writes"] == ["POST /x"]
    inp["verdicts"].append({"criterion": "B is done", "verdict": "pass", "evidence": "seen"})
    assert verifier._result(inp, ["A is done", "B is done"], 3, "m", fake_browser)["passed"] is True  # blocked writes don't fail the worker


def test_verifier_llm_uses_independent_model_and_falls_back(monkeypatch):
    built = []

    class FakeLLM:
        def __init__(self, cfg):
            built.append(cfg)
            llm_module.PRICES = {"input": 99}  # mimic LLM() mutating the global price table
            self.model = cfg["converse_model"]

    monkeypatch.setattr(verifier, "LLM", FakeLLM)
    prices = llm_module.PRICES
    cfg = {"llm": {"provider": "p", "converse_model": "worker-model", "verifier_provider": "vp", "verifier_model": "judge"}}
    v = verifier.verifier_llm(cfg, fallback="FALLBACK")
    assert v.model == "judge" and built[-1]["provider"] == "vp"
    assert llm_module.PRICES is prices  # worker's cost accounting untouched

    def boom(cfg):
        raise ValueError("no access")
    monkeypatch.setattr(verifier, "LLM", boom)
    assert verifier.verifier_llm(cfg, fallback="FALLBACK") == "FALLBACK"


def test_first_message_labels_worker_facts_as_hints():
    msg = verifier.build_first_message("do X", ["X done"], "k: v", [{"claim": "did X"}])
    assert "UNVERIFIED HINTS" in msg and "ORIGINAL source" in msg and 'source "sop"' in msg
