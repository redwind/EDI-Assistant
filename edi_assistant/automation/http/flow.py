"""Direct-HTTP version of the shipment steps (header -> POs -> cartons + Partial -> weights).

Each step fetches the same page the browser would show, builds the form exactly as the browser submits it
(see forms.py; verified against a recorded real run) and posts it with the browser's own login session
(BrowserContext.request shares the cookies). Every response is parsed and checked. Anything unexpected
raises HttpFallback: the runner then opens that page in the browser and finishes the shipment with the
normal (UI) steps. Validate Shipment and Submit ASN are never sent.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import Error as PlaywrightError

from edi_assistant.core.dates import format_mdy
from edi_assistant.core.dc_sites import pick_option
from edi_assistant.core.errors import EdiAssistantError, ForbiddenActionError
from edi_assistant.core.events import ShipmentCreated
from edi_assistant.core.models import PlannedLine
from edi_assistant.core.quantities import decide_carton

from .forms import Form, get_form, title_of
from .rows import Row, page_errors, table_rows

if TYPE_CHECKING:
    from ..flow.context import FlowContext

TIMEOUT_MS = 90_000
ALLOWED_PAGES = {"new_shipment.do", "search_po.do", "selected_pos.do", "search_items.do", "search_sites.do",
                 "customized_qty_cartons.do", "po_site_shipment.do"}
_FORBIDDEN_NAMES = re.compile(r"submitasn|btnsubmitasn|validateshipment|cancelshipment|btncancel", re.I)
_FORBIDDEN_ACTIONS = re.compile(r"^(remove|delete|cancel|validate|submit)", re.I)
HEADER_REQUIRED = ("txtShippingDate,OptShippingType,OptSCACCode,OptTransMethod,txtFromName,txtFromAddress1,"
                   "txtFromCity,txtFromZip,txtFromState,optToSiteNo,txtFromCountry")


class HttpFallback(EdiAssistantError):
    """Direct mode cannot continue safely; ctx: url (page to open in the browser), stage."""
    code = "http_fallback"


@dataclass
class Page:
    url: str
    status: int
    html: str
    ms: int

    @property
    def title(self) -> str:
        return title_of(self.html)

    def form(self, name: str | None = None) -> Form:
        try:
            return get_form(self.html, name)
        except LookupError:
            raise HttpFallback(f"form {name!r} missing on {self.url}", message_vi="The page did not look as expected",
                               url=self.url) from None


FETCH_JS = """async ({url, method, body, timeout}) => {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const opts = {method, credentials: 'include', redirect: 'follow', signal: ctl.signal};
    if (body !== null) {
      opts.body = body;
      opts.headers = {'Content-Type': 'application/x-www-form-urlencoded'};
    }
    const r = await fetch(url, opts);
    const buf = await r.arrayBuffer();
    const m = /charset=([^;]+)/i.exec(r.headers.get('content-type') || '');
    let text;
    try { text = new TextDecoder(m ? m[1].trim() : 'windows-1252').decode(buf); }
    catch (e) { text = new TextDecoder('windows-1252').decode(buf); }
    return {url: r.url, status: r.status, text};
  } finally { clearTimeout(timer); }
}"""


class _Resp:
    def __init__(self, d: dict):
        self.url, self.status, self._text = d["url"], d["status"], d["text"]

    def text(self) -> str:
        return self._text


class HttpClient:
    """Requests are sent with fetch() inside the browser page: same connection, certificates and login as the
    browser (Playwright's own request client rejects the site's incomplete certificate chain)."""

    def __init__(self, ctx: "FlowContext"):
        self.ctx = ctx
        self.page = ctx.session.page
        self.base = ctx.base("gateway/")
        self.last_url = self.base + "selected_pos.do"

    def _fetch(self, method: str, url: str, body: str | None) -> _Resp:
        return _Resp(self.page.evaluate(FETCH_JS, {"url": url, "method": method, "body": body, "timeout": TIMEOUT_MS}))

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else self.base + path

    @staticmethod
    def _guard(url: str, pairs: list[tuple[str, str]]) -> None:
        page = urlsplit(url).path.rsplit("/", 1)[-1]
        if page not in ALLOWED_PAGES:
            raise ForbiddenActionError(f"direct mode: page {page} not allowed", message_vi="Not allowed")
        for k, v in pairs + [(k, v[0]) for k, v in parse_qs(urlsplit(url).query).items()]:
            if _FORBIDDEN_NAMES.search(k) or (k == "action" and _FORBIDDEN_ACTIONS.match(v or "")) \
                    or re.search(r"submit\s*asn|validate", v or "", re.I):
                raise ForbiddenActionError(f"direct mode refused {k}={v}", message_vi="The tool never sends this")

    def _call(self, fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except PlaywrightError as ex:   # network / timeout: hand over to the browser steps
            raise HttpFallback(f"network: {str(ex).splitlines()[0] if str(ex) else ex}",
                               message_vi="The site did not answer", url=self.last_url) from ex

    def _done(self, resp, t0: float, what: str) -> Page:
        page = Page(resp.url, resp.status, resp.text(), round((time.monotonic() - t0) * 1000))
        self.ctx.debug(f"http {what} -> {page.status} {page.url} ({page.ms} ms)")
        if page.status >= 400:
            raise HttpFallback(f"{what}: HTTP {page.status}", message_vi=f"The site answered {page.status}", url=page.url)
        if "login" in urlsplit(page.url).path.lower() or "-- login" in page.title.lower():
            raise HttpFallback("logged out", message_vi="The EDI session ended (login page)", url=page.url)
        self.last_url = page.url
        return page

    def get(self, path: str, params: list[tuple[str, str]] | None = None) -> Page:
        url = self._url(path)
        if params:
            url += ("&" if "?" in url else "?") + urlencode(params)
        self._guard(url, [])
        t0 = time.monotonic()
        return self._done(self._call(self._fetch, "GET", url, None), t0, f"GET {path}")

    def post(self, path: str, pairs: list[tuple[str, str]]) -> Page:
        url = self._url(path)
        self._guard(url, pairs)
        t0 = time.monotonic()
        resp = self._call(self._fetch, "POST", url, urlencode(pairs, encoding="cp1252", errors="replace"))
        return self._done(resp, t0, f"POST {path}")

    def submit(self, form: Form, pairs: list[tuple[str, str]]) -> Page:
        action = form.action or ""
        if form.method == "get":
            return self.get(action, pairs)
        return self.post(action, pairs)


# ---------------------------------------------------------------- helpers
def _dec(s: str) -> Decimal | None:
    t = re.sub(r"[^\d.\-]", "", (s or "").replace(",", ""))
    try:
        return Decimal(t) if t else None
    except InvalidOperation:
        return None


def _ids(names: list[str], prefix: str) -> list[str]:
    return [n[len(prefix):] for n in names if n.startswith(prefix)]


def _row_for(rows: list[Row], text: str, control_pattern: str) -> Row | None:
    hits = [r for r in rows if r.has_cell(text) and r.control_names(control_pattern)]
    return hits[0] if len(hits) == 1 else None


class HttpShipment:
    """Runs one shipment directly. Statuses on the lines mirror the UI steps."""

    def __init__(self, ctx: "FlowContext"):
        self.ctx = ctx
        self.http = HttpClient(ctx)
        self.sh = ctx.current_shipment
        self.po_ids: dict[str, str] = {}     # PO line id -> poHeaderID (= search checkbox id)
        self.resume = ""                     # page to open in the browser if direct mode stops

    def fail(self, msg: str, page: Page | None = None) -> HttpFallback:
        url = self.resume or (page.url if page is not None else self.http.last_url)
        return HttpFallback(msg, message_vi=msg, url=url)

    # ---------------------------------------------------------------- header
    def header(self, first: PlannedLine) -> None:
        ctx, sh, cfg = self.ctx, self.sh, self.ctx.config.flow
        f = sh.factory
        page = self.http.get("new_shipment.do", [("po_header_id", first.po_line.po_line_id)])
        form = page.form("new_shipment")
        ov: dict[str, str | None] = {"CartonRadio": "Y", "Dirty_Flag": "True", "required": HEADER_REQUIRED,
                                      "AddUpdate": "Update"}
        need = {
            "OptShippingType": form.option_value("OptShippingType", value="3", label=cfg.shipping_type),
            "OptTransMethod": (form.option_value("OptTransMethod", label=f.transport_method, prefix=f.transport_method)
                               if f.transport_method else
                               form.option_value("OptTransMethod", value="O", label=cfg.transportation_method)),
            "OptSCACCode": form.option_value("OptSCACCode", value=f.scac_code or cfg.scac_code,
                                             prefix=f.scac_code or cfg.scac_code),
            "txtFromCountry": form.option_value("txtFromCountry", label=f.country, prefix=f.country[:5]),
        }
        missing = [k for k, v in need.items() if not v]
        if missing:
            raise self.fail(f"no matching option for {', '.join(missing)}", page)
        ov.update(need)
        scac = form.option("OptSCACCode", need["OptSCACCode"])
        ov["txtcarrier"] = scac.text.split("-", 1)[1].strip() if scac and "-" in scac.text else ""
        ov.update({"txtShippingDate": format_mdy(sh.shipping_date), "txtBillLading": cfg.bill_of_lading,
                   "txtPRONumber": cfg.pro_number, "txtFromName": f.name, "txtFromAddress1": f.address1,
                   "txtFromAddress2": f.address2, "txtFromCity": f.city, "txtFromState": f.state, "txtFromZip": f.zip})
        if f.site_no:
            v = form.option_value("OptSiteNO", label=f.site_no, prefix=f.site_no)
            if not v:
                raise self.fail(f"FROM Site No {f.site_no} not in the list", page)
            ov["OptSiteNO"] = v
        to = form.control("optToSiteNo")
        if to is not None and to.tag == "select":
            if not sh.to_site_no:
                raise self.fail("TO Site No unknown (no Delivery Address state)", page)
            val = pick_option([(o.value, o.text) for o in to.options], sh.to_site_no)
            opt = form.option("optToSiteNo", val) if val else None
            if opt is None:
                raise self.fail(f"TO Site No {sh.to_site_no} not in the list", page)
            a = opt.attrs
            ov.update({"optToSiteNo": opt.value, "txtToName": a.get("name11", ""), "txtToAddress1": a.get("address1", ""),
                       "txtToAddress2": a.get("address2", ""), "txtToCity": a.get("city", ""),
                       "txtToState": a.get("state", ""), "txtToZip": a.get("zip", ""),
                       "txtToCountry": a.get("countrycode", ""), "txtToCountryUnHidden": a.get("country", "")})
        saved = self.http.submit(form, form.pairs(ov, ("saveonly", "Save")))
        errs = page_errors(saved.html)
        m = re.search(r"shipment_id=(\d+)", saved.url)
        sf = get_form(saved.html, "new_shipment") if m else None
        wid = (sf.control("txtWebShipmentId").value if sf and sf.control("txtWebShipmentId") else "") or (m.group(1) if m else "")
        if not m or not wid.isdigit():
            raise self.fail("header not saved" + (f": {errs[0]}" if errs else ""), saved)
        aid = (sf.control("txtASNId").value if sf.control("txtASNId") else "") or wid
        sh.web_shipment_id, sh.asn_shipment_id = wid, aid
        tc = sf.control("optToSiteNo")   # what the site stored (a select on new shipments, read-only text otherwise)
        if tc is not None:
            got = (tc.selected_options()[0].value if tc.options else "") if tc.tag == "select" else tc.value
            sh.to_site_no = got.strip() or sh.to_site_no
        ctx.emit(ShipmentCreated(shipment_index=sh.index, web_shipment_id=wid, asn_shipment_id=aid))
        ctx.results.write(ctx.plan)
        ctx.info(f"shipment {sh.index}: header saved, Web Shipment ID {wid} (direct)")
        self.resume = saved.url   # header page: the browser steps continue from "Selected Purchase Orders >>"
        nxt = self.http.submit(sf, sf.pairs({"required": HEADER_REQUIRED, "AddUpdate": "Update"},
                                            ("submit123", "Selected Purchase Orders >>")))
        if "selected_pos.do" not in nxt.url:
            raise self.fail("could not open Selected Purchase Orders", nxt)
        self.resume = ""

    # ---------------------------------------------------------------- POs
    def selected_page(self) -> Page:
        return self.http.get("selected_pos.do", [("webshipmentId", self.sh.web_shipment_id), ("action", "")])

    def _selected_ids(self, page: Page) -> dict[str, str]:
        """PO line id -> poHeaderID for the rows of the Selected Purchase Orders page."""
        out = {}
        for r in table_rows(page.html):
            ids = _ids(r.control_names(r"complete_shipment_\d+"), "complete_shipment_")
            if len(ids) == 1:
                po = next((t for t in r.links if re.fullmatch(r"\d{9}", t)), "")
                if po:
                    out[po] = ids[0]
        return out

    def add_pos(self) -> None:
        sh = self.sh
        want = [ln for ln in sh.lines if ln.status == "pending"]
        if not want:
            return
        page = self.http.get("search_po.do")
        form = page.form("new_shipment")
        res = self.http.submit(form, form.pairs({"PO_NO": "", "status": "", "orderperpage": "100000"},
                                                ("submit", "Search")))
        rows = table_rows(res.html)
        ticks: dict[str, str] = {}
        for ln in want:
            po = ln.po_line.po_line_id
            row = _row_for(rows, po, r"CB_\d+")
            if row is None:   # not on the all-orders list: search for it alone
                one = self.http.submit(form, form.pairs({"PO_NO": po, "status": "", "orderperpage": "100000"},
                                                        ("submit", "Search")))
                row = _row_for(table_rows(one.html), po, r"CB_\d+")
                rows = table_rows(one.html) if row else rows
            if row is None:
                raise self.fail(f"PO {po} is not in Search Purchase Orders", res)
            if any(c.strip().lower() == "replaced" for c in row.cells):
                raise self.fail(f"PO {po} has been replaced", res)
            ticks[row.control_names(r"CB_\d+")[0]] = po
        rform = get_form(res.html, "new_shipment")
        added = self.http.submit(rform, rform.pairs({**{k: "on" for k in ticks}, "PO_NO": "", "orderperpage": "100000"},
                                                    ("submit", "Add Selected")))
        sel = self.selected_page()
        ids = self._selected_ids(sel)
        for cb, po in ticks.items():
            if po not in ids:
                raise self.fail(f"PO {po} was not added", added)
        for ln in want:
            ln.status = "added"
        self.po_ids.update(ids)
        self.ctx.info(f"shipment {sh.index}: {len(ticks)} POs added (direct)")

    # ---------------------------------------------------------------- carton + Partial
    def _po_form_overrides(self, form: Form, hid: str, po: str, action: str) -> dict[str, str]:
        pack = form.control(f"pack_code_{hid}")
        ptype = form.control(f"web_sh_packing_type_id_{hid}")
        cp = form.control(f"complete_shipment_{hid}")
        if pack is None or ptype is None or cp is None:
            raise self.fail(f"row controls of PO {po} missing")
        return {"action": action, "poHeaderID": hid, "purchaseOrderNo": po, "isCustomizedPage": "false",
                "packaging_code": pack.selected_options()[0].value if pack.options else "",
                "packing_type": ptype.selected_options()[0].value if ptype.options else "",
                "complete_partial": cp.selected_options()[0].value if cp.options else ""}

    def carton(self, line: PlannedLine) -> None:
        ctx, cfg = self.ctx, self.ctx.config.flow
        pl, po = line.po_line, line.po_line.po_line_id
        sel = self.selected_page()
        ids = self._selected_ids(sel)
        hid = ids.get(po)
        if not hid:
            raise self.fail(f"PO {po} not in Selected Purchase Orders", sel)
        form = sel.form("form1")
        ov = self._po_form_overrides(form, hid, po, "insertCarton")
        if ov["packing_type"] in ("", "0") or ov["packaging_code"] in ("", "0"):
            raise self.fail(f"PO {po}: shipping type / packaging code not set", sel)
        cpage = self.http.post("selected_pos.do", form.pairs({**ov, "savepo": "no"}))
        self.resume = self.http.base + "customized_qty_cartons.do"   # this carton now exists: never create another
        # the site answers Create Carton with the carton's Search Items page (older pages: the carton page)
        if "search_items" in cpage.html and "search purchase order items" in cpage.title.lower():
            items = cpage
        elif "customized_qty_carton" in cpage.html:
            items = self.http.get("search_items.do")
        else:
            raise self.fail(f"PO {po}: carton page did not open", cpage)
        irow = next((r for r in table_rows(items.html)
                     if r.control_names(r"CB_\d+") and (r.has_cell(pl.item_label) or pl.item_label in r.text.split())),
                    None)
        cbs = irow.control_names(r"CB_\d+") if irow else []
        if len(cbs) != 1:
            raise self.fail(f"PO {po}: item {pl.item_label} not found on Search Items", items)
        iform = items.form("search_items")
        nxt = self.http.submit(iform, iform.pairs({cbs[0]: "on"}, ("submit", "Add Selected")))
        # site (the site jumps to Search Sites after the item is added)
        if "search purchase order sites" in nxt.title.lower() or "search_sites" in nxt.url:
            srow = _row_for(table_rows(nxt.html), self.sh.to_site_no or "\0", r"CB_\w+")
            if srow is None:
                srow = next((r for r in table_rows(nxt.html) if r.control_names(r"CB_\w+")
                             and any(c.strip().lstrip("0") == (self.sh.to_site_no or "").lstrip("0") for c in r.cells)), None)
            if srow is None:
                raise self.fail(f"PO {po}: site {self.sh.to_site_no} not on Search Sites", nxt)
            sform = nxt.form("search_sites")
            nxt = self.http.submit(sform, sform.pairs({srow.control_names(r"CB_\w+")[0]: "on"},
                                                      ("submit", "Add Selected")))
        cform = nxt.form("customized_qty_carton")
        rows = table_rows(nxt.html)
        item_i = next((i for i, r in enumerate(rows) if r.control_names(r"editedItemQty\d+")
                       and (pl.item_label in r.links or pl.item_label in r.text.split())), None)
        site_r = next((r for r in rows if r.control_names(r"editedSiteQty\d+")
                       and any(c.strip().lstrip("0") == (self.sh.to_site_no or "").lstrip("0")
                               for c in r.cells + r.links)), None)
        if item_i is None or site_r is None:
            raise self.fail(f"PO {po}: item or site missing on the carton page", nxt)
        item_r = rows[item_i]
        iid = _ids(item_r.control_names(r"editedItemQty\d+"), "editedItemQty")[0]
        sid = _ids(site_r.control_names(r"editedSiteQty\d+"), "editedSiteQty")[0]
        ordered = _dec(cform.control(f"ItemOrderedQty{iid}").value if cform.control(f"ItemOrderedQty{iid}") else "")
        um = (item_r.cells[-1] if item_r.cells else "").strip()
        prepack = None
        if item_i + 1 < len(rows) and not rows[item_i + 1].controls:
            m = re.search(r"(\d+)\s*EA\b", rows[item_i + 1].text)
            if m:
                prepack = int(m.group(1))
        plan = decide_carton(pl.quantity, pl.packages, ordered, um, prepack)
        line.carton, line.web_qty_ordered, line.web_um = plan, ordered, um
        bad = plan.web_rule in ("unknown", "mismatch") or any(f.severity == "error" for f in plan.flags)
        if bad or plan.qty_per_carton <= 0 or plan.cartons_per_site <= 0 \
                or (ordered is not None and plan.qty_per_carton > ordered):
            # the UI step asks the user about quantities; continue there on this very carton page
            raise self.fail(f"PO {po}: quantities need a check (web {ordered} {um}, prepack {prepack})", nxt)
        pl.flags += plan.flags
        code = cform.option_value("packagingCodeSelect", label=cfg.packaging_code_carton, prefix="Physical Container - Carton")
        if not code:
            raise self.fail("packaging code not in the list", nxt)
        qpc, cps = str(plan.qty_per_carton), str(plan.cartons_per_site)
        saved = self.http.post("customized_qty_cartons.do", cform.pairs({
            "packagingCodeSelect": code, f"editedItemQty{iid}": qpc, f"editedSiteQty{sid}": cps,
            "editedElement": f",{iid},{iid}", "editedSites": f",{sid},{sid}", "actionCartonUpdated": "Y",
            "actionItemUpdated": "Y", "actionSiteUpdated": "Y"}))
        sv = get_form(saved.html, "customized_qty_carton") if "customized_qty_carton" in saved.html else None
        got_q = sv.control(f"editedItemQty{iid}").value if sv and sv.control(f"editedItemQty{iid}") else ""
        got_c = sv.control(f"editedSiteQty{sid}").value if sv and sv.control(f"editedSiteQty{sid}") else ""
        got_p = sv.option_value("packagingCodeSelect", value=code) if sv else None
        sel_p = sv.control("packagingCodeSelect").selected_options()[0].value if sv and sv.control("packagingCodeSelect") else ""
        if got_q != qpc or got_c != cps or sel_p != code or not got_p:
            errs = page_errors(saved.html)
            raise self.fail(f"PO {po}: carton not saved ({got_q}/{got_c}/{sel_p})" + (f": {errs[0]}" if errs else ""), saved)
        line.status = "carton_saved"
        self.resume = ""
        # Complete -> Partial
        sel = self.selected_page()
        form = sel.form("form1")
        ov = self._po_form_overrides(form, hid, po, "saveCarton")
        want = form.option_value(f"complete_shipment_{hid}", label=cfg.complete_partial, prefix=cfg.complete_partial)
        if not want:
            raise self.fail(f"'{cfg.complete_partial}' not in Complete/Partial", sel)
        ov.update({"complete_partial": want, f"complete_shipment_{hid}": want, "savepo": "yes"})
        res = self.http.post("selected_pos.do", form.pairs(ov))
        rf = get_form(res.html, "form1") if "form1" in res.html else None
        cp = rf.control(f"complete_shipment_{hid}") if rf else None
        if cp is None or cp.selected_options()[0].value != want:
            raise self.fail(f"PO {po}: {cfg.complete_partial} not saved", res)
        line.status = "carton_done"
        ctx.info(f"PO {po}: carton {qpc} x {cps} saved, {want} (direct)")

    # ---------------------------------------------------------------- weights
    def weights(self) -> None:
        sh, cfg = self.sh, self.ctx.config.flow
        lines = [ln for ln in sh.lines if ln.status == "carton_done"]
        if not lines:
            return
        page = self.http.get("po_site_shipment.do", [("shipment_id", sh.web_shipment_id)])
        m = re.search(r"(\d+)\s+Items? found", page.html)
        if m and int(m.group(1)) > 10:
            page = self.http.get("po_site_shipment.do", [("action", "ordersperpage"), ("ordersperpage", "100000")])
        form = page.form("po_site_shipment")
        rows = table_rows(page.html)
        ov: dict[str, str | None] = {"actionItemAdded": "Y"}
        edited: list[str] = []
        want: dict[str, str] = {}
        for ln in lines:
            po = ln.po_line.po_line_id
            r = _row_for(rows, po, r"editedSiteWgtqu\d+")
            if r is None:
                raise self.fail(f"weight row of PO {po} not found", page)
            rid = _ids(r.control_names(r"editedSiteWgtqu\d+"), "editedSiteWgtqu")[0]
            w = _dec(ln.weight_text)
            if w is None or w <= 0 or len(ln.weight_text) > 10:
                raise self.fail(f"PO {po}: weight {ln.weight_text!r} not accepted by the site", page)
            um = form.option_value(f"editedSiteWgtum{rid}", value=cfg.weight_um, label=cfg.weight_um)
            if not um:
                raise self.fail(f"weight unit {cfg.weight_um} not in the list", page)
            ov[f"editedSiteWgtqu{rid}"] = ln.weight_text
            ov[f"editedSiteWgtum{rid}"] = um
            edited += [rid, rid]
            want[rid] = ln.weight_text
        ov["editedElement"] = "," + ",".join(edited)
        saved = self.http.post("po_site_shipment.do?save=yes", form.pairs(ov))
        sf = get_form(saved.html, "po_site_shipment") if "po_site_shipment" in saved.html else None
        for rid, w in want.items():
            c = sf.control(f"editedSiteWgtqu{rid}") if sf else None
            if c is None or _dec(c.value) != _dec(w):
                raise self.fail(f"weight not saved ({c.value if c else '?'} != {w})", saved)
        for ln in lines:
            ln.status = "weight_done"
        self.ctx.info(f"shipment {sh.index}: weights saved for {len(lines)} POs (direct)")
