/* Acme Workforce console: shared nav, helpers, icons and the decision-card component. Vanilla JS, no build. */
(function () {
  const W = window.WF = {};
  const INR_PER_USD = 84;

  // ---------- theme ----------
  W.theme = () => document.documentElement.dataset.theme || 'dark';
  W.setTheme = t => { document.documentElement.dataset.theme = t; try { localStorage.setItem('wf-theme', t); } catch (e) {} };

  // ---------- helpers ----------
  W.$ = s => document.querySelector(s);
  W.$$ = s => [...document.querySelectorAll(s)];
  W.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  W.short = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
  W.plain = s => String(s ?? '').replace(/\*\*|__|^#+\s*/gm, '');
  W.initials = n => String(n || '?').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase();
  W.usd = v => v == null ? '—' : '$' + Number(v).toFixed(v < 1 ? 3 : 2);
  W.inr = v => v == null ? '' : '≈₹' + (v * INR_PER_USD).toFixed(v * INR_PER_USD < 10 ? 1 : 0);
  W.money = v => v == null ? '—' : `${W.usd(v)} <span class="muted">${W.inr(v)}</span>`;
  W.dur = s => { if (s == null) return '—'; const t = Math.round(s); return t < 60 ? `${t}s` : `${Math.floor(t/60)}m ${String(t%60).padStart(2,'0')}s`; };
  W.ago = ts => { if (!ts) return '—'; const s = Date.now()/1000 - ts; if (s < 60) return 'just now'; if (s < 3600) return `${Math.floor(s/60)}m ago`;
    if (s < 86400) return `${Math.floor(s/3600)}h ago`; return new Date(ts*1000).toLocaleDateString([], {day:'2-digit', month:'short'}); };
  W.clock = (ts) => new Date((ts || Date.now()/1000) * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  W.inrAmount = v => { const n = Number(String(v).replace(/[,\s₹]|INR/gi, '')); if (!isFinite(n) || n <= 0) return null;
    return '₹' + n.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}); };
  W.json = async (url, opts) => { const r = await fetch(url, opts); if (!r.ok) throw new Error(r.status); return r.json(); };
  W.post = (url, body) => W.json(url, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body || {})});

  // ---------- icons (inline SVG, currentColor) ----------
  const P = {
    check: '<path d="M4 10.5l3.5 3.5L16 6"/>', x: '<path d="M5 5l10 10M15 5L5 15"/>',
    users: '<circle cx="7.5" cy="7" r="3"/><path d="M2 17c.6-3 2.8-4.5 5.5-4.5S12.4 14 13 17"/><path d="M13 4.2a3 3 0 010 5.6M15 12.8c1.6.6 2.6 2 3 4.2"/>',
    inbox: '<path d="M3 11l2.2-6.2A1.5 1.5 0 016.6 4h6.8a1.5 1.5 0 011.4.8L17 11v4.5a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 013 15.5z"/><path d="M3 11h4l1 2h4l1-2h4"/>',
    log: '<path d="M6 4h10M6 10h10M6 16h10"/><circle cx="3" cy="4" r=".6"/><circle cx="3" cy="10" r=".6"/><circle cx="3" cy="16" r=".6"/>',
    grid: '<rect x="3" y="3" width="5.5" height="5.5" rx="1.2"/><rect x="11.5" y="3" width="5.5" height="5.5" rx="1.2"/><rect x="3" y="11.5" width="5.5" height="5.5" rx="1.2"/><rect x="11.5" y="11.5" width="5.5" height="5.5" rx="1.2"/>',
    sun: '<circle cx="10" cy="10" r="3.5"/><path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2M4 4l1.4 1.4M14.6 14.6L16 16M4 16l1.4-1.4M14.6 5.4L16 4"/>',
    moon: '<path d="M16.5 12.5A7 7 0 017.5 3.5a7 7 0 109 9z"/>',
    arrow: '<path d="M4 10h12M11 5l5 5-5 5"/>', ext: '<path d="M8 4H4v12h12v-4M11 3h6v6M17 3l-8 8"/>',
    plus: '<path d="M10 4v12M4 10h12"/>', shield: '<path d="M10 2l6.5 2.5v5c0 4-2.8 7-6.5 8.5C6.3 16.5 3.5 13.5 3.5 9.5v-5z"/><path d="M7 10l2 2 4-4"/>',
    hand: '<path d="M7 10V4.5a1.2 1.2 0 012.4 0V9M9.4 9V3.5a1.2 1.2 0 012.4 0V9M11.8 9V4.5a1.2 1.2 0 012.4 0v6.5c0 3.5-2.2 6-5.4 6-2.3 0-3.6-1-4.8-3L2.5 11a1.2 1.2 0 012-1.2L7 12.5"/>',
    spark: '<path d="M10 2.5l1.8 4.7 4.7 1.8-4.7 1.8L10 15.5l-1.8-4.7L3.5 9l4.7-1.8z"/>',
    chev: '<path d="M6 8l4 4 4-4"/>', bolt: '<path d="M11 2L4 11h5l-1 7 7-9h-5z"/>', lock: '<rect x="4" y="9" width="12" height="8" rx="1.5"/><path d="M7 9V6.5a3 3 0 016 0V9"/>',
    book: '<path d="M4 3.5h8.5a2 2 0 012 2V17H6a2 2 0 01-2-2z"/><path d="M4 15a2 2 0 012-2h8.5"/>',
    question: '<circle cx="10" cy="10" r="7.5"/><path d="M7.8 7.8a2.3 2.3 0 114 1.6c-.8.6-1.8 1-1.8 2.1M10 14.2v.1"/>',
    brain: '<path d="M7.5 3.5a2.5 2.5 0 00-2.5 2.5 2.5 2.5 0 00-1.5 4.3A2.8 2.8 0 006 15a2.5 2.5 0 004 1V4.6a2.5 2.5 0 00-2.5-1.1zM12.5 3.5A2.5 2.5 0 0115 6a2.5 2.5 0 011.5 4.3A2.8 2.8 0 0114 15a2.5 2.5 0 01-4 1"/>',
  };
  W.icon = (n, size = 16, sw = 1.7) => `<svg width="${size}" height="${size}" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || ''}</svg>`;

  // ---------- avatar / outcome ----------
  W.avatar = (r, cls = '', status) => {
    const name = r?.name || r?.role_name || '?';
    const hue = r?.avatar_hue ?? 220;
    return `<span class="av ${cls}" style="--h:${hue}" aria-hidden="true">${W.esc(W.initials(name))}${status ? `<i class="st ${status}"></i>` : ''}</span>`;
  };
  const OUT = {
    working: ['info', 'Working', true], needs_you: ['warn', 'Needs you', true], verified: ['ok', 'Verified'],
    escalated: ['amber', 'Escalated'], unverified: ['err', 'Not verified'], failed: ['err', 'Failed'], abandoned: ['neutral', 'Abandoned'],
  };
  W.outcome = (o) => { const [c, l, p] = OUT[o] || ['neutral', o];
    return `<span class="badge ${c}"${o === 'escalated' ? ' title="Stopped for a human by design"' : ''}>${p ? '<i class="dot pulse"></i>' : o === 'verified' ? W.icon('check', 12, 2.4) : '<i class="dot"></i>'}${l}</span>`; };

  // ---------- roles ----------
  let rolesP = null;
  W.roles = (fresh) => { if (!rolesP || fresh) rolesP = W.json('/api/roles').catch(() => []); return rolesP; };
  W.roleMap = async () => Object.fromEntries((await W.roles()).map(r => [r.id, r]));

  // ---------- nav ----------
  W.nav = (active) => {
    const el = document.getElementById('nav'); if (!el) return;
    const a = (href, key, ic, label, extra = '') => `<a href="${href}" class="${active === key ? 'on' : ''}"${active === key ? ' aria-current="page"' : ''}>${W.icon(ic)}<span class="lbl">${label}</span>${extra}</a>`;
    el.className = 'topnav';
    el.innerHTML = `
      <a class="brand" href="/runs" aria-label="Acme Workforce home"><span class="mark">${W.icon('spark', 17, 1.9)}</span>
        <span><b>Acme Workforce</b><span class="sub">AI employees · Acme Logistics</span></span></a>
      <nav class="navlinks" aria-label="Main">
        ${a('/runs', 'workforce', 'users', 'Workforce')}
        ${a('/inbox', 'inbox', 'inbox', 'Inbox', '<span class="count" id="inboxCount" hidden></span>')}
        ${a('/employees/all', 'audit', 'log', 'Audit log')}
        <details class="menu"><summary>${W.icon('grid')}<span class="lbl">Systems</span>${W.icon('chev', 14)}</summary>
          <div class="menu-pop" role="menu">
            <a href="/mail" target="_blank" rel="noopener">AcmeMail<span>Company email · /mail</span></a>
            <a href="/erp/bills" target="_blank" rel="noopener">Ledgerly ERP<span>Bills &amp; vendor master · /erp</span></a>
            <a href="/jobs" target="_blank" rel="noopener">HireHub<span>External job portal · /jobs</span></a>
            <a href="/ats" target="_blank" rel="noopener">TalentDesk<span>Applicant tracking · /ats</span></a>
          </div></details>
      </nav>
      <div class="navright"><button class="iconbtn" id="themeBtn" aria-label="Toggle light and dark theme"></button></div>`;
    const tb = document.getElementById('themeBtn');
    const paint = () => { tb.innerHTML = W.icon(W.theme() === 'dark' ? 'sun' : 'moon', 17); tb.title = W.theme() === 'dark' ? 'Light theme' : 'Dark theme'; };
    tb.onclick = () => { W.setTheme(W.theme() === 'dark' ? 'light' : 'dark'); paint(); }; paint();
    document.addEventListener('click', e => W.$$('details.menu[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; }));
    const poll = async () => { try { const r = await W.json('/api/inbox'); const c = document.getElementById('inboxCount');
      c.textContent = r.count; c.hidden = !r.count; W.inboxCount = r.count; document.dispatchEvent(new CustomEvent('wf:inbox', {detail: r})); } catch (e) {} };
    poll(); setInterval(poll, 4000);
  };

  // ---------- decision card ----------
  // item: {type:'approval'|'question'|'learning', id, run_id, role, role_name, request, question, options, rule, applies_to, reason, approver_display, goal, created}
  W.decisionCard = (it, role) => {
    role = role || {name: it.role_name || 'Your AI employee', avatar_hue: 220};
    const name = W.esc(role.name);
    const key = `${it.type}:${it.run_id || ''}:${it.id}`;
    const when = it.created ? (typeof it.created === 'number' ? W.ago(it.created) : W.esc(String(it.created).slice(0, 16).replace('T', ' '))) : '';
    const runLink = it.run_id ? `<a href="/runs/${encodeURIComponent(it.run_id)}">${W.esc(W.short(it.goal || it.run_id, 70))}</a>` : '';
    const head = (title, tone) => `<div class="dc-head">${W.avatar(role, 'l')}<div class="grow" style="min-width:0"><div class="t">${title}</div>
      <div class="m">${[runLink, when].filter(Boolean).join(' · ')}</div></div>${tone}</div>`;
    if (it.type === 'approval') {
      const r = it.request || {};
      const vals = Object.entries(r.values || {}).filter(([, v]) => String(v ?? '').trim() !== '');
      const amtEntry = vals.find(([k, v]) => /amount|total|payable/i.test(k) && W.inrAmount(v));
      const act = String(r.action || 'Continue').replace(/^Click\s+/i, '').replace(/"([^"]+)"\s+in\s+(\w+)/, (m, b, app) => `“${b}” in ${app.toUpperCase() === 'ERP' ? 'Ledgerly ERP' : app}`);
      const big = `${W.esc(act)}${amtEntry ? ` <span class="muted">for</span> <span class="amt">${W.inrAmount(amtEntry[1])}</span>` : ''}`;
      return `<article class="decision approval" data-key="${W.esc(key)}" data-type="approval" data-id="${W.esc(it.id)}" data-run="${W.esc(it.run_id)}">
        ${head(`${name} is asking for approval`, '<span class="badge warn"><i class="dot pulse"></i>Approval needed</span>')}
        <div class="dc-body"><div class="dc-big">${big}</div>
          ${r.why_needed || r.details ? `<p class="dc-why">${W.esc(r.why_needed || r.details)}</p>` : ''}
          ${vals.length ? `<dl class="kv">${vals.map(([k, v]) => `<dt>${W.esc(k)}</dt><dd>${W.esc(v)}</dd>`).join('')}</dl>` : ''}
          <div class="rulebar">${r.policy_rule ? `<span class="row" style="gap:6px">${W.icon('lock', 14)}Rule <span class="tag mono">${W.esc(r.policy_rule)}</span></span>` : '<span>Requested by the employee</span>'}
            ${it.approver_display ? `<span>Approver: <b style="color:var(--text)">${W.esc(it.approver_display)}</b></span>` : ''}
            ${r.url ? `<span class="mono faint">${W.esc(String(r.url).replace(/^https?:\/\/[^/]+/, ''))}</span>` : ''}</div>
          ${r.agent_note ? `<p class="small muted">Note from ${name}: ${W.esc(r.agent_note)}</p>` : ''}
        </div>
        <div class="dc-foot"><label class="sr" for="n-${W.esc(it.id)}">Note</label><input type="text" id="n-${W.esc(it.id)}" data-note placeholder="Add a note for the audit trail">
          <button class="btn danger" data-act="deny">${W.icon('x', 14, 2)}Deny</button>
          <button class="btn ok" data-act="approve">${W.icon('check', 14, 2.2)}Approve and continue</button></div></article>`;
    }
    if (it.type === 'question') {
      const opts = (it.options || []).map(o => `<button class="chip" data-opt="${W.esc(o)}">${W.esc(o)}</button>`).join('');
      return `<article class="decision question" data-key="${W.esc(key)}" data-type="question" data-id="${W.esc(it.id)}" data-run="${W.esc(it.run_id)}">
        ${head(`${name} needs information`, '<span class="badge info"><i class="dot pulse"></i>Question</span>')}
        <div class="dc-body"><div class="dc-big" style="font-size:17px;font-weight:600">${W.esc(it.question)}</div>${opts ? `<div class="chips">${opts}</div>` : ''}</div>
        <div class="dc-foot"><label class="sr" for="a-${W.esc(it.id)}">Answer</label><input type="text" id="a-${W.esc(it.id)}" data-answer placeholder="Your answer">
          <button class="btn primary" data-act="send">Send ${W.icon('arrow', 14, 2)}</button></div></article>`;
    }
    return `<article class="decision learning" data-key="${W.esc(key)}" data-type="learning" data-id="${W.esc(it.id)}">
      ${head(`${name} wants to learn a rule`, '<span class="badge accent">' + W.icon('brain', 13) + 'Company memory</span>')}
      <div class="dc-body"><div class="quote">“${W.esc(it.rule)}”</div>
        <dl class="kv">${it.applies_to ? `<dt>Applies to</dt><dd>${W.esc(Array.isArray(it.applies_to) ? it.applies_to.join(', ') : it.applies_to)}</dd>` : ''}
          ${it.reason ? `<dt>Why</dt><dd>${W.esc(it.reason)}</dd>` : ''}
          ${it.run_id ? `<dt>Learned from</dt><dd><a href="/runs/${encodeURIComponent(it.run_id)}" class="mono">${W.esc(it.run_id)}</a></dd>` : ''}</dl>
        <p class="small muted">Once added, this rule is shown to ${name} on every future task and appears on the role definition.</p></div>
      <div class="dc-foot"><span class="grow"></span><button class="btn danger" data-act="reject">Reject</button>
        <button class="btn primary" data-act="accept">${W.icon('plus', 14, 2.2)}Add to company memory</button></div></article>`;
  };

  W.doneRow = (label, ok = true) => `<div class="dc-done ${ok ? '' : 'no'}" role="status"><span class="ic">${W.icon(ok ? 'check' : 'x', 13, 2.4)}</span>
    <span>${label} · <span class="tnum">${W.clock()}</span> · logged to the audit trail</span></div>`;

  // Wire up all decision cards inside root. onDone(key, label) is called after a successful response.
  W.bindDecisions = (root, onDone) => {
    root.querySelectorAll('article.decision:not([data-bound])').forEach(card => {
      card.dataset.bound = '1';
      const {type, id, run} = card.dataset;
      const finish = (label, ok) => { const html = W.doneRow(label, ok); card.outerHTML = html; onDone && onDone(card.dataset.key, label, ok); };
      const fail = (btn) => { btn.disabled = false; card.classList.add('shake'); setTimeout(() => card.classList.remove('shake'), 400); };
      card.querySelectorAll('[data-opt]').forEach(b => b.onclick = () => { card.querySelector('[data-answer]').value = b.dataset.opt; });
      const ans = card.querySelector('[data-answer]');
      if (ans) ans.addEventListener('keydown', e => { if (e.key === 'Enter') card.querySelector('[data-act=send]').click(); });
      card.querySelectorAll('[data-act]').forEach(btn => btn.onclick = async () => {
        const act = btn.dataset.act; btn.disabled = true;
        try {
          if (type === 'approval') {
            const note = card.querySelector('[data-note]').value.trim();
            await W.post(`/runs/${encodeURIComponent(run)}/respond`, {id, approved: act === 'approve', note: note || (act === 'approve' ? 'Approved in the console' : 'Denied in the console')});
            finish(act === 'approve' ? 'Approved by you' : 'Denied by you', act === 'approve');
          } else if (type === 'question') {
            const a = ans.value.trim(); if (!a) { fail(btn); ans.focus(); return; }
            await W.post(`/runs/${encodeURIComponent(run)}/respond`, {id, answer: a});
            finish(`Answered by you: “${W.esc(W.short(a, 60))}”`, true);
          } else {
            await W.post(`/api/learning/${encodeURIComponent(id)}/${act}`);
            finish(act === 'accept' ? 'Added to company memory by you' : 'Rule rejected by you', act === 'accept');
          }
        } catch (e) { fail(btn); }
      });
    });
  };
})();
