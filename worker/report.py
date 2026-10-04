"""Evidence report: what was asked, what was done, what was verified, what needs a human."""
from __future__ import annotations

import html
import json
from pathlib import Path

BADGE = {True: ("VERIFIED", "#1a7f37"), False: ("NOT VERIFIED", "#cf222e"), None: ("NOT VERIFIED (ended early)", "#9a6700")}


def write_report(run_dir: Path, r: dict, events: list[dict]) -> Path:
    e = html.escape
    badge, color = BADGE[r.get("verified")]
    last_verdicts = r["verifications"][-1]["verdicts"] if r.get("verifications") else []
    shots = [ev.get("screenshot") for ev in events if ev["kind"] == "observation" and ev.get("screenshot")]
    approvals = [ev for ev in events if ev["kind"] == "approval"]
    timeline = [ev for ev in events if ev["kind"] in ("thought", "tool_call", "policy", "approval", "human", "guard", "verifier", "flag", "error")]

    def rel(p: str) -> str:
        return Path(p).relative_to(run_dir).as_posix() if p and Path(p).is_absolute() else p

    rows = "".join(f"<tr><td>{e(v['criterion'])}</td><td><b>{e(v['verdict'])}</b></td><td>{e(v['evidence'])}</td></tr>" for v in last_verdicts)
    facts = "".join(f"<li><b>{e(k)}</b>: {e(str(v['value']))} <span class=m>({e(v['source'])})</span></li>" for k, v in r["facts"].items())
    esc = "".join(f"<li>{e(json.dumps(x, default=str))}</li>" for x in r["escalations"]) or "<li>None</li>"
    flags = "".join(f"<li><b>{e(f['concern'])}</b> - {e(f['evidence'])}</li>" for f in r["flags"]) or "<li>None</li>"
    ledger = "".join(f"<tr><td>{x['step']}</td><td>{e(x['button'])}</td><td>{e(x['url'])}</td><td>{e(json.dumps(x['fields']))}</td><td>{x['outcome']}</td></tr>" for x in r["ledger"])
    appr = "".join(f"<li>{e(a.get('status'))}: {e(json.dumps(a.get('request') or a.get('note') or '', default=str))}</li>" for a in approvals) or "<li>None</li>"
    tl = "".join(f"<li><code>{ev['kind']}</code> {e(_short(ev))}</li>" for ev in timeline)
    gallery = "".join(f'<a href="{e(rel(s))}"><img src="{e(rel(s))}" loading="lazy"></a>' for s in shots[-8:])
    plan = "".join(f"<li>[{e(s.get('status', ''))}] {e(s.get('description', ''))}</li>" for s in r["plan"])
    u = r["usage"]
    doc = f"""<!doctype html><html><head><meta charset=utf-8><title>Run {e(r['run_id'])}</title><style>
body{{font-family:Segoe UI,Arial;margin:24px;max-width:1100px;color:#1f2328}} .badge{{background:{color};color:#fff;padding:4px 10px;border-radius:4px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #d0d7de;padding:6px;font-size:13px;vertical-align:top}} .m{{color:#656d76}}
img{{width:260px;border:1px solid #ccc;margin:4px}} li{{margin:3px 0;font-size:14px}} code{{background:#f6f8fa;padding:1px 4px}}</style></head><body>
<h1>AI worker run report</h1>
<p><b>Task:</b> {e(r['goal'])}</p>
<p><span class=badge>{badge}</span> &nbsp; status: <b>{e(r['status'])}</b> · {r['steps']} steps · {r['duration_s']}s · ${r['cost_usd']} ·
{u['llm_calls']} LLM calls ({u['input']} in / {u['cache_read']} cached / {u['output']} out tokens)</p>
<h2>Summary</h2><p>{e(r['summary'])}</p>
<h2>Independent verification</h2><table><tr><th>Criterion</th><th>Verdict</th><th>Evidence observed by verifier</th></tr>{rows or '<tr><td colspan=3>Not run</td></tr>'}</table>
{'<p><b>Deterministic check issues:</b> ' + e('; '.join(r.get('deterministic_issues') or [])) + '</p>' if r.get('deterministic_issues') else ''}
<h2>Needs attention / flagged</h2><ul>{flags}</ul>
<h2>Human interactions</h2><h3>Approvals</h3><ul>{appr}</ul><h3>Questions & escalations</h3><ul>{esc}</ul>
<h2>Facts gathered (with sources)</h2><ul>{facts or '<li>None</li>'}</ul>
<h2>Plan</h2><ol>{plan}</ol>
<h2>Consequential actions (idempotency ledger)</h2><table><tr><th>Step</th><th>Button</th><th>Page</th><th>Values</th><th>Outcome</th></tr>{ledger}</table>
<h2>Screenshots (latest)</h2>{gallery}
<h2>Timeline</h2><ol>{tl}</ol>
<p class=m>Full trace: trace.jsonl · result.json</p></body></html>"""
    out = run_dir / "report.html"
    out.write_text(doc, encoding="utf-8")
    return out


def _short(ev: dict) -> str:
    data = {k: v for k, v in ev.items() if k not in ("ts", "kind")}
    if ev["kind"] == "thought":
        return str(data.get("text", ""))[:400]
    return json.dumps(data, default=str)[:400]
