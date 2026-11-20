"""Page snapshot for AI/healing: aria tree, simplified DOM, screenshot (with redaction)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from .session import BrowserSession

LIMIT = 12_000
EMAIL_RE = re.compile(r"\S+@\S+")


@dataclass(slots=True)
class PageSnapshot:
    url: str = ""
    title: str = ""
    aria: str = ""
    dom: str = ""
    screenshot_path: str = ""
    screenshot_jpeg: bytes = b""


SIMPLIFY_JS = r"""() => {
  const out = []; const SEL = 'a,button,input,select,textarea,label,th,h1,h2,h3,[role],tr';
  const esc = s => (s||'').replace(/\s+/g,' ').trim().slice(0,60).replace(/\S+@\S+/g,'[redacted]');
  const hidden = e => e.offsetParent === null && e.tagName !== 'OPTION' && e.tagName !== 'BODY' && getComputedStyle(e).position !== 'fixed';
  const walk = (el, depth) => {
    if (out.length >= 2000) return;
    for (const c of el.children) {
      let next = depth;
      if (c.matches(SEL) && !hidden(c)) {
        if (c.tagName === 'TR' && !c.querySelector('input,select,a')) { walk(c, depth); continue; }
        const t = c.tagName.toLowerCase(); let a = '';
        for (const k of ['id','name','type','role']) if (c.getAttribute(k)) a += ` ${k}="${c.getAttribute(k)}"`;
        let v = c.value;
        if (typeof v === 'string' && v !== '') { if (c.type === 'password') v = '[redacted]'; a += ` value="${esc(v)}"`; }
        out.push('  '.repeat(Math.min(depth,10)) + `<${t}${a} text="${esc(c.innerText)}">`);
        next = depth + 1;
      }
      walk(c, next);
    }
  };
  walk(document.body, 0);
  return out.join('\n');
}"""


def capture(session: BrowserSession, run_dir: Path, tag: str, with_image: bool = True) -> PageSnapshot:
    """Never raises; failing parts are left empty."""
    snap = PageSnapshot()
    try:
        page = session.page
        snap.url, snap.title = page.url, page.title()
    except Exception:
        return snap
    try:
        snap.aria = EMAIL_RE.sub("[redacted]", page.locator("body").aria_snapshot())[:LIMIT]
    except Exception:
        pass
    try:
        snap.dom = str(page.evaluate(SIMPLIFY_JS))[:LIMIT]
    except Exception:
        pass
    if with_image:
        try:
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag)
            path = Path(run_dir) / "shots" / f"{time.strftime('%H%M%S')}_{safe}.jpg"
            snap.screenshot_jpeg = session.screenshot_jpeg(path)
            snap.screenshot_path = str(path)
        except Exception:
            pass
        try:   # full page HTML next to the screenshot (emails redacted), for fixing selectors on the real site
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tag)
            html = Path(run_dir) / "shots" / f"{time.strftime('%H%M%S')}_{safe}.html"
            html.parent.mkdir(parents=True, exist_ok=True)
            html.write_text(EMAIL_RE.sub("[redacted]", page.content()), encoding="utf-8")
        except Exception:
            pass
    return snap
