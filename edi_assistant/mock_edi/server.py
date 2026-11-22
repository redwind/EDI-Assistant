"""Routes and threaded HTTP server of the mock EDI Gateway (stdlib only)."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import pages
from .minipdf import make_pdf
from .state import MockOrder, MockShipment, MockState

ROOT = "/vms-gateway/"


@dataclass
class MockOptions:
    port: int = 8765
    require_login: bool = True        # first visit shows login page; "Go" with any password logs in
    dates_in_pdf: bool = False        # dates only inside an embedded PDF (iframe to order_pdf.do)
    prepack_pos: set[str] = field(default_factory=set)   # POs whose item has a prepack sub-row (N = 6)
    country_options: tuple[str, ...] = ("US", "CA", "CN")
    block_after_n_requests: int = 0   # >0: after N page requests every page request is blocked (anti-bot simulation)
    seed_tracker: bool = False        # add the nine PO-tracker POs (after seed_default)
    block_mode: str = "429"           # "429" (HTTP 429 Too Many Requests) | "access_denied" (HTTP 200 'Access Denied' page)


class _Redirect(Exception):
    def __init__(self, loc: str):
        self.loc = loc


class MockServer:
    def __init__(self, options: MockOptions | None = None, state: MockState | None = None):
        self.options = options or MockOptions()
        if state is None:
            state = MockState()
            state.seed_default()
            if self.options.seed_tracker:
                state.seed_tracker()
        elif self.options.seed_tracker:
            state.seed_tracker()
        self._state = state
        for po in self.options.prepack_pos:
            o = state.orders.get(po)
            if o is not None and not o.prepack:
                o.prepack = 6
        if not self.options.require_login:
            state.logged_in = True
            state.profile_selected = True
        self.lock = threading.RLock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = self.options.port

    @property
    def state(self) -> MockState:
        return self._state

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{ROOT}"

    def start(self) -> str:
        server = self

        class Handler(_Handler):
            srv = server

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.options.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="mock-edi", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # ------------------------------------------------------------------ routing
    def handle(self, method: str, path: str, query: dict[str, list[str]], form: dict[str, list[str]]):
        """Return (status, content_type, body_bytes). Raises _Redirect."""
        st, opt = self._state, self.options
        q = lambda k, d="": (query.get(k) or [d])[0]  # noqa: E731
        f = lambda k, d="": (form.get(k) or [d])[0]  # noqa: E731

        def html(s: str, code: int = 200):
            return code, "text/html; charset=utf-8", s.encode("utf-8")

        if not path.startswith(ROOT):
            return html("not found", 404)
        rel = path[len(ROOT):]
        if opt.block_after_n_requests > 0 and not rel.startswith("__"):
            st.request_count += 1
            if st.request_count > opt.block_after_n_requests:
                if opt.block_mode == "access_denied":
                    return html("<html><head><title>Access Denied</title></head><body><h1>Access Denied</h1>"
                                "<p>Unusual traffic detected.</p></body></html>")
                return html("<html><head><title>429</title></head><body><h1>Too Many Requests</h1></body></html>", 429)
        if rel == "__state":
            return 200, "application/json", json.dumps(st.snapshot()).encode()
        if rel == "__reset" and method == "POST":
            st.reset()
            st.seed_default()
            if opt.seed_tracker:
                st.seed_tracker()
            if not opt.require_login:
                st.logged_in = st.profile_selected = True
            return html("ok")
        if rel == "":
            raise _Redirect("login.do" if opt.require_login and not st.logged_in else "gateway/inbox.do")

        # ---- login / profile
        if rel == "login.do":
            if method == "POST":
                st.logged_in = True
                st.log.append("login")
                raise _Redirect("login.do?profile")
            if "profile" in query and st.logged_in:
                return html(pages.profile_page())
            return html(pages.login_page())
        if opt.require_login and not st.logged_in:
            raise _Redirect("login.do")
        if rel == "vendor.do":
            st.profile_selected = True
            return html(pages.vendor_page())
        if opt.require_login and not st.profile_selected:
            raise _Redirect("login.do?profile")

        # ---- gateway pages
        if rel in ("gateway/inbox.do", "gateway/filter_inbox.do", "gateway/outbox.do"):
            return html(pages.inbox_page(st, q("documentID") or None))
        if rel == "gateway/view_order.do":
            o = st.orders.get(q("orderNo"))
            if o is None:
                return html("no such order", 404)
            o.read = True
            return html(pages.view_order_page(o, q("order_id"), opt.dates_in_pdf))
        if rel == "gateway/order_pdf.do":
            o = next((x for x in st.orders.values() if str(x.order_id) == q("order_id")), None)
            if o is None:
                return html("no such order", 404)
            return 200, "application/pdf", make_pdf(pages.order_pdf_lines(o))
        if rel == "gateway/drafts.do":
            return html(pages.drafts_page(st))
        if rel == "gateway/new_shipment.do":
            return self._shipment(method, query, form, html)
        if rel == "gateway/selected_pos.do":
            sh = self._sh(q("shipment_id"))
            if sh is None:
                return html("no such shipment", 404)
            po_filter = q("purchaseOrderNo") or q("poNo")
            return html(pages.selected_pos_page(st, sh, q("tab"), po_filter))
        if rel == "gateway/selected_pos_add.do" and method == "POST":
            sh = self._sh(f("shipment_id"))
            if sh is None:
                return html("no such shipment", 404)
            for po in form.get("selPo", []):
                o = st.orders.get(po)
                if o is None or po in sh.pos:
                    continue
                sh.pos[po] = {"po_header_id": st.next_po_header_id, "complete_partial": "Complete",
                              "pack_code": "CTN25", "status": "Replaced" if o.status == "REPLACED" else "Available"}
                st.next_po_header_id += 1
                st.log.append(f"add_po {sh.shipment_id} {po}")
            raise _Redirect(f"selected_pos.do?shipment_id={sh.shipment_id}")
        if rel == "gateway/selected_pos_save.do" and method == "POST":
            sh = self._sh(f("shipment_id"))
            if sh is None:
                return html("no such shipment", 404)
            for po, d in sh.pos.items():
                if str(d["po_header_id"]) == f("poHeaderID"):
                    d["complete_partial"] = f("complete_partial", d["complete_partial"])
                    d["pack_code"] = f("packaging_code", d["pack_code"])
                    st.log.append(f"save_po {sh.shipment_id} {po} {d['complete_partial']}")
            raise _Redirect(f"selected_pos.do?shipment_id={sh.shipment_id}")
        if rel in ("gateway/carton.do", "gateway/carton_items_add.do", "gateway/carton_sites_add.do",
                   "gateway/carton_save.do"):
            return self._carton(rel, method, query, form, html)
        if rel == "gateway/po_site_shipment.do":
            sh = self._sh(q("shipment_id"))
            if sh is None:
                return html("no such shipment", 404)
            return html(pages.weight_page(st, sh, int(q("orderperpage", "10") or 10)))
        if rel == "gateway/po_site_shipment_save.do" and method == "POST":
            sh = self._sh(f("shipment_id"))
            if sh is None:
                return html("no such shipment", 404)
            for po, w in sh.weights.items():
                m = w["site_wgt_id"]
                if f"editedSiteWgtqu{m}" in form:
                    w["weight"] = f(f"editedSiteWgtqu{m}")
                    w["um"] = f(f"editedSiteWgtum{m}", w["um"])
                    st.log.append(f"weight {sh.shipment_id} {po} {w['weight']} {w['um']}")
            raise _Redirect(f"po_site_shipment.do?shipment_id={sh.shipment_id}")
        if rel == "gateway/asn.do":
            st.submit_called = True
            st.submit_attempts += 1
            st.log.append("SUBMIT ASN")
            return html(pages.asn_page())
        if rel == "gateway/cancel_shipment.do":
            st.shipments.pop(int(q("shipment_id", "0") or 0), None)
            st.log.append("cancel_shipment")
            raise _Redirect("drafts.do")
        return html("not found", 404)

    def _sh(self, sid: str) -> MockShipment | None:
        try:
            return self._state.shipments.get(int(sid))
        except (TypeError, ValueError):
            return None

    def _shipment(self, method, query, form, html):
        st = self._state
        q = lambda k, d="": (query.get(k) or [d])[0]  # noqa: E731
        if method == "GET":
            sh = self._sh(q("shipment_id"))
            order = st.orders.get(q("orderNo") or q("po_header_id"))   # real site: new_shipment.do?po_header_id=<PO line>
            return html(pages.shipment_page(st, self.options.country_options, sh, order))
        posted = {k: v[0] for k, v in form.items()}
        sh = self._sh(posted.get("shipment_id", ""))
        for key, label in pages.REQUIRED:
            if not posted.get(key) or (key == "OptShippingType" and posted[key] == "0"):
                return html(pages.shipment_page(st, self.options.country_options, sh, None,
                                                error=f"Please enter {label}", posted=posted))
        if sh is None:
            sh = MockShipment(shipment_id=st.next_shipment_id)
            st.next_shipment_id += 1
            st.shipments[sh.shipment_id] = sh
        sh.header = {k: v for k, v in posted.items() if k not in ("action", "AddUpdate", "next", "Dirty_Flag")}
        sh.header["txtWebShipmentId"] = sh.header["txtASNId"] = str(sh.shipment_id)
        st.log.append(f"save_header {sh.shipment_id}")
        if posted.get("next") == "pos":
            raise _Redirect(f"selected_pos.do?shipment_id={sh.shipment_id}")
        raise _Redirect(f"new_shipment.do?readyForLabels=N&shipment_id={sh.shipment_id}&ReadOnly=false")

    def _carton(self, rel, method, query, form, html):
        st = self._state
        q = lambda k, d="": (query.get(k) or [d])[0]  # noqa: E731
        f = lambda k, d="": (form.get(k) or [d])[0]  # noqa: E731
        src = form if method == "POST" else query
        sh = self._sh((src.get("shipment_id") or [""])[0])
        po = (src.get("po") or [""])[0]
        if sh is None or po not in sh.pos or po not in st.orders:
            return html("no such shipment/po", 404)
        c = sh.cartons.setdefault(po, {"cart_def_id": st.next_cart_def_id, "items_added": False, "sites_added": False,
                                       "packaging_code": "", "qty_per_carton": "", "cartons_per_site": "",
                                       "saved": False, "error": ""})
        if c["cart_def_id"] == st.next_cart_def_id:
            st.next_cart_def_id += 1
        back = f"carton.do?shipment_id={sh.shipment_id}&po={po}"
        o = st.orders[po]
        if rel == "gateway/carton.do":
            err, c["error"] = c["error"], ""
            return html(pages.carton_page(st, sh, po, q("itab"), q("stab"), err))
        if rel == "gateway/carton_items_add.do":
            c["items_added"] = True
            st.log.append(f"carton_items {po}")
        elif rel == "gateway/carton_sites_add.do":
            c["sites_added"] = True
            st.log.append(f"carton_sites {po}")
        else:  # carton_save.do
            qpc = f("qty_per_carton_1", c["qty_per_carton"])
            cps = f(f"cartons_per_site_{o.site_no}", c["cartons_per_site"])
            pk = f("packaging_code", c["packaging_code"])
            c.update(packaging_code=pk, qty_per_carton=qpc, cartons_per_site=cps, saved=False)
            err = ""
            try:
                nq, nc = int(qpc), int(cps)
            except ValueError:
                nq = nc = 0
            if not pk:
                err = "Please select Packaging Code"
            elif nq <= 0 or nc <= 0:
                err = "Please enter Qty Per Carton and Cartons Per Site"
            elif nq * nc > o.qty_ordered * (o.prepack or 1):
                err = "Quantity exceeds ordered"
            c["error"] = err
            if not err:
                c["saved"] = True
                if po not in sh.weights:
                    sh.weights[po] = {"weight": "", "um": "KG", "site_wgt_id": st.next_site_wgt_id}
                    st.next_site_wgt_id += 1
                st.log.append(f"carton_save {po} {pk} {qpc} {cps}")
        raise _Redirect(back)


class _Handler(BaseHTTPRequestHandler):
    srv: MockServer
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):  # silence
        pass

    def _serve(self, method: str):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query, keep_blank_values=True)
        form: dict[str, list[str]] = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(n).decode("utf-8", "replace"), keep_blank_values=True)
        try:
            with self.srv.lock:
                code, ctype, body = self.srv.handle(method, parts.path, query, form)
        except _Redirect as r:
            loc = r.loc if r.loc.startswith("/") else self._resolve(parts.path, r.loc)
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _resolve(path: str, rel: str) -> str:
        # login.do / vendor.do are at ROOT, everything else under gateway/
        if path.startswith(ROOT + "gateway/") and not rel.startswith("gateway/") and not rel.startswith("login.do"):
            return ROOT + "gateway/" + rel
        return ROOT + rel

    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")
