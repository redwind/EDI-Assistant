(() => {
  if (window.__ediPickerLoaded) return;
  window.__ediPickerLoaded = true;
  const q = (s) => document.querySelectorAll(s).length;
  const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const attrEsc = (s) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

  function accName(el) {
    const tag = el.tagName.toLowerCase();
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    if (tag === 'input' && ['button', 'submit', 'reset'].includes((el.type || '').toLowerCase())) return clean(el.value);
    if (el.id) { const l = document.querySelector('label[for="' + attrEsc(el.id) + '"]'); if (l) return clean(l.textContent); }
    if (tag === 'a' || tag === 'button') return clean(el.textContent);
    return '';
  }
  function roleOf(el) {
    const tag = el.tagName.toLowerCase(), t = (el.type || '').toLowerCase();
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'button' || (tag === 'input' && ['button', 'submit', 'reset'].includes(t))) return 'button';
    if (tag === 'textarea' || (tag === 'input' && ['text', 'search', 'email', 'tel', 'url', ''].includes(t))) return 'textbox';
    if (tag === 'select') return 'combobox';
    return '';
  }
  function labelXpath(el) {
    let lab = '';
    if (el.id) { const l = document.querySelector('label[for="' + attrEsc(el.id) + '"]'); if (l) lab = clean(l.textContent); }
    if (!lab) {
      let n = el.previousSibling;
      while (n && !lab) { lab = clean(n.textContent); n = n.previousSibling; }
      if (!lab && el.parentElement) { const p = el.parentElement.previousElementSibling; if (p) lab = clean(p.textContent); }
    }
    if (!lab || lab.length > 60) return null;
    const tag = el.tagName.toLowerCase();
    return "//*[normalize-space()='" + lab.replace(/'/g, '') + "']/following::" + tag + "[1]";
  }
  function cssPath(el) {
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && parts.length < 6 && n !== document.documentElement) {
      let i = 1, s = n;
      while ((s = s.previousElementSibling)) i++;
      parts.unshift(n.tagName.toLowerCase() + ':nth-child(' + i + ')');
      n = n.parentElement;
    }
    return parts.join(' > ');
  }
  function candidates(el) {
    const out = [], tag = el.tagName.toLowerCase();
    if (el.id && !/^\d+$/.test(el.id) && q('#' + cssEsc(el.id)) === 1) out.push({kind: 'css', css: '#' + cssEsc(el.id)});
    const name = el.getAttribute('name');
    if (name) {
      const sel = tag + '[name="' + attrEsc(name) + '"]';
      if (q(sel) === 1) out.push({kind: 'css', css: sel});
    }
    const role = roleOf(el), nm = accName(el);
    if (role && nm) out.push({kind: 'role', role: role, name: nm, exact: true});
    if (tag === 'input' && el.value && ['button', 'submit', 'reset'].includes((el.type || '').toLowerCase())) {
      out.push({kind: 'css', css: 'input[value="' + attrEsc(el.value) + '"]'});
    }
    const lx = labelXpath(el);
    if (lx) out.push({kind: 'xpath', xpath: lx});
    out.push({kind: 'css', css: cssPath(el)});
    return out;
  }
  window.__ediCandidates = candidates;
  // Same shape as actions._ATTRS_JS so Python can apply the forbidden-element guard without a round trip.
  function elementInfo(el) {
    const grab = e => e ? ({name: e.name || '', id: e.id || '', value: (typeof e.value === 'string' ? e.value : '') || '',
      text: (e.innerText || e.textContent || '').trim().slice(0, 200), onclick: (e.getAttribute('onclick') || '')}) : null;
    return [grab(el), grab(el.closest('button,a,input[type=submit],input[type=button]'))];
  }
  window.__ediElementInfo = elementInfo;

  let banner = null, hover = null, handlers = null;
  function stop() {
    if (handlers) {
      document.removeEventListener('click', handlers.click, true);
      document.removeEventListener('mouseover', handlers.over, true);
      document.removeEventListener('keydown', handlers.key, true);
      handlers = null;
    }
    if (hover) { hover.style.outline = hover.__ediOutline || ''; hover = null; }
    if (banner) { banner.remove(); banner = null; }
  }
  window.__ediPickerCancel = stop;
  window.__ediPickerStart = (key) => {
    stop();
    banner = document.createElement('div');
    banner.textContent = 'Click the element for: ' + key + ' (Esc to cancel)';
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;background:#ff3b30;color:#fff;' +
      'font:14px Arial;padding:6px 10px;text-align:center;pointer-events:none';
    document.documentElement.appendChild(banner);
    handlers = {
      over: (e) => {
        if (hover) hover.style.outline = hover.__ediOutline || '';
        hover = e.target; hover.__ediOutline = hover.style.outline; hover.style.outline = '2px solid #ff3b30';
      },
      click: (e) => {
        e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
        const el = e.target, c = candidates(el), info = elementInfo(el);
        const pw = el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'password';
        stop();
        if (window.__ediPicked) window.__ediPicked({candidates: c, element: info, password: pw});
      },
      key: (e) => { if (e.key === 'Escape') { stop(); if (window.__ediPicked) window.__ediPicked({candidates: []}); } },
    };
    document.addEventListener('mouseover', handlers.over, true);
    document.addEventListener('click', handlers.click, true);
    document.addEventListener('keydown', handlers.key, true);
  };
})();
