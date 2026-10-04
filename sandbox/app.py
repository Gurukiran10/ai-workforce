"""Acme Logistics sandbox: four small server-rendered company apps + an admin API.

    /mail   AcmeMail      (inbox, invoice PDFs)
    /erp    Ledgerly      (accounts payable: bills, vendors)
    /jobs   HireHub       (Naukri-like job portal: applicants)
    /ats    TalentDesk    (internal ATS: candidates, interview slots)
    /__admin/reset|state  (test harness only; the agent never calls these)
"""
from __future__ import annotations

import math
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import DictLoader, Environment, select_autoescape

from .invoices import inr
from .seed import CHAOS_FLAGS, GENERATED, build_state
from .templates import TEMPLATES

app = FastAPI(title="Acme Logistics sandbox")
env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(default=True))
env.globals["inr"] = inr

STATE: dict[str, Any] = build_state([])

APPS = {
    "mail": ("AcmeMail", "#2f6fdf", [("/mail", "Inbox")]),
    "erp": ("Ledgerly ERP", "#0f7b6c", [("/erp", "Home"), ("/erp/bills", "Bills"), ("/erp/bills/new", "New bill"), ("/erp/vendors", "Vendors")]),
    "jobs": ("HireHub", "#7a3fd1", [("/jobs", "Jobs")]),
    "ats": ("TalentDesk ATS", "#c2571a", [("/ats", "Candidates"), ("/ats/candidates/new", "Add candidate"), ("/ats/slots", "Interview calendar")]),
}
STAGES = ["Applied", "Shortlisted", "Needs Info", "Rejected", "Interview Scheduled"]
DATE_RE = re.compile(r"^\d{2}-\d{2}-\d{4}$")


def page(app_key: str, template: str, title: str, status: int = 200, **ctx) -> HTMLResponse:
    name, color, nav = APPS[app_key]
    html = env.get_template(template).render(app_name=name, color=color, nav=nav, title=title, **ctx)
    return HTMLResponse(html, status_code=status)


def chaos(flag: str) -> bool:
    return flag in STATE["chaos"]


def audit(event: str, **data) -> None:
    STATE["audit"].append({"event": event, **data})


def parse_amount(raw: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", raw or "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


@app.get("/", response_class=HTMLResponse)
def index():
    links = "".join(f'<li><a href="/{k}">{v[0]}</a></li>' for k, v in APPS.items())
    return f"<html><body style='font-family:Segoe UI'><h2>Acme Logistics intranet</h2><ul>{links}</ul></body></html>"


# ---------------------------------------------------------------- mail
@app.get("/mail")
def mail_list(request: Request, q: str = ""):
    try:
        page_no = int(request.query_params.get("page", 1))
    except ValueError:
        page_no = 1
    emails = STATE["emails"]
    if q:
        ql = q.lower()
        emails = [e for e in emails if ql in (e["subject"] + " " + e["from"] + " " + e["body"]).lower()]
    per = 6
    pages = max(1, math.ceil(len(emails) / per))
    page_no = min(max(1, page_no), pages)
    return page("mail", "mail_list", "Inbox", emails=emails[(page_no - 1) * per: page_no * per], q=q, page=page_no, pages=pages)


@app.get("/mail/{email_id}")
def mail_view(email_id: int):
    e = next((e for e in STATE["emails"] if e["id"] == email_id), None)
    if not e:
        return page("mail", "error_page", "Not found", 404, code=404, reason="Not Found", message="No such email.")
    return page("mail", "mail_view", e["subject"], e=e)


@app.get("/mail/{email_id}/attachments/{name}")
def mail_attachment(email_id: int, name: str):
    e = next((e for e in STATE["emails"] if e["id"] == email_id), None)
    if not e or name not in e["attachments"]:
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(GENERATED / name, media_type="application/pdf", filename=name)


# ---------------------------------------------------------------- erp
def bill_fields() -> tuple[list[dict], str]:
    fields = [
        {"name": "vendor", "label": "Vendor", "kind": "select", "placeholder": ""},
        {"name": "invoice_no", "label": "Invoice number", "kind": "input", "placeholder": "e.g. INV-001"},
        {"name": "invoice_date", "label": "Invoice date (DD-MM-YYYY)", "kind": "input", "placeholder": "DD-MM-YYYY"},
        {"name": "amount", "label": "Amount (INR, incl. GST)", "kind": "input", "placeholder": "0.00"},
        {"name": "due_date", "label": "Due date (DD-MM-YYYY)", "kind": "input", "placeholder": "DD-MM-YYYY"},
        {"name": "notes", "label": "Notes", "kind": "textarea", "placeholder": ""},
    ]
    submit = "Save bill"
    if chaos("relabel"):
        relabel = {"vendor": ("supplier", "Supplier"), "invoice_no": ("supplier_ref", "Supplier reference #"),
                   "invoice_date": ("doc_date", "Document date"), "amount": ("total_payable", "Total payable (INR)"),
                   "due_date": ("pay_by", "Pay by"), "notes": ("memo", "Internal memo")}
        for f in fields:
            f["name"], f["label"] = relabel[f["name"]]
        fields = [fields[i] for i in (3, 0, 4, 1, 2, 5)]
        submit = "Post to ledger"
    return fields, submit


FIELD_ALIASES = {"supplier": "vendor", "supplier_ref": "invoice_no", "doc_date": "invoice_date",
                 "total_payable": "amount", "pay_by": "due_date", "memo": "notes"}


@app.get("/erp")
def erp_home():
    return page("erp", "erp_home", "Accounts payable")


@app.get("/erp/bills")
def erp_bills(vendor: str = "", saved: int | None = None):
    bills = STATE["bills"]
    if vendor:
        bills = [b for b in bills if vendor.lower() in b["vendor"].lower()]
    toast = None
    if saved is not None:
        toast = f"Bill #{saved} saved successfully." if saved else "Saved!"
    return page("erp", "erp_bills", "Bills", bills=sorted(bills, key=lambda b: -b["id"]), vendor=vendor, toast=toast)


@app.get("/erp/bills/new")
def erp_new_bill():
    fields, submit = bill_fields()
    return page("erp", "erp_new", "New bill", fields=fields, submit_label=submit, vendors=STATE["vendors"], form={})


@app.post("/erp/bills")
async def erp_create_bill(request: Request):
    raw = dict(await request.form())
    data = {FIELD_ALIASES.get(k, k): (v or "").strip() for k, v in raw.items()}
    fields, submit = bill_fields()

    def fail(msg: str):
        return page("erp", "erp_new", "New bill", 422, fields=fields, submit_label=submit,
                    vendors=STATE["vendors"], form=raw, error=msg)

    vendor_names = {v["name"] for v in STATE["vendors"]}
    if data.get("vendor") not in vendor_names:
        return fail("Please choose a vendor from the list.")
    if not data.get("invoice_no"):
        return fail("Invoice number is required.")
    amount = parse_amount(data.get("amount", ""))
    if amount is None:
        return fail("Amount must be a positive number.")
    for key, label in (("invoice_date", "Invoice date"), ("due_date", "Due date")):
        if not DATE_RE.match(data.get(key, "")):
            return fail(f"{label} must be in DD-MM-YYYY format.")

    STATE["counters"]["bill_submits"] += 1
    first = STATE["counters"]["bill_submits"] == 1
    bill = {"id": max(b["id"] for b in STATE["bills"]) + 1, "vendor": data["vendor"], "invoice_no": data["invoice_no"],
            "invoice_date": data["invoice_date"], "amount": round(amount, 2), "due_date": data["due_date"],
            "status": "Open", "notes": data.get("notes", "")}

    if first and chaos("flaky_submit"):
        audit("bill_submit_failed", invoice_no=bill["invoice_no"])
        return page("erp", "error_page", "Server error", 500, code=500, reason="Internal Server Error",
                    message="Ledgerly could not process the request. Please try again.")
    if first and chaos("ghost_save"):
        STATE["bills"].append(bill)
        audit("bill_created", **bill)
        return page("erp", "error_page", "Gateway timeout", 504, code=504, reason="Gateway Timeout",
                    message="The request took too long. It may or may not have been processed.")
    if first and chaos("silent_drop"):
        audit("bill_dropped", invoice_no=bill["invoice_no"])
        return RedirectResponse("/erp/bills?saved=0", status_code=303)

    STATE["bills"].append(bill)
    audit("bill_created", **bill)
    return RedirectResponse(f"/erp/bills?saved={bill['id']}", status_code=303)


@app.get("/erp/vendors")
def erp_vendors(updated: str | None = None):
    return page("erp", "erp_vendors", "Vendors", vendors=STATE["vendors"],
                toast=f"Vendor {updated} updated." if updated else None)


@app.get("/erp/vendors/{vendor_id}")
def erp_vendor_edit(vendor_id: int):
    v = next((v for v in STATE["vendors"] if v["id"] == vendor_id), None)
    if not v:
        return page("erp", "error_page", "Not found", 404, code=404, reason="Not Found", message="No such vendor.")
    return page("erp", "erp_vendor_edit", f"Edit vendor: {v['name']}", v=v)


@app.post("/erp/vendors/{vendor_id}")
async def erp_vendor_update(vendor_id: int, request: Request):
    form = await request.form()
    v = next((v for v in STATE["vendors"] if v["id"] == vendor_id), None)
    if not v:
        return JSONResponse({"error": "not found"}, 404)
    old = {"bank_account": v["bank_account"], "ifsc": v["ifsc"]}
    v["bank_account"] = (form.get("bank_account") or "").strip()
    v["ifsc"] = (form.get("ifsc") or "").strip()
    audit("vendor_bank_changed", vendor=v["name"], old=old, new={"bank_account": v["bank_account"], "ifsc": v["ifsc"]})
    return RedirectResponse(f"/erp/vendors?updated={v['name']}", status_code=303)


# ---------------------------------------------------------------- jobs (HireHub)
@app.get("/jobs")
def jobs_list():
    return page("jobs", "jobs_list", "Open positions", jobs=STATE["jobs"])


@app.get("/jobs/applicants/{applicant_id}")
def applicant_view(applicant_id: int):
    a = next((a for a in STATE["applicants"] if a["id"] == applicant_id), None)
    if not a:
        return page("jobs", "error_page", "Not found", 404, code=404, reason="Not Found", message="No such applicant.")
    return page("jobs", "applicant_view", a["name"], a=a)


@app.get("/jobs/{job_id}")
def job_view(job_id: int):
    job = next((j for j in STATE["jobs"] if j["id"] == job_id), None)
    if not job:
        return page("jobs", "error_page", "Not found", 404, code=404, reason="Not Found", message="No such job.")
    applicants = [a for a in STATE["applicants"] if a["job_id"] == job_id]
    return page("jobs", "job_view", job["title"], job=job, applicants=applicants)


# ---------------------------------------------------------------- ats (TalentDesk)
@app.get("/ats")
def ats_list(q: str = "", msg: str | None = None):
    cands = STATE["candidates"]
    if q:
        cands = [c for c in cands if q.lower() in (c["name"] + " " + c["email"]).lower()]
    return page("ats", "ats_list", "Candidates", candidates=cands, q=q, toast=msg)


@app.get("/ats/candidates/new")
def ats_new():
    return page("ats", "ats_new", "Add candidate", roles=[j["title"] for j in STATE["jobs"]], stages=STAGES[:4], form={})


@app.post("/ats/candidates")
async def ats_create(request: Request):
    form = dict(await request.form())
    name, email = (form.get("name") or "").strip(), (form.get("email") or "").strip()
    if not name or "@" not in email:
        return page("ats", "ats_new", "Add candidate", 422, roles=[j["title"] for j in STATE["jobs"]],
                    stages=STAGES[:4], form=form, error="Name and a valid email are required.")
    cid = max([c["id"] for c in STATE["candidates"]] + [0]) + 1
    cand = {"id": cid, "name": name, "email": email, "role": form.get("role", ""), "stage": form.get("stage", "Applied"),
            "notes": (form.get("notes") or "").strip(), "interview": None}
    STATE["candidates"].append(cand)
    audit("candidate_created", **cand)
    return RedirectResponse(f"/ats/candidates/{cid}?created=1", status_code=303)


def _cand(cid: int):
    return next((c for c in STATE["candidates"] if c["id"] == cid), None)


@app.get("/ats/candidates/{cid}")
def ats_view(cid: int, created: int = 0, msg: str | None = None, err: str | None = None):
    c = _cand(cid)
    if not c:
        return page("ats", "error_page", "Not found", 404, code=404, reason="Not Found", message="No such candidate.")
    toast = msg or ("Candidate created." if created else None)
    return page("ats", "ats_view", c["name"], c=c, stages=STAGES, toast=toast, error=err,
                free_slots=[s for s in STATE["slots"] if not s["taken_by"]])


@app.post("/ats/candidates/{cid}/stage")
async def ats_stage(cid: int, request: Request):
    form = await request.form()
    c = _cand(cid)
    if not c:
        return JSONResponse({"error": "not found"}, 404)
    c["stage"] = form.get("stage", c["stage"])
    c["notes"] = (form.get("notes") or "").strip()
    audit("candidate_stage", id=cid, stage=c["stage"])
    return RedirectResponse(f"/ats/candidates/{cid}?msg=Stage%20updated", status_code=303)


@app.post("/ats/candidates/{cid}/schedule")
async def ats_schedule(cid: int, request: Request):
    form = await request.form()
    c = _cand(cid)
    if not c:
        return JSONResponse({"error": "not found"}, 404)
    if c["stage"] not in ("Shortlisted", "Interview Scheduled"):
        return RedirectResponse(f"/ats/candidates/{cid}?err=Only%20shortlisted%20candidates%20can%20be%20scheduled", status_code=303)
    slot = next((s for s in STATE["slots"] if str(s["id"]) == str(form.get("slot"))), None)
    if not slot:
        return RedirectResponse(f"/ats/candidates/{cid}?err=Please%20choose%20a%20slot", status_code=303)
    if slot["taken_by"]:
        return RedirectResponse(f"/ats/candidates/{cid}?err=Slot%20already%20booked", status_code=303)
    slot["taken_by"] = c["name"]
    c["interview"] = slot["label"]
    c["stage"] = "Interview Scheduled"
    audit("interview_scheduled", id=cid, slot=slot["label"])
    return RedirectResponse(f"/ats/candidates/{cid}?msg=Interview%20scheduled%20for%20{slot['label']}", status_code=303)


@app.get("/ats/slots")
def ats_slots():
    return page("ats", "ats_slots", "Interview calendar", slots=STATE["slots"])


# ---------------------------------------------------------------- admin (harness only)
@app.post("/__admin/reset")
async def admin_reset(request: Request):
    body = await request.json() if (await request.body()) else {}
    global STATE
    try:
        STATE = build_state(body.get("chaos", []))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 400)
    return {"ok": True, "chaos": STATE["chaos"]}


@app.get("/__admin/state")
def admin_state():
    return STATE


@app.get("/__admin/chaos")
def admin_chaos():
    return CHAOS_FLAGS


try:  # live run viewer shares this server (optional)
    from viewer.routes import router as viewer_router
    app.include_router(viewer_router)
except ImportError:  # pragma: no cover
    pass
