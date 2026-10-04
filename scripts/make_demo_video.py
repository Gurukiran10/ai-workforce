"""Produce the demo video automatically: a REAL live run recorded from the operator console, with captions,
text-to-speech narration (Windows voices), title/result slides, and the waiting parts sped up.

Requires the sandbox running (python -m sandbox) and LLM credentials in .env (one live task, ~$0.15).
    python scripts/make_demo_video.py            -> docs/video/acme-workforce-demo.mp4
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "video"
WORK = OUT / "_work"
BASE = "http://localhost:8000"
W, H = 1600, 900
FAST = 5.0  # speed-up for waiting segments
VOICE = "Microsoft Zira Desktop"

N = {  # narration, written to be spoken: short sentences, connecting phrases
    "title": "Hi, this is Acme Workforce. It's a set of AI employees that do real work inside company systems. "
             "They check in with a human when a decision is needed, and they prove the result before they say it's done.",
    "roster": "Here's the workforce. Each AI employee is defined by a simple role file: what they're responsible for, "
              "which systems they're allowed to use, the business rules they follow, and when they have to ask a human. "
              "Diya handles accounts payable, and Kabir handles recruiting. Both run on exactly the same code.",
    "profile": "Let's open Diya's profile. Her permissions and approval limits are enforced in code, not in a prompt. "
               "Bills over one lakh need the Finance Manager, over five lakh need the CFO, and she can never delete a record. "
               "And this trust ladder shows how much autonomy she has earned from her verified track record.",
    "assign": "Now the exact task from the brief, with two real-world problems injected: the server will fail on the "
              "first save, and the invoice is above the approval limit.",
    "work": "While she works, you can see her reading the procedure, searching the mailbox, opening the PDF, and filling "
            "in the form, all in a real browser.",
    "approval": "Diya read the procedure, found the invoice in the mailbox, read the PDF, and filled in the bill. "
                "But before she can save it, the permission layer stops her. One lakh eighty five thousand rupees needs the "
                "Finance Manager's approval. So I approve it, and add a note for the audit trail.",
    "error": "Then the save fails with a server error. She doesn't just retry. She first checks the bills list to make "
             "sure nothing was saved, so a duplicate bill can never be created.",
    "verify": "Now, the important part. An independent verifier, a different AI model working in a separate, read-only "
              "browser, downloads the original invoice again and checks every value in the ERP.",
    "receipt": "And it's verified. Every success criterion has evidence, the approval is in the audit trail, and the "
               "whole task cost about ten rupees.",
    "recruit": "The same runtime also does a completely different job. Here, Kabir screened six applicants against the "
               "job description, and booked the strongest candidate for Thursday.",
    "ats": "Two were shortlisted, three were rejected with reasons, and one was marked Needs Info, because his salary "
           "expectation was missing. It doesn't guess.",
    "learn": "It also learns. When an invoice had no due date, Diya asked once, and then proposed a company rule. "
             "After a human approved it, the next run needed no questions at all, with twenty six percent fewer steps, "
             "and forty three percent lower cost.",
    "results": "Everything is measured against the sandbox's real database: twenty two scenarios, including five "
               "held-out tasks that I wrote before running anything. Across twenty seven live runs, there were zero false "
               "successes. Every miss was a safe one.",
    "arch": "Under the hood, it's one reasoning loop with an explicit plan and generic browser tools. The permission layer "
            "and the provenance checks live outside the model, and the verifier simply cannot change data.",
    "close": "Next, I'd add Raj-style WhatsApp checks with candidates, always-on employees that watch the inbox, and "
             "reusable skills built from verified runs. Thanks for watching.",
}

CAPTION_JS = r"""(t) => {
  let c = document.getElementById('__cap');
  if (!c) { c = document.createElement('div'); c.id = '__cap';
    c.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:78%;z-index:99999;' +
      'background:rgba(10,12,20,.86);color:#fff;font:500 21px/1.45 Inter,Segoe UI,sans-serif;padding:12px 22px;' +
      'border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.45);border:1px solid rgba(255,255,255,.12);text-align:center;transition:opacity .3s';
    document.body.appendChild(c); }
  c.textContent = t; c.style.opacity = t ? 1 : 0;
}"""
CURSOR_INIT = r"""window.addEventListener('DOMContentLoaded', () => {
  const d = document.createElement('div'); d.id = '__cur';
  d.style.cssText = 'position:fixed;width:22px;height:22px;border-radius:50%;background:rgba(124,116,255,.35);' +
    'border:2px solid #fff;z-index:100000;pointer-events:none;transform:translate(-50%,-50%);left:-50px;top:-50px;transition:left .25s,top .25s';
  document.body.appendChild(d);
  document.addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; });
  document.addEventListener('mousedown', () => { d.style.background = 'rgba(124,116,255,.9)'; setTimeout(() => d.style.background = 'rgba(124,116,255,.35)', 250); });
});"""

SLIDE_CSS = """body{margin:0;height:100vh;display:grid;place-items:center;background:radial-gradient(1200px 600px at 20% 10%,#1e1b4b 0%,#0b0f17 60%);
color:#f2f4f7;font-family:Inter,Segoe UI,sans-serif}.s{width:1280px}.k{color:#a5b4fc;font:600 18px Inter;letter-spacing:.12em;text-transform:uppercase}
h1{font-size:60px;line-height:1.08;margin:14px 0 18px;letter-spacing:-.02em}h2{font-size:44px;margin:10px 0 26px;letter-spacing:-.01em}
p{font-size:24px;color:#c4cad6;line-height:1.5;margin:0}table{border-collapse:collapse;font-size:24px;width:100%}td,th{padding:14px 18px;border-bottom:1px solid #2b3646;text-align:left}
th{color:#8b95a7;font-weight:500;font-size:18px}.g{color:#6ce9a6;font-weight:700}.big{display:flex;gap:22px;margin-top:8px}.b{flex:1;background:#121826;border:1px solid #1f2937;border-radius:16px;padding:22px 24px}
.b b{display:block;font-size:46px;letter-spacing:-.02em}.b span{color:#8b95a7;font-size:18px}.mono{font-family:Consolas,monospace;font-size:19px;color:#c7d2fe;white-space:pre;line-height:1.45}
.logo{width:64px;height:64px;border-radius:16px;background:linear-gradient(135deg,#7c74ff,#7a5af8);display:grid;place-items:center;font:700 30px Inter}"""

SLIDES = {
    "title": """<div class=s><div class=logo>A</div><div class=k style="margin-top:28px">CentrAlign AI · Engineering Intern take-home</div>
<h1>Acme Workforce</h1><p>AI employees that do the work in real company systems,<br>check in when a decision is yours, and prove the result.</p></div>""",
    "learn": """<div class=s><div class=k>It learns your company's rules, with a human in the loop</div><h2>Asked once. Never again.</h2>
<table><tr><th>Same invoice with no due date</th><th>Questions to a human</th><th>Steps</th><th>Cost</th><th>Verified</th></tr>
<tr><td>Run 1: before learning</td><td>1</td><td>27</td><td>$0.180</td><td class=g>yes</td></tr>
<tr><td>Run 2: after the rule was approved</td><td class=g>0</td><td class=g>20</td><td class=g>$0.103</td><td class=g>yes</td></tr></table>
<p style="margin-top:26px">Learned rule (approved by a human in the Inbox): <i>"Globex PDFs never print a due date: use invoice date + 15 days."</i></p></div>""",
    "results": """<div class=s><div class=k>Measured against the sandbox's real database</div><h2>27 live runs. 0 false successes.</h2>
<div class=big><div class=b><b>16/17</b><span>development scenarios passed</span></div><div class=b><b>7/10</b><span>held-out runs passed<br>(tasks frozen before any run)</span></div>
<div class=b><b class=g>0</b><span>false successes<br>(said done, wasn't)</span></div><div class=b><b>5/5</b><span>correct safety stops</span></div></div>
<p style="margin-top:28px">Chaos tested: server errors, fake "Saved!", relabelled forms, revised invoices, prompt injection, bank-detail fraud, out-of-role work.</p></div>""",
    "arch": """<div class=s><div class=k>Architecture</div><h2>Safety lives in code, not in the prompt</h2><div class=mono>Request -> route to an AI employee (role file: responsibilities, systems, rules, checkpoints)
   -> ReAct loop: plan with exact success criteria -> act -> observe (page, HTTP status, files) -> adapt
   -> every write passes: duplicate ledger -> provenance check -> permission layer -> human approval
   -> verifier: different model, fresh browser, network-level read-only, re-downloads the source
   -> receipt + evidence report + audit trail      learning: answer -> proposed rule -> human approves</div></div>""",
    "close": """<div class=s><div class=logo>A</div><h1 style="margin-top:26px">Thank you</h1><p>Next: Raj-style WhatsApp checks with candidates · always-on employees watching the inbox ·
reusable skills compiled from verified runs.</p><p style="margin-top:22px;color:#8b95a7">Code, results and evidence reports: see the GitHub README.</p></div>""",
}


NEURAL_VOICE = "en-US-AndrewMultilingualNeural"  # warm, conversational male voice; alternatives: en-US-BrianMultilingualNeural, en-IN-PrabhatNeural


def tts(key: str, text: str) -> tuple[Path, float]:
    """Neural male voice via edge-tts (needs internet; the text is the public demo script).
    Falls back to the built-in Windows voice if the service is unreachable."""
    from moviepy.editor import AudioFileClip
    try:
        import asyncio
        import edge_tts
        out = WORK / f"{key}.mp3"
        for attempt in range(6):  # the free service occasionally returns no audio: retry before giving up
            try:
                asyncio.run(edge_tts.Communicate(text, NEURAL_VOICE, rate="-2%").save(str(out)))
                if out.exists() and out.stat().st_size > 2000:
                    break
            except Exception:
                pass
            time.sleep(2 + attempt * 2)
        else:
            raise RuntimeError("neural voice returned no audio after 6 attempts")
    except Exception as e:  # offline or service down
        print(f"neural voice unavailable ({type(e).__name__}); using Windows voice for {key}")
        out = WORK / f"{key}.wav"
        script = (f"Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$s.SelectVoice('{VOICE}'); $s.Rate = 0; $s.SetOutputToWaveFile('{out}'); $s.Speak(@'\n{text}\n'@); $s.Dispose()")
        _run(["powershell", "-NoProfile", "-Command", script], check=True)
    with AudioFileClip(str(out)) as a:
        return out, a.duration


class Recorder:
    def __init__(self, page, t0):
        self.page, self.t0, self.segments = page, t0, []

    def now(self) -> float:
        return time.time() - self.t0

    def caption(self, text: str):
        try:
            self.page.evaluate(CAPTION_JS, text)
        except Exception:
            pass

    def say(self, key: str, extra: float = 0.6):
        """Narrated segment at real speed: caption + hold for the narration's duration."""
        wav, dur = AUDIO[key]
        self.caption(N[key])
        start = self.now()
        self.page.wait_for_timeout(int((dur + extra) * 1000))
        self.segments.append({"start": start, "end": self.now(), "speed": 1.0, "audio": str(wav)})

    def fast(self, until, caption: str = "", timeout: float = 600, poll: float = 1.0):
        """Waiting segment, sped up FAST x in the final cut. `until()` returns truthy to stop."""
        self.caption(caption)
        start, end_by = self.now(), time.time() + timeout
        while time.time() < end_by:
            v = until()
            if v:
                break
            self.page.wait_for_timeout(int(poll * 1000))
        self.segments.append({"start": start, "end": self.now(), "speed": FAST, "audio": None})
        return v

    def hold(self, seconds: float):
        start = self.now()
        self.page.wait_for_timeout(int(seconds * 1000))
        self.segments.append({"start": start, "end": self.now(), "speed": 1.0, "audio": None})


def slide(rec: Recorder, name: str):
    p = WORK / f"slide-{name}.html"
    p.write_text(f"<!doctype html><meta charset=utf-8><style>{SLIDE_CSS}</style>{SLIDES[name]}", encoding="utf-8")
    rec.page.goto(p.as_uri())
    rec.page.wait_for_timeout(300)


def events(run_id: str) -> list[dict]:
    try:
        return httpx.get(f"{BASE}/runs/{run_id}/events", timeout=10).json()
    except Exception:
        return {"events": [], "pending": [], "result": None}


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    print("generating narration…")
    global AUDIO
    AUDIO = {k: tts(k, v) for k, v in N.items()}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, color_scheme="dark",
                                  record_video_dir=str(WORK), record_video_size={"width": W, "height": H})
        ctx.add_init_script(CURSOR_INIT)
        page = ctx.new_page()
        t0 = time.time()
        rec = Recorder(page, t0)

        slide(rec, "title"); rec.say("title", 1.0)

        page.goto(f"{BASE}/runs"); page.wait_for_load_state("networkidle")
        page.locator(".emp-card, [class*=emp]").first.hover()
        rec.say("roster")

        page.goto(f"{BASE}/employees/diya"); page.wait_for_load_state("networkidle")
        rec.caption(N["profile"])
        start = rec.now()
        for _ in range(6):
            page.mouse.wheel(0, 260); page.wait_for_timeout(int(AUDIO["profile"][1] * 1000 / 7))
        page.mouse.wheel(0, -2000)
        rec.segments.append({"start": start, "end": rec.now(), "speed": 1.0, "audio": str(AUDIO["profile"][0])})

        # ---- live run: the brief's task with two injected problems
        page.goto(f"{BASE}/runs"); page.wait_for_load_state("networkidle")
        rec.caption(N["assign"])
        start = rec.now()
        page.locator("#seg button", has_text="Diya").click(); page.wait_for_timeout(500)
        page.locator("#presets >> text=Globex invoice into the ERP").click(); page.wait_for_timeout(600)
        page.locator("details.stress summary").click(); page.wait_for_timeout(600)
        page.locator("#chaos >> text=Server error on save").click(); page.wait_for_timeout(400)
        page.locator("#chaos >> text=Amount above approval limit").click(); page.wait_for_timeout(400)
        remaining = AUDIO["assign"][1] - (rec.now() - start)
        if remaining > 0:
            page.wait_for_timeout(int(remaining * 1000))
        page.locator("#assignBtn").click()
        page.wait_for_url("**/runs/2*", timeout=20000)
        run_id = page.url.rstrip("/").split("/")[-1]
        rec.segments.append({"start": start, "end": rec.now(), "speed": 1.0, "audio": str(AUDIO["assign"][0])})
        print("live run:", run_id)

        rec.fast(lambda: events(run_id).get("pending"), "Working: reading the SOP, searching the mailbox, reading the PDF, filling the bill…")
        rec.caption(N["approval"])
        start = rec.now()
        page.wait_for_timeout(int(max(0, AUDIO["approval"][1] - 3) * 1000))
        note = page.locator("[data-note]").first
        if note.count():
            note.click(); note.type("Approved - Finance Manager", delay=40)
        page.locator("button", has_text="Approve and continue").first.click()
        page.wait_for_timeout(2500)
        rec.segments.append({"start": start, "end": rec.now(), "speed": 1.0, "audio": str(AUDIO["approval"][0])})

        said_error = said_verify = False
        while True:
            r = events(run_id)
            kinds = [(e["kind"], e.get("outcome"), e.get("status")) for e in r["events"]]
            if not said_error and any(k == "action_ledger" and o == "http_error" for k, o, _ in kinds):
                rec.say("error"); said_error = True; continue
            if not said_verify and any(k == "verifier" and s == "started" for k, _, s in kinds):
                rec.say("verify"); said_verify = True; continue
            if r.get("result"):
                break
            rec.fast(lambda: (lambda x: x.get("result") or (not said_error and any(e["kind"] == "action_ledger" and e.get("outcome") == "http_error" for e in x["events"]))
                              or (not said_verify and any(e["kind"] == "verifier" and e.get("status") == "started" for e in x["events"])))(events(run_id)),
                     "Working…", timeout=900, poll=1.5)
        page.wait_for_timeout(2500)
        page.evaluate("window.scrollTo(0, 0)")
        rec.say("receipt", 1.2)

        # ---- generalisation: recruiting on the same code
        page.goto(f"{BASE}/runs/sample-recruiting-screening"); page.wait_for_timeout(3500)
        rec.say("recruit")
        page.goto(f"{BASE}/ats"); page.wait_for_load_state("networkidle")
        httpx.get(f"{BASE}/ats")  # noop
        rec.say("ats")

        for name in ("learn", "results", "arch", "close"):
            slide(rec, name)
            rec.say(name, 1.0)

        video_path = page.video.path()
        ctx.close(); browser.close()

    (WORK / "segments.json").write_text(json.dumps(rec.segments, indent=1), encoding="utf-8")
    cut(Path(video_path), rec.segments)


def _run(cmd, **kw):
    """subprocess.run with retries: on a memory-starved Windows PC, starting a process can fail briefly."""
    for attempt in range(8):
        try:
            return subprocess.run(cmd, **kw)
        except OSError:
            time.sleep(4 + attempt * 3)
    return subprocess.run(cmd, **kw)


HOLD_ONLY = {"title", "roster", "error", "verify", "receipt", "recruit", "ats", "learn", "results", "arch", "close"}


def _probe_duration(ff: str, path) -> float:
    """Duration in seconds from ffmpeg's own banner (no extra dependencies, tiny memory)."""
    import re
    r = _run([ff, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def cut(raw: Path, segments: list[dict]):
    """Edit the raw recording scene by scene with small ffmpeg commands (low memory), then join and add the voice.
    Voice clips never overlap: a scene is held (last frame frozen) until its narration has finished plus a short
    pause, so a long sentence can never run into the next scene."""
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    parts_dir = WORK / "parts"
    parts_dir.mkdir(exist_ok=True)
    total_src = _probe_duration(ff, raw)

    parts, voices, t = [], [], 0.0
    for i, s in enumerate(segments):
        a, b = max(0.0, s["start"]), min(total_src, s["end"])
        if b - a < 0.2:
            continue
        seg_len = (b - a) / s["speed"]
        hold = 0.0
        if s["audio"]:
            ad = _probe_duration(ff, s["audio"])
            need = 0.25 + ad + 0.35  # lead-in + speech + short pause before the next scene
            if Path(s["audio"]).stem in HOLD_ONLY and seg_len > need + 0.5:  # nothing happens on screen: cut the silent tail
                b = a + need * s["speed"]
                seg_len = (b - a) / s["speed"]
            hold = max(0.0, need - seg_len)
            voices.append((s["audio"], t + 0.25))
        vf = f"setpts=(PTS-STARTPTS)/{s['speed']},fps=25,scale=1280:720"
        if hold:
            vf += f",tpad=stop_mode=clone:stop_duration={hold:.3f}"
        part = parts_dir / f"p{i:02d}.mp4"
        _run([ff, "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(raw), "-an",
                        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                        "-threads", "2", str(part)], check=True)
        parts.append(part)
        t += seg_len + hold

    listing = parts_dir / "list.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    silent, mixed, out = OUT / "_silent.mp4", OUT / "_voice.m4a", OUT / "acme-workforce-demo.mp4"
    _run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)], check=True)

    cmd = [ff, "-y", "-loglevel", "error"]
    for path, _ in voices:
        cmd += ["-i", path]
    delays = "".join(f"[{i}:a]adelay={int(st * 1000)}|{int(st * 1000)}[a{i}];" for i, (_, st) in enumerate(voices))
    mix = "".join(f"[a{i}]" for i in range(len(voices))) + f"amix=inputs={len(voices)}:normalize=0:duration=longest[o]"
    cmd += ["-filter_complex", delays + mix, "-map", "[o]", "-c:a", "aac", "-b:a", "160k", str(mixed)]
    _run(cmd, check=True)
    _run([ff, "-y", "-loglevel", "error", "-i", str(silent), "-i", str(mixed), "-c:v", "copy", "-c:a", "aac",
                    "-shortest", str(out)], check=True)
    for p in parts:
        p.unlink(missing_ok=True)
    silent.unlink(missing_ok=True)
    mixed.unlink(missing_ok=True)
    print(f"video: {out}  ({t:.0f}s)")


def recut():
    """Re-edit with new narration, reusing the existing raw recording and timings (no new live run, no LLM cost)."""
    segments = json.loads((WORK / "segments.json").read_text(encoding="utf-8"))
    raw = max(WORK.glob("page@*.webm"), key=lambda p: p.stat().st_mtime)
    for s in segments:
        if s["audio"]:
            key = Path(s["audio"]).stem
            s["audio"] = str(tts(key, N[key])[0])
        elif s["speed"] > 1 and (s["end"] - s["start"]) / s["speed"] >= 8:  # long sped-up wait: narrate it, no dead air
            s["audio"] = str(tts("work", N["work"])[0])
    cut(raw, segments)


if __name__ == "__main__":
    import sys
    recut() if "--recut" in sys.argv else main()
