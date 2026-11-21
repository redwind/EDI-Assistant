"""Flow steps S0..S10. Every step is idempotent on retry."""
from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from playwright.sync_api import Error as PlaywrightError

from edi_assistant.core.dc_sites import pick_option, same_site
from edi_assistant.core.dates import compute_shipping_date, format_mdy, parse_date_token, parse_ship_dates
from edi_assistant.core.errors import (DataMismatchError, ElementNotFoundError, PostconditionFailed, StepSkipped)
from edi_assistant.core.events import InputField, ShipmentCreated
from edi_assistant.core.models import Flag, PlannedLine
from edi_assistant.core.quantities import decide_carton

from ..actions import SAVE_NAV_TIMEOUT_MS
from ..po_dates import _collapse, read_po_dates, read_pdf_window
from ..selectors import _Skip, extract_row_key

if TYPE_CHECKING:
    from .context import FlowContext

ADD_CONFIRM = r"do you want to add the selected"
SAVE_CHANGES_CONFIRM = r"do you want to save the changes"   # carton / weight Save ("... made on this page?"), PO row Save ("... ?")   # carton / weight Save (checkAndSaveCarton)
NEG = 250   # ms budget for negative existence probes (page already loaded)
ERROR_SCAN_MAX = 20   # post-Save error scan: how many matches per candidate are inspected
_HAS_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)   # an error message carries words; a lone red '*' marker does not


class Step:
    id: str = ""
    title_vi: str = ""
    selector_keys: tuple[str, ...] = ()
    retry_on_fail: bool = True
    line: PlannedLine | None = None

    def act(self, ctx: "FlowContext") -> None: ...

    def check(self, ctx: "FlowContext") -> bool: ...


def _dec(s: str) -> Decimal:
    t = re.sub(r"[^\d.\-]", "", (s or "").replace(",", ""))
    try:
        return Decimal(t)
    except InvalidOperation:
        raise DataMismatchError(f"cannot parse number {s!r}", message_vi=f'Cannot read number "{s}"') from None


def _poll(fn, timeout_ms: int, ctx: "FlowContext") -> bool:
    end = time.monotonic() + timeout_ms / 1000
    while True:
        ctx.actions._check_abort()
        try:
            if fn():
                return True
        except PlaywrightError:
            pass
        if time.monotonic() >= end:
            return False
        ctx.page.wait_for_timeout(150)


def _visible_text(ctx: "FlowContext", key: str, vars: dict | None = None) -> str:
    """First visible match of `key` (all candidates, all matches) whose text carries words; '' when none.
    Used for post-Save error checks, so it deliberately does not stop at an empty/hidden first match."""
    page = ctx.page
    for cand in ctx.resolver.store.candidates(key):
        try:
            loc = ctx.resolver.build(page, cand, vars or {}, within_timeout_ms=0)
            for i in range(min(loc.count(), ERROR_SCAN_MAX)):
                el = loc.nth(i)
                if el.is_visible():
                    txt = el.inner_text().strip()
                    if _HAS_WORD.search(txt):
                        return txt
        except (_Skip, ElementNotFoundError, PlaywrightError):
            continue
    return ""


def _settle(ctx: "FlowContext") -> None:
    """Let the current document finish loading before a post-action check (returns at once when already loaded)."""
    for state, cap in (("domcontentloaded", 8000), ("load", 3000)):
        try:
            ctx.page.wait_for_load_state(state, timeout=cap)
        except PlaywrightError:
            pass


def _dialog_mark(ctx: "FlowContext") -> int:
    d = getattr(ctx, "dialogs", None)
    return d.count if d is not None else 0


def _dialogs_text(ctx: "FlowContext", mark: int | None) -> str:
    """Messages of the alerts/confirms the site showed since `mark` (they were auto-closed, so quote them)."""
    d = getattr(ctx, "dialogs", None)
    if d is None or mark is None:
        return ""
    parts = []
    for typ, msg, accepted in d.since(mark):
        msg = " ".join((msg or "").split())
        if msg:
            parts.append(f'"{msg}"' + ("" if typ == "alert" or accepted else " (answered Cancel)"))
    return "; ".join(parts)


def _after_save(ctx: "FlowContext", navigated: bool, what: str, step_id: str, dialog_mark: int | None = None) -> None:
    """Gate after every Save click: the page must have settled and show no error text, and a Save that did not
    reload the page is a failure (the value read-back would otherwise just echo what we typed).
    `dialog_mark` (from _dialog_mark before the click) lets the failure quote any popup the site showed."""
    _settle(ctx)
    popups = _dialogs_text(ctx, dialog_mark)
    err = _visible_text(ctx, "ship.error_text")
    if err:
        raise PostconditionFailed(f"{what} error: {err}", message_vi="The site reported an error: " + err, step_id=step_id)
    if not navigated:
        msg = "The page did not reload after Save"
        if popups:
            msg += f". The site showed: {popups}. Fix it in the browser, press Save there, then press Continue."
        else:
            msg += "; check the page in the browser"
        raise PostconditionFailed(f"page did not reload after Save ({what})" + (f"; popups: {popups}" if popups else ""),
                                  message_vi=msg, step_id=step_id)


def _row_in(ctx: "FlowContext", row, key: str, vars: dict):
    """First candidate of `key` that matches inside `row`."""
    for cand in ctx.resolver.store.candidates(key):
        try:
            loc = ctx.resolver.build(row, cand, vars)
            if loc.count() >= 1:
                return loc.first
        except PlaywrightError:
            continue
    raise ElementNotFoundError(f"not found inside row: {key}", message_vi=f"Element not found: {key}", key=key, tried=[])


# ---------------------------------------------------------------- S0
class S0EnsureLoggedIn(Step):
    id = "S0.ensure_logged_in"
    title_vi = "Check login"
    selector_keys = ("login.password_input", "login.profile_vendor_link", "login.edi_gateway_button")

    def act(self, ctx: "FlowContext") -> None:
        s, a = ctx.session, ctx.actions
        s.goto("gateway/inbox.do")
        for _ in range(8):
            title = s.title()
            if "EDI Gateway Inbox" in title:
                return
            if "-- Login" in title or a.exists("login.password_input", timeout_ms=NEG):
                ctx.ask("login_required",
                        "Please log in to EDI Gateway in the browser window (the tool never types passwords). "
                        "When you are logged in, press Continue.", options=["continue", "abort"], step_id=self.id)
                s.goto("gateway/inbox.do")
            elif "Select Profile" in title:
                a.click("login.profile_vendor_link", ctx.vars(), expect_navigation=True)
            elif "View Profile" in title:
                a.click("login.edi_gateway_button", expect_navigation=True)
            else:
                s.goto("gateway/inbox.do")

    def check(self, ctx: "FlowContext") -> bool:
        return "EDI Gateway Inbox" in ctx.session.title() or ctx.actions.exists("inbox.document_id_input", timeout_ms=NEG)


# ---------------------------------------------------------------- S1..S4
class S1InboxSearch(Step):
    selector_keys = ("inbox.document_id_input", "inbox.search_button", "inbox.result_row")

    def __init__(self, line: PlannedLine):
        self.line = line
        self.po = line.po_line.po_line_id
        self.id = "S1.inbox_search"
        self.title_vi = f"Find PO {self.po} in Inbox"

    def act(self, ctx: "FlowContext") -> None:
        a = ctx.actions
        v = ctx.vars(self.line)
        if "inbox.do" not in ctx.session.url() or not a.exists("inbox.document_id_input", v, 1500):
            ctx.session.goto("gateway/inbox.do")
        a.fill("inbox.document_id_input", self.po, v)
        a.click("inbox.search_button", v, expect_navigation=True)

    def check(self, ctx: "FlowContext") -> bool:
        v = ctx.vars(self.line)
        if ctx.actions.exists("inbox.result_row", v, 6000):
            return True
        if ctx.actions.exists("inbox.results_table", v, NEG):
            raise DataMismatchError(f"PO {self.po} not found in inbox",
                                    message_vi=f"PO {self.po} not found in Inbox. Check the PO number and line number (01, 02…).")
        return False


class S2OpenPODetail(Step):
    selector_keys = ("inbox.result_row_active", "inbox.result_link", "po.page_marker", "po.create_new_shipment_link")

    def __init__(self, line: PlannedLine):
        self.line = line
        self.po = line.po_line.po_line_id
        self.id = "S2.open_po_detail"
        self.title_vi = f"Open PO {self.po} details"

    def act(self, ctx: "FlowContext") -> None:
        a = ctx.actions
        v = ctx.vars(self.line)
        try:
            row, _ = a.resolve("inbox.result_row_active", v, 2500)
        except ElementNotFoundError:
            if a.exists("inbox.result_row", v, NEG):
                raise DataMismatchError(f"PO {self.po} only has REPLACED versions",
                                        message_vi=f"PO {self.po} only has REPLACED versions. Check for the new PO.") from None
            raise
        link = _row_in(ctx, row, "inbox.result_link", v)
        a.click_locator(link, expect_navigation=True)

    def check(self, ctx: "FlowContext") -> bool:
        v = ctx.vars(self.line)
        return _poll(lambda: "view_order.do" in ctx.session.url() or ctx.actions.exists("po.page_marker", v, NEG)
                     or ctx.actions.exists("po.create_new_shipment_link", v, NEG), 8000, ctx)


class S3ReadDates(Step):
    selector_keys = ("po.pdf_embed",)

    def __init__(self, line: PlannedLine):
        self.line = line
        self.po = line.po_line.po_line_id
        self.master = line.po_line.master_po
        self.id = "S3.read_dates"
        self.title_vi = "Read ship dates (Early/Late Ship Date)"

    def act(self, ctx: "FlowContext") -> None:
        sh = ctx.current_shipment
        if sh.dates_source == "excel" and self.master in sh.po_windows:
            self._cross_check(ctx, sh)
            return
        w, source = read_po_dates(ctx, self.po)
        sh.po_windows[self.master] = w
        if source == "user":
            sh.flags.append(Flag("dates_manual", f"Ship dates of PO {self.po} entered by the user", "info"))
        ctx.info(f"dates {self.po} {w.early}..{w.late} via {source}")

    def _cross_check(self, ctx: "FlowContext", sh) -> None:
        """Excel dates are authoritative: the web window is only compared (rungs DOM + PDF; no AI, no user prompt)."""
        excel_w = sh.po_windows[self.master]
        w = None
        try:
            w = parse_ship_dates(_collapse(ctx.actions.body_text()))
        except PlaywrightError:
            pass
        if w is None:
            w = read_pdf_window(ctx)
        if w is None:
            ctx.info(f"dates {self.po}: web dates not readable; using Excel {excel_w.early}..{excel_w.late}")
        elif (w.early, w.late) != (excel_w.early, excel_w.late):
            msg = (f"PO {self.po}: web window {w.early}..{w.late} differs from Excel "
                   f"{excel_w.early}..{excel_w.late}; Excel used")
            sh.flags.append(Flag("dates_mismatch_web", msg))
            ctx.warn(msg)
        else:
            ctx.info(f"dates {self.po} confirmed on web")

    def check(self, ctx: "FlowContext") -> bool:
        return self.master in ctx.current_shipment.po_windows


class S4ComputeShipDate(Step):
    id = "S4.compute_ship_date"
    title_vi = "Compute ship date"

    def act(self, ctx: "FlowContext") -> None:
        sh = ctx.current_shipment
        res = compute_shipping_date(list(sh.po_windows.values()), ctx.today())
        if any(f.code == "no_date_intersection" for f in res.flags):
            ctx.ask("no_date_intersection",
                    f"The POs in this shipment have non-overlapping ship date windows. The midpoint of the first PO will be used ({res.shipping_date}). Continue?",
                    options=["continue", "abort"], step_id=self.id)
        if any(f.code == "date_in_past" for f in res.flags) and ctx.config.flow.past_date_policy == "ask":
            resp = ctx.ask("date_in_past",
                           f"The midpoint of the ship window is in the past. Enter a ship date (MM/DD/YYYY) or keep the default to use today ({format_mdy(res.shipping_date)}).",
                           options=["continue", "abort"], step_id=self.id,
                           input_fields=[InputField("shipping_date", "Ship date (MM/DD/YYYY)", default=format_mdy(res.shipping_date))])
            typed = parse_date_token(resp.values.get("shipping_date", ""))
            if typed is not None:
                res.shipping_date = typed
        sh.shipping_date = res.shipping_date
        sh.date_result = res
        sh.flags += res.flags

    def check(self, ctx: "FlowContext") -> bool:
        return ctx.current_shipment.shipping_date is not None


# ---------------------------------------------------------------- S5 / S6
class S5CreateNewShipment(Step):
    id = "S5.create_new_shipment"
    title_vi = "Click Create New Shipment"
    selector_keys = ("po.create_new_shipment_link", "ship.form", "ship.shipping_type")

    def __init__(self, line: PlannedLine):
        self.line = line
        self._tries = 0

    def act(self, ctx: "FlowContext") -> None:
        try:
            ctx.actions.click("po.create_new_shipment_link", ctx.vars(self.line), timeout_ms=5000, expect_navigation=True)
        except ElementNotFoundError:
            if ctx.healer.can_call() and self._tries == 0:
                self._tries = 1
                raise   # let the runner try AI healing first
            ctx.warn("Create New Shipment link not found; falling back to gateway/new_shipment.do")
            ctx.session.goto("gateway/new_shipment.do")

    def check(self, ctx: "FlowContext") -> bool:
        a = ctx.actions
        return _poll(lambda: a.exists("ship.form", timeout_ms=NEG) and a.exists("ship.shipping_type", timeout_ms=NEG), 8000, ctx)


def _capture_ids(ctx: "FlowContext") -> bool:
    """Read web/asn ids from the saved shipment page; idempotent. True if a saved shipment is shown."""
    a, sh = ctx.actions, ctx.current_shipment
    wid = ""
    loc = ctx.resolver.try_resolve(ctx.page, "ship.web_shipment_id", None, NEG)
    if loc is not None:
        wid = a.value_of(loc)
    if not wid:
        m = re.search(r"Web Shipment ID:\s*(\d+)", a.body_text())
        wid = m.group(1) if m else ""
    if not wid:
        m = re.search(r"shipment_id=(\d+)", ctx.session.url())
        wid = m.group(1) if m else ""
    if not re.fullmatch(r"\d{3,}", wid or ""):
        return False
    first = sh.web_shipment_id != wid
    aid = ""
    loc = ctx.resolver.try_resolve(ctx.page, "ship.asn_shipment_id", None, NEG)
    if loc is not None:
        aid = a.value_of(loc)
    sh.web_shipment_id, sh.asn_shipment_id = wid, aid or wid
    loc = ctx.resolver.try_resolve(ctx.page, "ship.to_site_no", None, NEG)
    if loc is not None:
        sh.to_site_no = a.value_of(loc) or sh.to_site_no
    if first:
        ctx.emit(ShipmentCreated(shipment_index=sh.index, web_shipment_id=wid, asn_shipment_id=sh.asn_shipment_id))
        ctx.results.write(ctx.plan)
    return True


def _select_to_site(ctx: "FlowContext", step_id: str) -> None:
    """TO Site No: a dropdown on a new shipment (pick the DC from the Delivery Address state);
    older pages show it read-only, filled from the PO - then only compare."""
    a, sh = ctx.actions, ctx.current_shipment
    loc = ctx.resolver.try_resolve(ctx.page, "ship.to_site_select", None, NEG)
    if loc is None:
        ro = ctx.resolver.try_resolve(ctx.page, "ship.to_site_no", None, NEG)
        got = a.value_of(ro) if ro is not None else ""
        if got and sh.to_site_no and not same_site(got, sh.to_site_no):
            ctx.warn(f"TO Site No on the page is {got}, Delivery Address says {sh.to_site_no}")
        return
    if not sh.to_site_no:
        ctx.ask("to_site_missing",
                "TO Site No is unknown (no Delivery Address / state in the tracker). Pick the DC in the "
                "TO \"Site No\" dropdown in the browser (CA=512, NJ=053, GA=934), then press Continue.",
                options=["continue", "abort"], step_id=step_id)
        return
    opts = loc.evaluate("el => [...el.options].map(o => [o.value, (o.text||'').trim()])")
    hit = pick_option([(o[0], o[1]) for o in opts], sh.to_site_no)
    if hit is None:
        ctx.ask("to_site_not_in_list",
                f"TO Site No {sh.to_site_no} is not in the dropdown ({', '.join(o[1] for o in opts if o[1])[:200]}). "
                "Pick the right DC in the browser, then press Continue.", options=["continue", "abort"], step_id=step_id)
        return
    a.select_locator(loc, value=hit)
    loc.dispatch_event("change")
    if not _poll(lambda: a.read_value("ship.to_address1", timeout_ms=NEG), 3000, ctx):
        ctx.warn(f"TO address not auto-filled after selecting Site No {sh.to_site_no}")


class S6FillHeaderSave(Step):
    id = "S6.fill_header_save"
    title_vi = "Fill shipment header and Save"
    selector_keys = ("ship.radio_with_cartons", "ship.shipping_type", "ship.shipping_date", "ship.transportation_method",
                     "ship.scac_code", "ship.bill_of_lading", "ship.pro_number", "ship.from_name", "ship.save_button")

    def act(self, ctx: "FlowContext") -> None:
        a, sh, cfg = ctx.actions, ctx.current_shipment, ctx.config.flow
        _settle(ctx)
        probe_ms = 1500 if "shipment_id=" in ctx.session.url() else NEG   # a saved header's URL carries its id
        if a.exists("ship.submit_asn_button", timeout_ms=probe_ms) and _capture_ids(ctx):
            return   # already saved (retry after manual save)
        f = sh.factory
        a.check("ship.radio_with_cartons")
        a.select("ship.shipping_type", value="3", label=cfg.shipping_type)
        a.fill("ship.shipping_date", format_mdy(sh.shipping_date), dispatch_change=True)
        if f.transport_method:   # factory override (e.g. Mexico by truck: LTL)
            a.select("ship.transportation_method", label=f.transport_method, label_prefix=f.transport_method)
        else:
            a.select("ship.transportation_method", value="O", label=cfg.transportation_method)
        scac = f.scac_code or cfg.scac_code
        a.select("ship.scac_code", value=scac, label_prefix=scac)
        if not _poll(lambda: a.read_value("ship.carrier", timeout_ms=NEG), 3000, ctx):
            a.resolve("ship.scac_code")[0].dispatch_event("change")   # nudge the onchange handler once
            if not _poll(lambda: a.read_value("ship.carrier", timeout_ms=NEG), 3000, ctx):
                ctx.warn("carrier not auto-filled after SCAC selection")
        a.fill("ship.bill_of_lading", cfg.bill_of_lading)
        a.fill("ship.pro_number", cfg.pro_number)
        _select_to_site(ctx, self.id)
        if f.site_no:
            a.select("ship.from_site_no", label=f.site_no)
        a.fill("ship.from_name", f.name)
        a.fill("ship.from_address1", f.address1)
        a.fill("ship.from_address2", f.address2)
        a.fill("ship.from_city", f.city)
        a.fill("ship.from_state", f.state)
        a.fill("ship.from_zip", f.zip)
        try:
            a.select("ship.from_country", label=f.country, label_prefix=f.country[:5])
        except DataMismatchError:
            ctx.ask("country_not_in_list",
                    f'Country "{f.country}" is not in the list. Click "More.." in the browser and pick the country, then press Continue.',
                    options=["continue", "abort"], step_id=self.id)
            if not a.read_value("ship.from_country"):
                raise PostconditionFailed("country still empty", message_vi="No country selected", step_id=self.id) from None
        if ctx.plan.dry_run:
            ctx.ask("dry_run_stop", "Dry run: the form is filled but NOT saved. Press Continue to finish this shipment.",
                    options=["continue", "abort"], step_id=self.id)
            sh.status = "dry_run"
            raise StepSkipped("dry run")
        mark = _dialog_mark(ctx)
        navigated = a.click("ship.save_button", expect_navigation=True, nav_timeout_ms=SAVE_NAV_TIMEOUT_MS)
        _after_save(ctx, navigated, "header", self.id, mark)
        _capture_ids(ctx)

    def check(self, ctx: "FlowContext") -> bool:
        sh = ctx.current_shipment
        _settle(ctx)
        txt = _visible_text(ctx, "ship.error_text")
        if txt and _capture_ids(ctx) and ctx.actions.exists("ship.submit_asn_button", timeout_ms=1500):
            # saved-shipment state (Web Shipment ID + Submit ASN button present): residual red text is only a warning
            ctx.warn(f"red text on the saved-shipment page ignored: {txt}")
            txt = ""
        if txt:
            raise PostconditionFailed(f"page error: {txt}", message_vi="The site reported an error: " + txt, step_id=self.id)
        if not _capture_ids(ctx):
            return False
        return bool(re.fullmatch(r"\d{3,}", sh.web_shipment_id)) and ctx.actions.exists("ship.submit_asn_button", timeout_ms=1500)


# ---------------------------------------------------------------- S7
def _ensure_selected_tab(ctx: "FlowContext", v: dict) -> None:
    a = ctx.actions
    if a.exists("pos.search_po_input", v, NEG):
        a.click("pos.tab_selected", v, expect_navigation=True)


class S7AddPurchaseOrders(Step):
    id = "S7.add_purchase_orders"
    title_vi = "Add POs to the shipment"
    selector_keys = ("ship.selected_pos_button", "pos.tab_search", "pos.search_po_input", "pos.search_button",
                     "pos.search_row", "pos.add_selected_button", "pos.selected_row")

    def act(self, ctx: "FlowContext") -> None:
        a, sh = ctx.actions, ctx.current_shipment
        if not a.exists("pos.page_marker", timeout_ms=NEG):
            a.click("ship.selected_pos_button", expect_navigation=True)
        _settle(ctx)
        for line in sh.lines:
            if line.status != "pending":
                continue
            v = ctx.vars(line)
            po = v["po"]
            _ensure_selected_tab(ctx, v)
            if not a.exists("pos.selected_row", v, 1000):
                a.click("pos.tab_search", v, expect_navigation=True)
                a.fill("pos.search_po_input", po, v)
                a.click("pos.search_button", v, expect_navigation=True)
                row, _ = a.resolve("pos.search_row", v, 6000)
                boxes = row.locator("input[type='checkbox']")
                if po not in " ".join(row.inner_text().split()) or boxes.count() != 1:
                    raise PostconditionFailed(f"search row for PO {po} is ambiguous",
                                              message_vi=f"Could not single out the row of PO {po} in the search "
                                                         "results; tick it and press Add Selected in the browser",
                                              step_id=self.id)
                boxes.first.check()
                ctx.dialogs.expect_accept(ADD_CONFIRM)
                a.click("pos.add_selected_button", v, expect_navigation=True)
                if not a.exists("pos.selected_row", v, 6000):
                    a.click("pos.tab_selected", v, expect_navigation=True)
                    if not a.exists("pos.selected_row", v, 3000):
                        raise PostconditionFailed(f"PO {po} not in selected list",
                                                  message_vi=f"PO {po} is not in the selected list yet", step_id=self.id)
            line.status = "added"
            row, _ = a.resolve("pos.selected_row", v, 4000)
            cells = [c.strip().lower() for c in row.locator("td").all_inner_texts()]   # Status column position differs (mock 3rd, real 4th)
            if "replaced" in cells:
                line.po_line.flags.append(Flag("po_replaced", f"PO {po} has been replaced", "error"))
                resp = ctx.ask("po_replaced",
                               f'PO {po} has been replaced. Handle it manually following the "PO replaced" procedure, then press Continue, or Skip this line.',
                               options=["continue", "skip", "abort"], step_id=self.id)
                if resp.action == "skip":
                    line.status = "skipped"

    def check(self, ctx: "FlowContext") -> bool:
        a = ctx.actions
        for line in ctx.current_shipment.lines:
            if line.status in ("skipped", "failed"):
                continue
            v = ctx.vars(line)
            _ensure_selected_tab(ctx, v)
            if not a.exists("pos.selected_row", v, 1500):
                return False
        return True


# ---------------------------------------------------------------- S8 / S8b
def _row_vars(ctx: "FlowContext", line: PlannedLine) -> dict:
    v = ctx.vars(line)
    row, _ = ctx.actions.resolve("pos.selected_row", v, 4000)
    v["row_key"] = extract_row_key(row, "pos")
    return v


def _on_sites_search(ctx: "FlowContext") -> bool:
    """The carton's 'Search Sites' page (title 'BCF EDI Gateway -- Search Purchase Order Sites')."""
    try:
        return "search purchase order sites" in ctx.session.title().lower() or "search_sites.do" in ctx.session.url()
    except PlaywrightError:
        return False


class S8CreateCarton(Step):
    selector_keys = ("pos.row_create_carton_button", "carton.page_marker", "carton.item_po_row", "carton.site_row",
                     "carton.packaging_code_select", "carton.item_qty_per_carton_input",
                     "carton.site_cartons_per_site_input", "carton.save_button", "carton.back_to_po_button")

    def __init__(self, line: PlannedLine):
        self.line = line
        self.po = line.po_line.po_line_id
        self.id = f"S8.create_carton[{self.po}]"
        self.title_vi = f"Create cartons for PO {self.po}"

    def _add_via_search(self, ctx, tab_key: str, row_key: str, add_key: str, v: dict, skip_tab: bool = False) -> None:
        a = ctx.actions
        if not skip_tab:
            try:
                a.click(tab_key, v, timeout_ms=1500, expect_navigation=True)
            except ElementNotFoundError:
                pass   # tab may be absent
        row, _ = a.resolve(row_key, v, 4000)
        boxes = row.locator("input[type='checkbox']")
        if boxes.count() != 1:
            raise PostconditionFailed(f"{row_key}: {boxes.count()} checkboxes in the row",
                                      message_vi="Could not single out the row to tick; tick it and press Add Selected "
                                                 "in the browser", step_id=self.id)
        boxes.first.check()
        ctx.dialogs.expect_accept(ADD_CONFIRM)
        a.click(add_key, v, expect_navigation=True)

    def act(self, ctx: "FlowContext") -> None:
        a, cfg, line = ctx.actions, ctx.config.flow, self.line
        pl = line.po_line
        if not a.exists("carton.page_marker", timeout_ms=NEG):
            if not a.exists("pos.page_marker", timeout_ms=1500):
                raise PostconditionFailed("not on selected POs page", message_vi="Not on the Selected Purchase Orders page", step_id=self.id)
            _ensure_selected_tab(ctx, ctx.vars(line))
            v = _row_vars(ctx, line)
            a.click("pos.row_create_carton_button", v, expect_navigation=True)
            if not a.exists("carton.page_marker", v, 8000):
                raise PostconditionFailed("carton page not shown", message_vi="Could not open the carton page", step_id=self.id)
        v = ctx.vars(line)
        if not a.exists("carton.item_po_row", v, 300) and not _on_sites_search(ctx):
            self._add_via_search(ctx, "carton.tab_items_search", "carton.items_search_row", "carton.items_add_selected", v)
            # the real site moves straight on to "Search Sites" after the item is added
            if not _on_sites_search(ctx) and not a.exists("carton.item_po_row", v, 8000):
                raise PostconditionFailed("item row missing", message_vi="Could not add the item to the carton", step_id=self.id)
        if _on_sites_search(ctx) or not a.exists("carton.site_row", v, 300):
            if not v.get("site_no"):
                raise PostconditionFailed("TO site unknown", message_vi="TO Site No is unknown, so the site to add to "
                                          "the carton is unknown; tick it on Search Sites and press Add Selected",
                                          step_id=self.id)
            self._add_via_search(ctx, "carton.tab_sites_search", "carton.sites_search_row", "carton.sites_add_selected", v,
                                 skip_tab=_on_sites_search(ctx))
            if not a.exists("carton.site_row", v, 8000):
                raise PostconditionFailed("site row missing", message_vi="Could not add the site to the carton", step_id=self.id)
        if not a.exists("carton.item_po_row", v, 3000):
            raise PostconditionFailed("item row missing", message_vi="The item is not in the carton (Selected Items)",
                                      step_id=self.id)
        ordered = _dec(a.read_text("carton.item_qty_ordered_cell", v))
        um = a.read_text("carton.item_um_cell", v).strip()
        prepack: int | None = None
        pre = ctx.resolver.try_resolve(ctx.page, "carton.item_prepack_row", v, 300)
        if pre is not None:
            m = re.search(r"(\d+)\s*EA\b", pre.inner_text())
            if m:
                prepack = int(m.group(1))
        elif um.upper() == "AS":
            ctx.warn(f"{self.po}: unit of measure AS but no prepack sub-row found")
        plan = decide_carton(pl.quantity, pl.packages, ordered, um, prepack)
        qpc, cps = plan.qty_per_carton, plan.cartons_per_site
        line.carton, line.web_qty_ordered, line.web_um = plan, ordered, um
        if any(f.severity == "error" and f.code in ("non_integer_units", "non_integer_prepack") for f in plan.flags):
            resp = ctx.ask("non_integer_carton",
                           f"Quantity {pl.quantity} / {pl.packages} cartons does not divide evenly (prepack {prepack}). Enter values manually or Skip.",
                           options=["continue", "skip", "abort"],
                           input_fields=[InputField("qty_per_carton", "Qty Per Carton", default=str(qpc)),
                                         InputField("cartons_per_site", "Cartons Per Site", default=str(cps))], step_id=self.id)
            if resp.action == "skip":
                line.status = "skipped"
                raise StepSkipped("non-integer carton math")
            try:
                qpc, cps = int(resp.values["qty_per_carton"]), int(resp.values["cartons_per_site"])
            except (KeyError, ValueError):
                raise PostconditionFailed("invalid carton numbers", message_vi="Invalid numbers entered", step_id=self.id) from None
            plan.qty_per_carton, plan.cartons_per_site = qpc, cps
        need_pause = plan.web_rule in ("unknown", "mismatch") and (
            ctx.plan.qty_strict or plan.web_rule == "unknown" or any(f.code == "qty_over_ordered" for f in plan.flags))
        pl.flags += plan.flags
        if need_pause and cfg.pause_on_qty_warning:
            resp = ctx.ask("qty_mismatch",
                           f"PO {self.po}: Excel Order Units {pl.order_units or pl.quantity}, Pack {pl.pack_qty or plan.units_per_carton} "
                           f"-> Cartons {pl.packages}; web Qty Ordered {ordered} {um}"
                           + (f", prepack {prepack} EA" if prepack else "")
                           + ". Qty Per Carton x Cartons Per Site must equal Qty Ordered. "
                           "Enter the values to use, Skip this line, or Abort.",
                           options=["continue", "skip", "abort"],
                           input_fields=[InputField("qty_per_carton", "Qty Per Carton", default=str(qpc)),
                                         InputField("cartons_per_site", "Cartons Per Site", default=str(cps))],
                           step_id=self.id)
            if resp.action == "skip":
                line.status = "skipped"
                raise StepSkipped("qty mismatch")
            try:
                qpc, cps = int(resp.values.get("qty_per_carton", qpc)), int(resp.values.get("cartons_per_site", cps))
            except (TypeError, ValueError):
                raise PostconditionFailed("invalid carton numbers", message_vi="Invalid numbers entered", step_id=self.id) from None
            plan.qty_per_carton, plan.cartons_per_site = qpc, cps
        if pl.model_no:
            row_txt = ctx.resolver.try_resolve(ctx.page, "carton.item_po_row", v, NEG)
            try:
                txt = row_txt.inner_text() if row_txt is not None else ""
            except PlaywrightError:
                txt = ""
            if txt and pl.model_no.upper() not in txt.upper():
                msg = f"PO {self.po}: Model {pl.model_no} not shown in the item row"
                pl.flags.append(Flag("model_mismatch_web", msg, "warning"))
                ctx.warn(msg)
        a.select("carton.packaging_code_select", label=cfg.packaging_code_carton, label_contains="Physical Container", vars=v)
        a.fill("carton.item_qty_per_carton_input", str(qpc), v, dispatch_change=True)
        a.fill("carton.site_cartons_per_site_input", str(cps), v, dispatch_change=True)
        mark = _dialog_mark(ctx)
        ctx.dialogs.expect_accept(SAVE_CHANGES_CONFIRM)
        navigated = a.click("carton.save_button", v, expect_navigation=True, nav_timeout_ms=SAVE_NAV_TIMEOUT_MS)
        _after_save(ctx, navigated, "carton", self.id, mark)   # a rejected Save re-renders the typed values: never trust the read-back alone
        got_q = a.read_value("carton.item_qty_per_carton_input", v)
        got_c = a.read_value("carton.site_cartons_per_site_input", v)
        if got_q != str(qpc) or got_c != str(cps):
            raise PostconditionFailed(f"carton values not persisted ({got_q}/{got_c})",
                                      message_vi="Carton values were not saved", step_id=self.id)
        a.click("carton.back_to_po_button", v, expect_navigation=True)
        if not a.exists("pos.page_marker", v, 8000):
            raise PostconditionFailed("not back on POs page", message_vi="Could not return to the PO page", step_id=self.id)
        line.status = "carton_done"

    def check(self, ctx: "FlowContext") -> bool:
        return self.line.status in ("carton_done", "skipped") and ctx.actions.exists("pos.page_marker", timeout_ms=1500)


class S8bSetPartial(Step):
    selector_keys = ("pos.row_complete_partial_select", "pos.row_save_button")

    def __init__(self, line: PlannedLine):
        self.line = line
        self.po = line.po_line.po_line_id
        self.id = f"S8b.set_partial[{self.po}]"
        self.title_vi = f"Change Complete -> Partial for PO {self.po}"

    def act(self, ctx: "FlowContext") -> None:
        if self.line.status == "skipped":
            raise StepSkipped("line skipped")
        a = ctx.actions
        v = _row_vars(ctx, self.line)
        a.select("pos.row_complete_partial_select", label=ctx.config.flow.complete_partial, vars=v)
        mark = _dialog_mark(ctx)
        ctx.dialogs.expect_accept(SAVE_CHANGES_CONFIRM)   # saveCarton(): confirm("Do you want to save the changes ?")
        navigated = a.click("pos.row_save_button", v, expect_navigation=True, nav_timeout_ms=SAVE_NAV_TIMEOUT_MS)
        _after_save(ctx, navigated, "complete/partial", self.id, mark)   # the select shows Partial even when not saved

    def check(self, ctx: "FlowContext") -> bool:
        if self.line.status == "skipped":
            return True
        v = _row_vars(ctx, self.line)
        got = ctx.actions.read_value("pos.row_complete_partial_select", v)
        return got.lower() == ctx.config.flow.complete_partial.lower()


# ---------------------------------------------------------------- S9 / S10
class S9EnterWeights(Step):
    id = "S9.enter_weights"
    title_vi = "Enter weights"
    selector_keys = ("pos.view_detail_button", "weight.form", "weight.row", "weight.row_weight_input",
                     "weight.row_um_select", "weight.save_button")

    def _active(self, ctx):
        return [l for l in ctx.current_shipment.lines if l.status not in ("skipped", "failed")]

    @staticmethod
    def _ensure_all(ctx, n_lines: int) -> None:
        """More than 10 lines: show all rows (orderperpage = All) before locating rows."""
        a = ctx.actions
        if n_lines <= 10 or not a.exists("weight.orderperpage_select", timeout_ms=NEG):
            return
        if a.read_value("weight.orderperpage_select") == "100000":
            return
        try:
            with ctx.page.expect_navigation(wait_until="domcontentloaded", timeout=6000):
                a.select("weight.orderperpage_select", value="100000", label="All")
        except PlaywrightError:
            pass

    def _wvars(self, ctx, line):
        v = ctx.vars(line)
        row, _ = ctx.actions.resolve("weight.row", v, 4000)
        v["row_key"] = extract_row_key(row, "weight")
        return v

    def act(self, ctx: "FlowContext") -> None:
        a = ctx.actions
        lines = self._active(ctx)
        if not a.exists("weight.form", timeout_ms=NEG):
            a.click("pos.view_detail_button", expect_navigation=True)
        if not a.exists("weight.form", timeout_ms=8000):
            raise PostconditionFailed("weight page not shown", message_vi="Could not open the weight page", step_id=self.id)
        self._ensure_all(ctx, len(lines))
        for line in lines:
            v = self._wvars(ctx, line)
            a.fill("weight.row_weight_input", line.weight_text, v, dispatch_change=True)
            a.select("weight.row_um_select", label=ctx.config.flow.weight_um, vars=v)
            ctx.actions.resolve("weight.row_um_select", v)[0].dispatch_event("change")
        mark = _dialog_mark(ctx)
        ctx.dialogs.expect_accept(SAVE_CHANGES_CONFIRM)
        navigated = a.click("weight.save_button", expect_navigation=True, nav_timeout_ms=SAVE_NAV_TIMEOUT_MS)
        _after_save(ctx, navigated, "weights", self.id, mark)
        self._ensure_all(ctx, len(lines))   # the page may fall back to 10 rows after saving
        for line in lines:
            v = self._wvars(ctx, line)
            got = a.read_value("weight.row_weight_input", v)
            if _dec(got) != _dec(line.weight_text):   # the site echoes 1.00 back as "1.0"
                raise PostconditionFailed(f"weight not saved for {line.po_line.po_line_id}: {got!r}",
                                          message_vi=f"Weight of PO {line.po_line.po_line_id} was not saved", step_id=self.id)
            line.status = "weight_done"

    def check(self, ctx: "FlowContext") -> bool:
        return all(l.status == "weight_done" for l in self._active(ctx))


class S10FinishShipment(Step):
    id = "S10.finish_shipment"
    title_vi = "Finish shipment (waiting for your review)"
    selector_keys = ("weight.back_button", "pos.validate_button")

    def __init__(self, is_last: bool):
        self.is_last = is_last

    def act(self, ctx: "FlowContext") -> None:
        a, sh = ctx.actions, ctx.current_shipment
        if a.exists("weight.form", timeout_ms=NEG):
            a.click("weight.back_button", expect_navigation=True)
        if ctx.config.flow.click_validate:
            a.click("pos.validate_button", expect_navigation=True)
        ctx.results.write(ctx.plan)
        if not self.is_last and not ctx.config.flow.review_between_shipments:
            ctx.info(f"shipment {sh.index} done: Web Shipment ID {sh.web_shipment_id}")
        elif not self.is_last:
            ctx.ask("finished_review",
                    f"Shipment {sh.index}: Web Shipment ID {sh.web_shipment_id} has been created. Review it in the browser and click Submit ASN yourself when ready.",
                    options=["continue"], step_id=self.id)

    def check(self, ctx: "FlowContext") -> bool:
        return True
