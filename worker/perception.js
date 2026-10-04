// Snapshot the page into numbered interactive elements + readable text.
// Generic: works on any server-rendered page; no app-specific selectors.
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const labelFor = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return clean(l.innerText);
    }
    const wrap = el.closest('label');
    if (wrap) return clean(wrap.innerText);
    if (el.placeholder) return el.placeholder;
    if (el.tagName === 'INPUT' && ['submit', 'button'].includes(el.type)) return el.value;
    return clean(el.innerText || el.title || el.name || '');
  };

  document.querySelectorAll('[data-agent-id]').forEach((el) => el.removeAttribute('data-agent-id'));
  const selector = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [onclick]';
  const forms = Array.from(document.forms);
  const elements = [];
  let id = 1;
  for (const el of document.querySelectorAll(selector)) {
    if (!visible(el) || el.disabled) continue;
    el.setAttribute('data-agent-id', String(id));
    const tag = el.tagName.toLowerCase();
    const item = { id, tag, label: clean(labelFor(el)).slice(0, 120) };
    if (tag === 'input') { item.type = el.type; item.value = el.value; }
    if (tag === 'textarea') item.value = el.value;
    if (tag === 'select') {
      item.options = Array.from(el.options).map((o) => clean(o.text)).slice(0, 40);
      item.value = el.selectedIndex >= 0 ? clean(el.options[el.selectedIndex].text) : '';
    }
    if (tag === 'a') item.href = el.getAttribute('href');
    if (tag === 'button' || (tag === 'input' && ['submit', 'button'].includes(el.type))) {
      item.submit = !!el.form && el.type === 'submit';  // <button> defaults to type=submit
      if (item.submit) item.form_method = (el.formMethod || el.form.method || 'get').toLowerCase();
    }
    if (el.form) item.form = forms.indexOf(el.form) + 1;
    elements.push(item);
    id += 1;
  }
  const main = document.querySelector('main') || document.body;
  const alerts = Array.from(document.querySelectorAll('[role=alert],[role=status]')).map((a) => clean(a.innerText));
  return {
    url: location.href,
    title: document.title,
    text: (main.innerText || '').replace(/\n{3,}/g, '\n\n').trim(),
    alerts,
    elements,
  };
}
