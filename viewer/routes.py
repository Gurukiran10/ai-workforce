"""AI Workforce console: roster of AI employees, inbox of decisions, profiles, live runs, audit log.

Served by the sandbox server at /runs. Reads runs/<id>/trace.jsonl as it grows; approvals and
questions go through WebChannel's pending/ and responses/ files. No DB, no websockets.
Role definitions come from roles/<id>.yaml (with a built-in fallback), trust stats are computed
from run results, and learning proposals live in memory/_proposed/<id>.json.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
ROLES = ROOT / "roles"
MEMORY = ROOT / "memory"
PROPOSED = MEMORY / "_proposed"
LEARNED = MEMORY / "learned_rules.md"
POLICIES = ROOT / "config" / "policies.yaml"
UI = Path(__file__).resolve().parent
ID_RE = re.compile(r"[\w-]+")
router = APIRouter()

try:  # backend learning helpers (built in parallel); inline fallbacks below
    from worker.learning import accept_proposal as _accept_proposal, reject_proposal as _reject_proposal  # type: ignore
except Exception:  # noqa: BLE001
    _accept_proposal = _reject_proposal = None
try:
    from worker.learning import trust_record as _trust_record, recommended_autonomy as _recommended_autonomy  # type: ignore
except Exception:  # noqa: BLE001
    _trust_record = _recommended_autonomy = None


# ---------------------------------------------------------------- helpers
def _check_id(x: str) -> str:
    if not ID_RE.fullmatch(x or ""):
        raise HTTPException(404, "bad id")
    return x


def _run_dir(run_id: str) -> Path:
    d = (RUNS / run_id).resolve()
    if not str(d).startswith(str(RUNS.resolve())) or not d.is_dir():
        raise HTTPException(404, "no such run")
    return d


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _read_yaml(p: Path):
    if yaml is None:
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _page(name: str, **subs) -> str:
    html = (UI / name).read_text(encoding="utf-8")
    for k, v in subs.items():
        html = html.replace("{{" + k + "}}", v)
    return html


# ---------------------------------------------------------------- roles
DEFAULT_ROLES = [
    {"id": "diya", "name": "Diya", "title": "Accounts Payable Associate", "reports_to": "Meera Rao (Finance Manager)",
     "avatar_hue": 265, "autonomy": "supervised", "match": r"invoice|bill|vendor|bank|payable",
     "responsibilities": ["Pick up vendor invoices from AcmeMail and read the PDF (the source of truth)",
                          "Enter bills into Ledgerly ERP with the exact vendor of record, dates and GST-inclusive totals",
                          "Check for duplicates and revised invoices before entering anything",
                          "Handle vendor master changes such as bank details, only with approval"],
     "systems": ["mail", "erp"], "knowledge": ["sop_accounts_payable.md", "vendors.md", "company_directory.md"],
     "business_rules": ["high_value_amount", "very_high_value_amount", "bank_details_change", "no_deletes", "outbound_email"],
     "escalation": {"approver": "Meera Rao (Finance Manager)", "questions_to": "the requester"},
     "human_checkpoints": ["Bills above INR 1,00,000 wait for Finance Manager approval",
                           "Any bank account / IFSC change waits for approval",
                           "Missing due dates are asked, never guessed",
                           "Look-alike sender domains are flagged and refused"]},
    {"id": "kabir", "name": "Kabir", "title": "Recruiting Coordinator", "reports_to": "Vikram Desai (Hiring Manager)",
     "avatar_hue": 170, "autonomy": "supervised", "match": r"applicant|applied|candidate|screen|interview|job|hire|recruit",
     "responsibilities": ["Collect new applications from HireHub and AcmeMail",
                          "Screen candidates against the job description and record them in TalentDesk",
                          "Move candidates to the right stage without creating duplicates",
                          "Book screening calls in the first free interview slot"],
     "systems": ["mail", "jobs", "ats"], "knowledge": ["sop_recruiting_screening.md", "jd_backend_engineer.md", "company_directory.md"],
     "business_rules": ["no_deletes", "outbound_email"],
     "escalation": {"approver": "Vikram Desai (Hiring Manager)", "questions_to": "the requester"},
     "human_checkpoints": ["Outbound email to candidates waits for approval",
                           "Ambiguous job titles are asked, never assumed",
                           "Slot conflicts are re-planned, never double-booked"]},
]


def _roles() -> list[dict]:
    out = []
    if ROLES.is_dir():
        for f in sorted(ROLES.glob("*.yaml")):
            r = _read_yaml(f)
            if isinstance(r, dict) and r.get("id"):
                r["_file"] = True
                out.append(r)
    if not out:
        out = [dict(r) for r in DEFAULT_ROLES]
    for r in out:
        r.setdefault("name", str(r["id"]).title())
        r.setdefault("title", "AI employee")
        r.setdefault("avatar_hue", 220)
        r.setdefault("autonomy", "supervised")
        for k in ("responsibilities", "systems", "knowledge", "business_rules", "human_checkpoints"):
            r[k] = r.get(k) or []
        r["escalation"] = r.get("escalation") or {}
    return out


def _role_by_id(rid: str) -> dict | None:
    return next((r for r in _roles() if r["id"] == rid), None)


def _infer_role(goal: str, roles: list[dict]) -> str | None:
    g = goal or ""
    for r in roles:
        pat = r.get("match")
        try:
            if pat and re.search(pat, g, re.I):
                return r["id"]
        except re.error:
            continue
    return None


def _policies() -> list[dict]:
    p = _read_yaml(POLICIES) or {}
    return [x for x in (p.get("rules") or []) if isinstance(x, dict)]


def _directory() -> dict[str, str]:
    """Title -> person name, parsed from memory/company_directory.md ('- Finance Manager (...): Meera Rao')."""
    out = {}
    try:
        for line in (MEMORY / "company_directory.md").read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*-\s*([^:(]+?)\s*(?:\([^)]*\))?\s*:\s*([A-Z][\w .'-]+)$", line)
            if m and "http" not in line:
                out[m.group(1).strip()] = m.group(2).strip()
    except OSError:
        pass
    return out


def _approver_display(title: str | None) -> str:
    if not title:
        return ""
    if "(" in title:
        return title
    for t, name in _directory().items():
        if t.lower().startswith(title.lower()):
            return f"{name} ({title})"
    return title


# ---------------------------------------------------------------- run summaries (cached by trace mtime/size)
_CACHE: dict[str, tuple[tuple, dict]] = {}


def _short_url(u: str) -> str:
    return re.sub(r"^https?://[^/]+", "", str(u or "")) or "/"


def _sentence(ev: dict) -> str | None:
    k = ev.get("kind")
    if k == "tool_call":
        t, a = ev.get("tool", ""), ev.get("input") or {}
        if t.startswith("verifier."):
            return "Verifier is checking the result"
        return {
            "search_memory": lambda: f"Looked up company memory: {str(a.get('query', ''))[:60]}",
            "update_plan": lambda: "Updated the plan",
            "open_url": lambda: f"Opened {_short_url(a.get('url'))}",
            "click": lambda: "Clicked on the page",
            "type_text": lambda: "Filling in a form",
            "select_option": lambda: f"Selected “{a.get('option', '')}”",
            "read_page": lambda: "Reading the page",
            "read_file": lambda: f"Reading {a.get('path', 'a file')}",
            "remember": lambda: f"Noted {a.get('key', 'a fact')}",
            "flag_concern": lambda: "Flagged a concern",
            "finish": lambda: "Writing the report",
        }.get(t, lambda: None)()
    if k == "approval" and ev.get("status") == "requested":
        act = (ev.get("request") or {}).get("action", "")
        m = re.search(r'"([^"]+)"', act)
        return f"Waiting for approval: {m.group(1) if m else act}"
    if k == "approval":
        return f"Approval {ev.get('status')}"
    if k == "human" and ev.get("type") == "question":
        return "Asked you a question"
    if k == "verifier" and ev.get("status") == "started":
        return "Independent verifier is checking the work"
    if k == "learning":
        return "Proposed a new rule"
    return None


def _summarize(d: Path, roles: list[dict]) -> dict | None:
    tr = d / "trace.jsonl"
    try:
        st = tr.stat()
    except OSError:
        return None
    res_p = d / "result.json"
    res_m = res_p.stat().st_mtime if res_p.exists() else 0
    key = (st.st_mtime, st.st_size, res_m)
    hit = _CACHE.get(d.name)
    if hit and hit[0] == key:
        s = dict(hit[1])
    else:
        first, touches, sentence, verifier_model, last_ts = {}, 0, None, None, None
        try:
            with tr.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if i == 0:
                        first = ev
                    k = ev.get("kind")
                    if (k == "approval" and ev.get("status") == "requested") or (k == "human" and ev.get("type") == "question"):
                        touches += 1
                    if k == "verifier" and ev.get("model"):
                        verifier_model = ev["model"]
                    s2 = _sentence(ev)
                    if s2:
                        sentence = s2
                    last_ts = ev.get("ts", last_ts)
        except OSError:
            pass
        res = _read_json(res_p) or {}
        goal = res.get("goal") or first.get("goal", "")
        role = res.get("role") or first.get("role") or _infer_role(goal, roles)
        s = {"id": d.name, "goal": goal, "model": first.get("model", ""), "started": first.get("ts"),
             "last_ts": last_ts, "status": res.get("status", "running"), "verified": res.get("verified"),
             "steps": res.get("steps"), "cost_usd": res.get("cost_usd"), "duration_s": res.get("duration_s"),
             "role": role, "role_name": res.get("role_name") or first.get("role_name"),
             "human_touches": touches, "sentence": sentence, "verifier_model": verifier_model,
             "has_result": bool(res), "_mtime": st.st_mtime}
        _CACHE[d.name] = (key, dict(s))
    if s["status"] == "running" and time.time() - s["_mtime"] > 900:
        s["status"] = "abandoned"  # process died without writing a result
    pend = _pending(d) if s["status"] == "running" else []
    s["pending"] = len(pend)
    if pend:
        p = pend[-1]
        if p.get("kind") == "approval":
            act = (p.get("request") or {}).get("action", "")
            m = re.search(r'"([^"]+)"', act)
            s["sentence"] = f"Waiting for approval: {m.group(1) if m else act}"
        else:
            s["sentence"] = "Waiting for your answer"
    s["outcome"] = _outcome(s)
    if not s.get("role_name") and s.get("role"):
        r = next((x for x in roles if x["id"] == s["role"]), None)
        s["role_name"] = r["name"] if r else str(s["role"]).title()
    return s


def _outcome(s: dict) -> str:
    st = s["status"]
    if st == "running":
        return "needs_you" if s.get("pending") else "working"
    if st == "abandoned":
        return "abandoned"
    if s.get("verified"):
        return "verified"
    if st == "blocked":
        return "escalated"
    if st == "unverified":
        return "unverified"
    return "failed"


def _pending(d: Path) -> list[dict]:
    pdir, rdir = d / "pending", d / "responses"
    if not pdir.is_dir():
        return []
    out = []
    for f in sorted(pdir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        p = _read_json(f)
        if not p or (rdir / f"{p.get('id')}.json").exists():
            continue  # already answered; worker will clean it up
        p["created"] = f.stat().st_mtime
        out.append(p)
    return out


def _all_runs(limit: int | None = None) -> list[dict]:
    if not RUNS.is_dir():
        return []
    roles = _roles()
    dirs = [p for p in RUNS.iterdir() if p.is_dir() and not p.name.startswith("_") and (p / "trace.jsonl").exists()]
    dirs.sort(key=lambda p: (p / "trace.jsonl").stat().st_mtime, reverse=True)
    out = []
    for d in dirs[:limit] if limit else dirs:
        s = _summarize(d, roles)
        if s:
            out.append({k: v for k, v in s.items() if not k.startswith("_")})
    return out


# ---------------------------------------------------------------- trust
def _trust_inline(runs: list[dict], role_id: str) -> dict:
    mine = [r for r in runs if r.get("role") == role_id and r["status"] not in ("running",)]
    rec = {"tasks": len(mine), "verified": 0, "unverified": 0, "escalated": 0, "failed": 0, "cost_usd": 0.0, "last_run": None,
           "recent": [r["outcome"] for r in mine[:10]], "recent_statuses": [r["status"] for r in reversed(mine[:10])]}
    for r in mine:
        o = r["outcome"]
        rec["verified" if o == "verified" else "escalated" if o == "escalated" else "unverified" if o == "unverified" else "failed"] += 1
        rec["cost_usd"] += r.get("cost_usd") or 0
    rec["cost_usd"] = round(rec["cost_usd"], 4)
    if mine:
        rec["last_run"] = mine[0]["id"]
    return rec


def _recommend_inline(rec: dict) -> tuple[str, str]:
    if rec.get("verified", 0) < 3:
        return "supervised", f"Only {rec.get('verified', 0)} verified tasks so far; keep a human on every consequential action until there are at least 3."
    if "unverified" in (rec.get("recent") or []):
        return "supervised", "A recent task could not be verified; keep supervision until the last 10 runs are clean."
    return "standard", f"{rec['verified']} verified tasks and no unverified results in the last 10 runs; policy rules alone can gate risky actions."


def _trust(runs: list[dict], role_id: str) -> tuple[dict, tuple[str, str]]:
    rec = None
    if _trust_record:
        try:
            rec = _trust_record(RUNS, role_id)
        except Exception:  # noqa: BLE001
            rec = None
    inline = _trust_inline(runs, role_id)
    # Older runs carry no "role" in result.json (the backend counts only tagged runs); the inline
    # record infers the role from the goal, so prefer whichever has seen more of this employee's work.
    if not isinstance(rec, dict) or rec.get("tasks", 0) < inline["tasks"]:
        rec = inline
    else:
        rec = {**inline, **rec}
    rec_level = None
    if _recommended_autonomy:
        try:
            rec_level = tuple(_recommended_autonomy(rec))
        except Exception:  # noqa: BLE001
            rec_level = None
    return rec, rec_level or _recommend_inline(rec)


def _role_view(r: dict, runs: list[dict]) -> dict:
    mine = [x for x in runs if x.get("role") == r["id"]]
    active = next((x for x in mine if x["status"] == "running"), None)
    trust, (lvl, why) = _trust(runs, r["id"])
    status = "idle"
    if active:
        status = "waiting" if active["pending"] else "working"
    last = next((x for x in mine if x["status"] != "running"), None)
    return {**{k: v for k, v in r.items() if not k.startswith("_")},
            "trust": trust, "recommended": {"level": lvl, "reason": why},
            "status": status, "active_run": active, "last_run": last,
            "in_progress": sum(1 for x in mine if x["status"] == "running"),
            "needs_you": sum(x["pending"] for x in mine)}


# ---------------------------------------------------------------- pages
@router.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/runs")


@router.get("/runs", response_class=HTMLResponse)
def dashboard():
    return _page("index.html")


@router.get("/inbox", response_class=HTMLResponse)
def inbox_page():
    return _page("inbox.html")


@router.get("/employees/{role_id}", response_class=HTMLResponse)
def employee_page(role_id: str):
    return _page("employee.html", role_id=_check_id(role_id))


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(run_id: str):
    if not re.fullmatch(r"[\w.-]+", run_id):
        raise HTTPException(404)
    return _page("run.html", run_id=run_id)


@router.get("/runs-ui/{name}")
def ui_asset(name: str):
    f = UI / name
    if f.suffix not in (".css", ".js") or not f.is_file() or f.parent != UI:
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- APIs
@router.get("/api/runs")
def list_runs():
    return _all_runs(limit=60)


@router.get("/api/roles")
def list_roles():
    runs = _all_runs()
    return [_role_view(r, runs) for r in _roles()]


def _learned_rules(role_id: str | None = None) -> list[str]:
    try:
        lines = LEARNED.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        m = re.match(r"^\s*-\s*\[([\w-]+)\]\s*(.+)$", ln)
        if m and (role_id is None or m.group(1) == role_id):
            out.append(m.group(2).strip())
    return out


@router.get("/api/roles/{role_id}")
def get_role(role_id: str):
    _check_id(role_id)
    runs = _all_runs()
    roles = _roles()
    if role_id == "all":
        return {"id": "all", "runs": runs, "roles": [{k: v for k, v in r.items() if not k.startswith("_")} for r in roles]}
    r = next((x for x in roles if x["id"] == role_id), None)
    if not r:
        raise HTTPException(404, "no such employee")
    pol = {p.get("id"): p for p in _policies()}
    rules = []
    for pid in r["business_rules"]:
        p = pol.get(pid, {"id": pid, "description": "", "action": ""})
        rules.append({**p, "approver_display": _approver_display(p.get("approver"))})
    view = _role_view(r, runs)
    view.update({"rules": rules, "no_deletes": "no_deletes" in r["business_rules"],
                 "learned_rules": _learned_rules(role_id), "runs": [x for x in runs if x.get("role") == role_id],
                 "editable": bool(r.get("_file"))})
    return view


@router.post("/api/roles/{role_id}/autonomy")
async def set_autonomy(role_id: str, request: Request):
    _check_id(role_id)
    body = await request.json()
    level = str(body.get("level", ""))
    if level not in ("supervised", "standard"):
        raise HTTPException(400, "level must be supervised or standard")
    f = ROLES / f"{role_id}.yaml"
    if not f.is_file():
        raise HTTPException(404, "role file not found")
    text = f.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^(autonomy:\s*)[\"']?[\w-]+[\"']?(.*)$", lambda m: f"{m.group(1)}{level}{m.group(2)}", text, count=1)
    if not n:
        new = text.rstrip("\n") + f"\nautonomy: {level}\n"
    f.write_text(new, encoding="utf-8", newline="")
    return {"ok": True, "id": role_id, "autonomy": level}


def _proposals(status: str | None = "pending") -> list[dict]:
    if not PROPOSED.is_dir():
        return []
    out = []
    for f in sorted(PROPOSED.glob("*.json"), key=lambda p: p.stat().st_mtime):
        p = _read_json(f)
        if isinstance(p, dict) and (status is None or p.get("status", "pending") == status):
            p.setdefault("id", f.stem)
            out.append(p)
    return out


@router.get("/api/inbox")
def inbox():
    roles = {r["id"]: r for r in _roles()}
    items = []
    for s in _all_runs(limit=60):
        if s["status"] != "running" or not s["pending"]:
            continue
        for p in _pending(RUNS / s["id"]):
            req = p.get("request") or {}
            approver = req.get("approver")
            if not approver and req.get("policy_rule"):
                approver = next((x.get("approver") for x in _policies() if x.get("id") == req["policy_rule"]), None)
            items.append({"type": p.get("kind", "question"), "id": p.get("id"), "run_id": s["id"], "goal": s["goal"],
                          "role": s.get("role"), "role_name": s.get("role_name"), "created": p.get("created"),
                          "request": req, "question": p.get("question"), "options": p.get("options") or [],
                          "approver_display": _approver_display(approver)})
    for p in _proposals("pending"):
        r = roles.get(p.get("role"))
        items.append({"type": "learning", "id": p.get("id"), "run_id": p.get("run_id"), "role": p.get("role"),
                      "role_name": r["name"] if r else str(p.get("role") or "").title(), "rule": p.get("rule"),
                      "applies_to": p.get("applies_to"), "reason": p.get("reason"), "created": p.get("created")})
    items.sort(key=lambda i: (i["type"] == "learning", -(_ts(i.get("created")) or 0)))
    return {"count": len(items), "items": items}


def _ts(v):
    if isinstance(v, (int, float)):
        return v
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except (TypeError, ValueError):
        return None


def _decide_inline(pid: str, accept: bool) -> dict:
    f = PROPOSED / f"{pid}.json"
    p = _read_json(f)
    if not isinstance(p, dict):
        raise HTTPException(404, "no such proposal")
    if p.get("status", "pending") != "pending":
        return p
    p["status"] = "accepted" if accept else "rejected"
    p["decided"] = datetime.now().isoformat(timespec="seconds")
    if accept:
        line = f"- [{p.get('role')}] {p.get('rule')} (learned from run {p.get('run_id')}, approved by a human)\n"
        existing = LEARNED.read_text(encoding="utf-8") if LEARNED.exists() else "# Learned rules (human-approved)\n\n"
        if not existing.endswith("\n"):
            existing += "\n"
        LEARNED.write_text(existing + line, encoding="utf-8")
    f.write_text(json.dumps(p, indent=2), encoding="utf-8")
    return p


@router.post("/api/learning/{pid}/{decision}")
def decide_learning(pid: str, decision: str):
    _check_id(pid)
    if decision not in ("accept", "reject"):
        raise HTTPException(404)
    if not (PROPOSED / f"{pid}.json").is_file():
        raise HTTPException(404, "no such proposal")
    fn = _accept_proposal if decision == "accept" else _reject_proposal
    if fn:
        try:
            return {"ok": True, "proposal": fn(MEMORY, pid)}
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "proposal": _decide_inline(pid, decision == "accept")}


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, since: int = 0):
    if not (RUNS / run_id).is_dir():  # just launched, worker still starting
        return {"events": [], "next": 0, "pending": [], "result": None, "starting": True}
    d = _run_dir(run_id)
    lines = (d / "trace.jsonl").read_text(encoding="utf-8").splitlines() if (d / "trace.jsonl").exists() else []
    events = []
    for x in lines[since:]:
        try:
            events.append(json.loads(x))
        except json.JSONDecodeError:
            break  # partially written line; pick it up next poll
    pending = _pending(d)
    for p in pending:
        req = p.get("request") or {}
        approver = req.get("approver")
        if not approver and req.get("policy_rule"):
            approver = next((x.get("approver") for x in _policies() if x.get("id") == req["policy_rule"]), None)
        p["approver_display"] = _approver_display(approver)
    result = _read_json(d / "result.json")
    if result:
        result = {k: result.get(k) for k in ("status", "verified", "summary", "steps", "cost_usd", "duration_s", "usage",
                                             "claimed_status", "role", "role_name", "escalations")}
    return {"events": events, "next": since + len(events), "pending": pending, "result": result}


@router.post("/runs/{run_id}/respond")
async def run_respond(run_id: str, request: Request):
    d = _run_dir(run_id)
    body = await request.json()
    rid = "".join(c for c in str(body.get("id", "")) if c.isalnum())
    if not rid:
        raise HTTPException(400, "missing id")
    (d / "responses").mkdir(exist_ok=True)
    (d / "responses" / f"{rid}.json").write_text(json.dumps(body), encoding="utf-8")
    return {"ok": True}


@router.get("/runs/{run_id}/file/{path:path}")
def run_file(run_id: str, path: str):
    d = _run_dir(run_id)
    f = (d / path).resolve()
    if not str(f).startswith(str(d)) or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


@router.post("/api/runs/start")
async def start_run(request: Request):
    """Launch the worker as a separate process (same as the CLI), with approvals routed to this console."""
    body = await request.json()
    task = (body.get("task") or "").strip()
    if not task:
        raise HTTPException(400, "task is required")
    chaos = [c for c in body.get("chaos", []) if re.fullmatch(r"[a-z_]+", c)]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    cmd = [sys.executable, "-m", "worker", "run", task, "--human", "web", "--run-id", run_id]
    role = str(body.get("role") or "").strip()
    if role and ID_RE.fullmatch(role):
        cmd += ["--role", role]
    if chaos:
        cmd += ["--chaos", ",".join(chaos)]
    elif body.get("reset", True):
        cmd += ["--reset"]
    if body.get("headed"):
        cmd += ["--headed"]
    RUNS.mkdir(exist_ok=True)
    log = (RUNS / f"_{run_id}.log").open("w", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                     env={**os.environ, "PYTHONUTF8": "1"})
    return {"run_id": run_id}
