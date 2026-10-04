"""Jinja templates for the sandbox apps, kept in one module for easy reading."""

BASE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>{{ title }} · {{ app_name }}</title>
<style>
 body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}
 header{background:{{ color }};color:#fff;padding:10px 20px;display:flex;gap:18px;align-items:center}
 header b{font-size:18px;margin-right:12px} header a{color:#fff;text-decoration:none;opacity:.9}
 main{padding:20px;max-width:1000px}
 table{border-collapse:collapse;width:100%;background:#fff} th,td{border:1px solid #dde1e7;padding:6px 8px;text-align:left;font-size:14px}
 th{background:#eef1f5} .toast{background:#e5f6ea;border:1px solid #9bd3ab;padding:8px 12px;margin-bottom:12px}
 .error{background:#fde8e8;border:1px solid #f0a3a3;padding:8px 12px;margin-bottom:12px}
 form.card,.card{background:#fff;border:1px solid #dde1e7;padding:16px;margin:10px 0}
 label{display:block;margin-top:10px;font-weight:600;font-size:13px} input,select,textarea{padding:6px;width:320px;font-size:14px}
 button{margin-top:14px;padding:8px 16px;background:{{ color }};color:#fff;border:0;cursor:pointer;font-size:14px}
 .muted{color:#69707d;font-size:13px} pre{white-space:pre-wrap;font-family:inherit}
</style></head>
<body><header><b>{{ app_name }}</b>{% for href, text in nav %}<a href="{{ href }}">{{ text }}</a>{% endfor %}</header>
<main><h2>{{ title }}</h2>
{% if toast %}<div class="toast" role="status">{{ toast }}</div>{% endif %}
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
{% block body %}{% endblock %}</main></body></html>"""

MAIL_LIST = r"""{% extends "base" %}{% block body %}
<form method="get" action="/mail"><input name="q" placeholder="Search mail" aria-label="Search mail" value="{{ q }}"> <button type="submit">Search</button></form>
<table><tr><th>From</th><th>Subject</th><th>Received</th></tr>
{% for e in emails %}<tr><td>{{ e.from }}</td><td><a href="/mail/{{ e.id }}">{{ e.subject }}</a>{% if e.attachments %} 📎{% endif %}</td><td>{{ e.date }}</td></tr>{% endfor %}
</table>
<p class="muted">Page {{ page }} of {{ pages }}
{% if page > 1 %}<a href="/mail?q={{ q }}&page={{ page - 1 }}">Newer</a>{% endif %}
{% if page < pages %}<a href="/mail?q={{ q }}&page={{ page + 1 }}">Older</a>{% endif %}</p>
{% endblock %}"""

MAIL_VIEW = r"""{% extends "base" %}{% block body %}
<div class="card"><p><b>From:</b> {{ e.from }}<br><b>Received:</b> {{ e.date }}</p><pre>{{ e.body | urlize }}</pre>
{% if e.attachments %}<p><b>Attachments:</b></p><ul>{% for a in e.attachments %}<li><a href="/mail/{{ e.id }}/attachments/{{ a }}">{{ a }}</a></li>{% endfor %}</ul>{% endif %}
</div><a href="/mail">Back to inbox</a>
{% endblock %}"""

ERP_HOME = r"""{% extends "base" %}{% block body %}
<div class="card"><p>Welcome to Ledgerly, Acme Logistics accounts payable.</p>
<ul><li><a href="/erp/bills">View bills</a></li><li><a href="/erp/bills/new">Enter a new bill</a></li><li><a href="/erp/vendors">Vendors</a></li></ul></div>
{% endblock %}"""

ERP_BILLS = r"""{% extends "base" %}{% block body %}
<form method="get" action="/erp/bills"><input name="vendor" aria-label="Filter by vendor" placeholder="Filter by vendor" value="{{ vendor }}"> <button type="submit">Filter</button></form>
<p><a href="/erp/bills/new">+ New bill</a></p>
<table><tr><th>#</th><th>Vendor</th><th>Invoice No</th><th>Invoice Date</th><th>Amount (INR)</th><th>Due Date</th><th>Status</th><th>Notes</th></tr>
{% for b in bills %}<tr><td>{{ b.id }}</td><td>{{ b.vendor }}</td><td>{{ b.invoice_no }}</td><td>{{ b.invoice_date }}</td><td>{{ inr(b.amount) }}</td><td>{{ b.due_date }}</td><td>{{ b.status }}</td><td>{{ b.notes }}</td></tr>
{% else %}<tr><td colspan="8">No bills found.</td></tr>{% endfor %}</table>
{% endblock %}"""

ERP_NEW = r"""{% extends "base" %}{% block body %}
<form class="card" method="post" action="/erp/bills">
{% for f in fields %}
 <label for="{{ f.name }}">{{ f.label }}</label>
 {% if f.kind == 'select' %}<select id="{{ f.name }}" name="{{ f.name }}"><option value="">-- choose --</option>{% for v in vendors %}<option{% if form.get(f.name) == v.name %} selected{% endif %}>{{ v.name }}</option>{% endfor %}</select>
 {% elif f.kind == 'textarea' %}<textarea id="{{ f.name }}" name="{{ f.name }}">{{ form.get(f.name, '') }}</textarea>
 {% else %}<input id="{{ f.name }}" name="{{ f.name }}" value="{{ form.get(f.name, '') }}" placeholder="{{ f.placeholder }}">{% endif %}
{% endfor %}
<br><button type="submit">{{ submit_label }}</button></form>
{% endblock %}"""

ERP_VENDORS = r"""{% extends "base" %}{% block body %}
<table><tr><th>Vendor</th><th>Email domain</th><th>Bank account</th><th>IFSC</th><th></th></tr>
{% for v in vendors %}<tr><td>{{ v.name }}</td><td>{{ v.email_domain }}</td><td>{{ v.bank_account }}</td><td>{{ v.ifsc }}</td><td><a href="/erp/vendors/{{ v.id }}">Edit {{ v.name }}</a></td></tr>{% endfor %}</table>
{% endblock %}"""

ERP_VENDOR_EDIT = r"""{% extends "base" %}{% block body %}
<form class="card" method="post" action="/erp/vendors/{{ v.id }}">
<label for="bank_account">Bank account number</label><input id="bank_account" name="bank_account" value="{{ v.bank_account }}">
<label for="ifsc">IFSC code</label><input id="ifsc" name="ifsc" value="{{ v.ifsc }}">
<br><button type="submit">Update vendor bank details</button></form>
{% endblock %}"""

JOBS_LIST = r"""{% extends "base" %}{% block body %}
<table><tr><th>Job</th><th>Location</th><th>Posted</th><th>Status</th></tr>
{% for j in jobs %}<tr><td><a href="/jobs/{{ j.id }}">{{ j.title }}</a></td><td>{{ j.location }}</td><td>{{ j.posted }}</td><td>{{ j.status }}</td></tr>{% endfor %}</table>
{% endblock %}"""

JOB_VIEW = r"""{% extends "base" %}{% block body %}
<p class="muted">{{ job.location }} · posted {{ job.posted }}</p>
<h3>Applicants ({{ applicants|length }})</h3>
<table><tr><th>Name</th><th>Experience</th><th>Location</th><th>Applied</th></tr>
{% for a in applicants %}<tr><td><a href="/jobs/applicants/{{ a.id }}">{{ a.name }}</a></td><td>{{ a.experience_years }} yrs</td><td>{{ a.location }}</td><td>{{ a.applied }}</td></tr>{% endfor %}</table>
{% endblock %}"""

APPLICANT_VIEW = r"""{% extends "base" %}{% block body %}
<div class="card">
<p><b>Email:</b> {{ a.email }}</p>
<p><b>Total experience:</b> {{ a.experience_years }} years</p>
<p><b>Key skills:</b> {{ a.skills }}</p>
<p><b>Current location:</b> {{ a.location }} &nbsp; <b>Open to remote:</b> {{ a.open_to_remote }}</p>
<p><b>Notice period:</b> {{ a.notice_days }} days</p>
<p><b>Expected CTC:</b> {% if a.expected_ctc_lpa is none %}Not disclosed{% else %}{{ a.expected_ctc_lpa }} LPA{% endif %}</p>
<p><b>Profile summary:</b> {{ a.summary }}</p>
</div><a href="/jobs/{{ a.job_id }}">Back to applicants</a>
{% endblock %}"""

ATS_LIST = r"""{% extends "base" %}{% block body %}
<form method="get" action="/ats"><input name="q" aria-label="Search candidates" placeholder="Search candidates" value="{{ q }}"> <button type="submit">Search</button></form>
<p><a href="/ats/candidates/new">+ Add candidate</a> · <a href="/ats/slots">Interview calendar</a></p>
<table><tr><th>Name</th><th>Email</th><th>Role</th><th>Stage</th><th>Interview</th><th>Notes</th></tr>
{% for c in candidates %}<tr><td><a href="/ats/candidates/{{ c.id }}">{{ c.name }}</a></td><td>{{ c.email }}</td><td>{{ c.role }}</td><td>{{ c.stage }}</td><td>{{ c.interview or '' }}</td><td>{{ c.notes }}</td></tr>
{% else %}<tr><td colspan="6">No candidates.</td></tr>{% endfor %}</table>
{% endblock %}"""

ATS_NEW = r"""{% extends "base" %}{% block body %}
<form class="card" method="post" action="/ats/candidates">
<label for="name">Full name</label><input id="name" name="name" value="{{ form.get('name','') }}">
<label for="email">Email</label><input id="email" name="email" value="{{ form.get('email','') }}">
<label for="role">Role</label><select id="role" name="role">{% for r in roles %}<option{% if form.get('role') == r %} selected{% endif %}>{{ r }}</option>{% endfor %}</select>
<label for="stage">Stage</label><select id="stage" name="stage">{% for s in stages %}<option{% if form.get('stage') == s %} selected{% endif %}>{{ s }}</option>{% endfor %}</select>
<label for="notes">Screening notes</label><textarea id="notes" name="notes">{{ form.get('notes','') }}</textarea>
<br><button type="submit">Create candidate</button></form>
{% endblock %}"""

ATS_VIEW = r"""{% extends "base" %}{% block body %}
<div class="card"><p><b>Email:</b> {{ c.email }}<br><b>Role:</b> {{ c.role }}<br><b>Stage:</b> {{ c.stage }}<br><b>Interview:</b> {{ c.interview or 'Not scheduled' }}<br><b>Notes:</b> {{ c.notes }}</p></div>
<form class="card" method="post" action="/ats/candidates/{{ c.id }}/stage"><h3>Update stage</h3>
<label for="stage">Stage</label><select id="stage" name="stage">{% for s in stages %}<option{% if c.stage == s %} selected{% endif %}>{{ s }}</option>{% endfor %}</select>
<label for="notes">Screening notes</label><textarea id="notes" name="notes">{{ c.notes }}</textarea>
<br><button type="submit">Save stage</button></form>
<form class="card" method="post" action="/ats/candidates/{{ c.id }}/schedule"><h3>Schedule screening call</h3>
<label for="slot">Available slot</label><select id="slot" name="slot"><option value="">-- choose --</option>{% for s in free_slots %}<option value="{{ s.id }}">{{ s.label }}</option>{% endfor %}</select>
<br><button type="submit">Schedule interview</button></form>
<a href="/ats">Back to candidates</a>
{% endblock %}"""

ATS_SLOTS = r"""{% extends "base" %}{% block body %}
<table><tr><th>Slot</th><th>Status</th></tr>
{% for s in slots %}<tr><td>{{ s.label }}</td><td>{% if s.taken_by %}Booked: {{ s.taken_by }}{% else %}Free{% endif %}</td></tr>{% endfor %}</table>
{% endblock %}"""

ERROR_500 = r"""{% extends "base" %}{% block body %}
<div class="error" role="alert"><b>{{ code }} {{ reason }}</b><br>{{ message }}</div>
<a href="/erp/bills">Go to bills</a>
{% endblock %}"""

TEMPLATES = {
    "base": BASE, "mail_list": MAIL_LIST, "mail_view": MAIL_VIEW, "erp_home": ERP_HOME, "erp_bills": ERP_BILLS,
    "erp_new": ERP_NEW, "erp_vendors": ERP_VENDORS, "erp_vendor_edit": ERP_VENDOR_EDIT, "jobs_list": JOBS_LIST,
    "job_view": JOB_VIEW, "applicant_view": APPLICANT_VIEW, "ats_list": ATS_LIST, "ats_new": ATS_NEW, "ats_view": ATS_VIEW,
    "ats_slots": ATS_SLOTS, "error_page": ERROR_500,
}
