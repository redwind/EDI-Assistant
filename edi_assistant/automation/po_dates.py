"""Ship-date ladder: DOM text -> PDF (pypdf) -> AI vision -> ask the user."""
from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import pypdf
from playwright.sync_api import Error as PlaywrightError

from edi_assistant.core.dates import parse_date_token, parse_ship_dates
from edi_assistant.core.errors import PostconditionFailed
from edi_assistant.core.events import InputField
from edi_assistant.core.models import DateWindow

from .dom_snapshot import capture

if TYPE_CHECKING:
    from .flow.context import FlowContext

_URL_JS = "[...document.querySelectorAll('a[href],iframe[src],embed[src],object[data]')].map(e => e.href || e.src || e.data)"


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _pdf_urls(ctx: "FlowContext") -> list[str]:
    page = ctx.page
    out: list[str] = []
    loc = ctx.resolver.try_resolve(page, "po.pdf_embed", ctx.vars(), timeout_ms=300)
    if loc is not None:
        for attr in ("src", "data"):
            try:
                v = loc.get_attribute(attr)
            except PlaywrightError:
                v = None
            if v:
                out.append(urljoin(page.url, v))
    try:
        out += [u for u in page.evaluate(_URL_JS) if u and re.search(r"pdf|servlet", u, re.I)]
    except PlaywrightError:
        pass
    uniq: list[str] = []
    for u in out:
        if u not in uniq and "asn.do" not in u:
            uniq.append(u)
    return uniq[:3]


def _read_pdf(ctx: "FlowContext") -> DateWindow | None:
    for url in _pdf_urls(ctx):
        try:
            resp = ctx.page.request.get(url)
            body = resp.body()
            ctype = resp.headers.get("content-type", "")
            if not (resp.ok and (ctype.startswith("application/pdf") or body.startswith(b"%PDF"))):
                continue
            reader = pypdf.PdfReader(io.BytesIO(body))
            text = " ".join((p.extract_text() or "") for p in reader.pages[:3])
            w = parse_ship_dates(_collapse(text))
            if w is not None:
                return w
        except Exception as ex:   # corrupt pdf / network: try next rung
            ctx.log.debug("pdf rung failed for %s: %s", url, ex)
    return None


def read_pdf_window(ctx: "FlowContext") -> DateWindow | None:
    return _read_pdf(ctx)


def read_po_dates(ctx: "FlowContext", po_line_id: str) -> tuple[DateWindow, str]:
    """Returns (window, source) with source in {'dom','pdf','ai','user'}."""
    try:
        w = parse_ship_dates(_collapse(ctx.actions.body_text()))
    except PlaywrightError:
        w = None
    if w is not None:
        return w, "dom"
    w = _read_pdf(ctx)
    if w is not None:
        return w, "pdf"
    if ctx.healer.can_call() and ctx.config.ai.vision:
        snap = capture(ctx.session, ctx.run_dir, f"dates_{po_line_id}")
        w = ctx.healer.read_dates(snap)
        if w is not None:
            return w, "ai"
    for _ in range(3):
        resp = ctx.ask(
            "dates_needed",
            f"Could not read the ship dates of PO {po_line_id}. Look at the PO page in the browser and enter the Early/Late Ship Date.",
            options=["continue", "abort"],
            input_fields=[InputField("early_ship_date", "Early Ship Date (e.g. 09-MAR-26 or 03/09/2026)"),
                          InputField("late_ship_date", "Late Ship Date")])
        a = parse_date_token(resp.values.get("early_ship_date", ""))
        b = parse_date_token(resp.values.get("late_ship_date", ""))
        if a and b:
            return DateWindow(min(a, b), max(a, b)), "user"
    raise PostconditionFailed(f"dates for {po_line_id} not available", message_vi=f"No ship dates available for PO {po_line_id}",
                              step_id="S3.read_dates")
