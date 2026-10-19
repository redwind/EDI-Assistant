"""Every mock route renders with the exact title and field names (no browser needed)."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import pypdf
import pytest

from edi_assistant.mock_edi import MockOptions, MockServer
from edi_assistant.mock_edi.minipdf import make_pdf


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


class Page(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.title = ""
        self.names: set[str] = set()
        self.ids: set[str] = set()
        self.values: list[str] = []
        self.texts: list[str] = []
        self._in_title = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "title":
            self._in_title = True
        if d.get("name"):
            self.names.add(d["name"])
        if d.get("id"):
            self.ids.add(d["id"])
        if tag == "input" and d.get("value"):
            self.values.append(d["value"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        self.texts.append(data)


def get(srv, rel, data=None):
    req = urllib.request.Request(srv.url + rel, data=urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None)
    try:
        r = OPENER.open(req)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def page(srv, rel, data=None) -> Page:
    code, _, body = get(srv, rel, data)
    assert code == 200, (rel, code)
    return Page(body.decode())


@pytest.fixture
def srv(mock_server):
    return mock_server


def test_login_flow_and_redirects(mock_server_login):
    s = mock_server_login
    code, h, _ = get(s, "")
    assert code == 302 and h["Location"].endswith("/vms-gateway/login.do")
    code, h, _ = get(s, "gateway/inbox.do")
    assert code == 302 and h["Location"].endswith("login.do")
    p = page(s, "login.do")
    assert p.title == "Vendor Management Suite -- Login"
    assert {"userid", "password"} <= p.names and "Go" in p.values and "Grayson@shyftglobal.com" in p.values
    code, h, _ = get(s, "login.do", {"userid": "u", "password": "x"})
    assert code == 302 and h["Location"].endswith("login.do?profile")
    p = page(s, "login.do?profile")
    assert p.title == "Vendor Management Suite -- Select Profile"
    assert any("SHYFT GLOBAL LLC" in t for t in p.texts) and any("CA=512" in t for t in p.texts)
    code, h, _ = get(s, "gateway/inbox.do")
    assert code == 302 and h["Location"].endswith("login.do?profile")
    p = page(s, "vendor.do?vendor_id=1&profile")
    assert p.title == "Vendor Management Suite -- View Profile" and "EDI Gateway" in p.values
    assert page(s, "gateway/inbox.do").title == "Vendor Management Suite -- EDI Gateway Inbox"


def test_inbox_filter_and_rows(srv):
    p = page(srv, "gateway/inbox.do")
    assert {"filterinbox", "documentID", "start_date", "end_date", "orderperpage", "reset", "filter_unread",
            "filter_partiallyshipped"} <= p.names and "inboxTable" in p.ids
    html = get(srv, "gateway/filter_inbox.do?documentID=580367401")[2].decode()
    assert html.count("view_order.do?order_id=") == 2          # 1 stricken version + 1 active
    assert 'class="even stricken"' in html or 'class="odd stricken"' in html
    assert "580367301" not in html
    assert "view_order.do" not in get(srv, "gateway/filter_inbox.do?documentID=5803674")[2].decode()   # 7 digits: nothing
    assert get(srv, "gateway/inbox.do")[2].decode().count("view_order.do") >= 6


def test_view_order_and_pdf(srv, mock_server_pdf):
    o = srv.state.orders["580367401"]
    p = page(srv, f"gateway/view_order.do?order_id={o.order_id}&orderNo=580367401")
    assert p.title == "Vendor Management Suite -- View Order"
    txt = " ".join(p.texts)
    assert "09-MAR-26" in txt and "13-MAR-26" in txt and "Create New Shipment" in txt and "Return To Order List" in txt
    assert o.read is True
    o2 = mock_server_pdf.state.orders["580367401"]
    html = get(mock_server_pdf, f"gateway/view_order.do?order_id={o2.order_id}&orderNo=580367401")[2].decode()
    assert "09-MAR-26" not in html and "order_pdf.do?order_id=" in html
    code, h, body = get(mock_server_pdf, f"gateway/order_pdf.do?order_id={o2.order_id}")
    assert code == 200 and h["Content-Type"] == "application/pdf" and body.startswith(b"%PDF")
    text = pypdf.PdfReader(io.BytesIO(body)).pages[0].extract_text()
    assert "Early Ship Date" in text and "09-MAR-26" in text and "13-MAR-26" in text


def test_minipdf_roundtrip():
    text = pypdf.PdfReader(io.BytesIO(make_pdf(["Hello (World) \\ x", "line two"]))).pages[0].extract_text()
    assert "Hello (World)" in text and "line two" in text


def _header_form(**over):
    d = {"shipment_id": "", "AddUpdate": "Update", "next": "", "CartonRadio": "Y", "OptShippingType": "3",
         "txtShippingDate": "03/11/2026", "OptTransMethod": "O", "OptSCACCode": "MAEU", "txtcarrier": "MAERSK",
         "txtBillLading": "Unknown", "txtPRONumber": "Unknown", "txtFromName": "N", "txtFromAddress1": "A",
         "txtFromCity": "C", "txtFromState": "S", "txtFromZip": "Z", "txtFromCountry": "CN", "optToSiteNo": "512"}
    d.update(over)
    return d


def test_shipment_header_routes(srv):
    p = page(srv, "gateway/new_shipment.do?orderNo=580367401")
    assert p.title == "Vendor Management Suite -- Shipment"
    for n in ("new_shipment", "CartonRadio", "OptShippingType", "OptTransMethod", "OptSCACCode", "txtcarrier", "txtBillLading",
              "txtPRONumber", "chkShipment", "OptSiteNO", "txtSiteNO", "txtFromName", "txtFromAddress1", "txtFromAddress2",
              "txtFromCity", "txtFromState", "txtFromZip", "txtFromCountry", "optToSiteNo", "txtToName", "txtToAddress1",
              "txtToAddress2", "txtToCity", "txtToState", "txtToZip", "txtToCountryUnHidden", "btnCancel", "label",
              "validateShipment", "btnSubmitASN", "action", "shipment_id", "Dirty_Flag", "AddUpdate"):
        assert n in p.names, n
    for i in ("txtWebShipmentId", "txtASNId", "txtShippingDate", "submit123", "saveonly", "cancelShipment", "txtFromName"):
        assert i in p.ids, i
    assert "512" in p.values
    # server-side required validation, then success
    code, _, body = get(srv, "gateway/new_shipment.do", _header_form(txtFromName=""))
    assert code == 200 and "Please enter Name" in body.decode()
    assert srv.state.shipments == {}
    code, h, _ = get(srv, "gateway/new_shipment.do", _header_form())
    assert code == 302 and "shipment_id=792872" in h["Location"] and "ReadOnly=false" in h["Location"]
    code, h, _ = get(srv, "gateway/new_shipment.do", _header_form(shipment_id="792872", next="pos"))
    assert code == 302 and h["Location"].endswith("selected_pos.do?shipment_id=792872")
    assert len(srv.state.shipments) == 1
    p = page(srv, "gateway/new_shipment.do?readyForLabels=N&shipment_id=792872&ReadOnly=false")
    assert "792872" in p.values and "MAERSK" in p.values
    assert page(srv, "gateway/drafts.do").title == "BCF EDI Gateway -- Drafts"


def _make_shipment(srv):
    get(srv, "gateway/new_shipment.do", _header_form(optToSiteNo="512"))
    return "792872"


def test_pos_carton_weight_routes(srv):
    sid = _make_shipment(srv)
    p = page(srv, f"gateway/selected_pos.do?shipment_id={sid}")
    assert p.title == "BCF EDI Gateway -- Selected Purchase Orders" and any("Selecting Purchase Orders" in t for t in p.texts)
    assert "form1" in p.names and "poSiteShipment" in p.names and "btnSubmitASN" in p.names
    p = page(srv, f"gateway/selected_pos.do?shipment_id={sid}&tab=search&purchaseOrderNo=580367401")
    assert "purchaseOrderNo" in p.names and "selPo" in p.names and "Add Selected" in p.values
    assert get(srv, "gateway/selected_pos_add.do", {"shipment_id": sid, "selPo": ["580367401", "580367402"]})[0] == 302
    p = page(srv, f"gateway/selected_pos.do?shipment_id={sid}")
    sh = srv.state.shipments[792872]
    n = sh.pos["580367401"]["po_header_id"]
    assert {f"complete_shipment_{n}", f"pack_code_{n}", f"web_sh_packing_type_id_{n}", f"PO-{n}"} <= p.names
    assert sh.pos["580367402"]["status"] == "Replaced"
    get(srv, "gateway/selected_pos_save.do", {"shipment_id": sid, "poHeaderID": n, "complete_partial": "Partial", "packaging_code": "CTN25"})
    assert sh.pos["580367401"]["complete_partial"] == "Partial"
    # carton
    p = page(srv, f"gateway/carton.do?shipment_id={sid}&po=580367401")
    assert p.title == "BCF EDI Gateway -- Carton Definition"
    page(srv, f"gateway/carton.do?shipment_id={sid}&po=580367401&itab=search")
    get(srv, "gateway/carton_items_add.do", {"shipment_id": sid, "po": "580367401"})
    get(srv, "gateway/carton_sites_add.do", {"shipment_id": sid, "po": "580367401"})
    p = page(srv, f"gateway/carton.do?shipment_id={sid}&po=580367401")
    assert {"carton_definition_name", "packaging_code", "qty_per_carton_1", "cartons_per_site_512"} <= p.names
    # invalid then valid save
    get(srv, "gateway/carton_save.do", {"shipment_id": sid, "po": "580367401", "packaging_code": "", "qty_per_carton_1": "6",
                                         "cartons_per_site_512": "85"})
    assert "Packaging Code" in get(srv, f"gateway/carton.do?shipment_id={sid}&po=580367401")[2].decode()
    get(srv, "gateway/carton_save.do", {"shipment_id": sid, "po": "580367401", "packaging_code": "PCC", "qty_per_carton_1": "7",
                                         "cartons_per_site_512": "85"})
    assert "exceeds" in get(srv, f"gateway/carton.do?shipment_id={sid}&po=580367401")[2].decode()
    get(srv, "gateway/carton_save.do", {"shipment_id": sid, "po": "580367401", "packaging_code": "PCC", "qty_per_carton_1": "6",
                                         "cartons_per_site_512": "85"})
    assert sh.cartons["580367401"]["saved"] is True
    # weights
    p = page(srv, f"gateway/po_site_shipment.do?shipment_id={sid}")
    assert p.title == "Vendor Management Suite -- Create User"
    m = sh.weights["580367401"]["site_wgt_id"]
    assert {"po_site_shipment", "commonunit", "orderperpage", f"editedSiteWgtqu{m}", f"editedSiteWgtum{m}", "backtoorders",
            "SaveCarton2"} <= p.names
    get(srv, "gateway/po_site_shipment_save.do", {"shipment_id": sid, f"editedSiteWgtqu{m}": "12.50", f"editedSiteWgtum{m}": "KG"})
    assert sh.weights["580367401"]["weight"] == "12.50"


def test_asn_state_reset_cancel(srv):
    p = page(srv, "gateway/asn.do?shipment_id=1")      # only reachable by raw HTTP, never by the automation
    assert p.title == "SUBMITTED" and srv.state.submit_called and srv.state.submit_attempts == 1
    snap = json.loads(get(srv, "__state")[2])
    assert snap["submit_called"] is True and "580367401" in snap["orders"]
    assert get(srv, "__reset", {})[0] == 200
    assert srv.state.submit_called is False and "580367401" in srv.state.orders
    sid = _make_shipment(srv)
    assert get(srv, f"gateway/cancel_shipment.do?shipment_id={sid}")[0] == 302
    assert srv.state.shipments == {}
    assert get(srv, "nope.do")[0] == 404


def test_country_options_and_prepack_option():
    s = MockServer(MockOptions(port=0, require_login=False, country_options=("US", "CN"), prepack_pos={"580367401"}))
    s.start()
    try:
        html = get(s, "gateway/new_shipment.do")[2].decode()
        assert "CANADA" not in html and "CHINA" in html
        assert s.state.orders["580367401"].prepack == 6
    finally:
        s.stop()


def test_seed_tracker_pages():
    srv = MockServer(MockOptions(port=0, require_login=False, seed_tracker=True))
    srv.start()
    try:
        st = srv.state
        ids = ["582067801", "582067802", "582068001", "582068002", "582068201", "582067701", "582067702",
               "582067901", "582068401"]
        assert all(i in st.orders for i in ids) and st.orders["582068401"].prepack == 6
        assert st.orders["582067701"].early == "09-NOV-26" and st.orders["582067701"].late == "13-NOV-26"
        _, _, inbox = get(srv, "gateway/inbox.do")
        inbox = inbox.decode()
        assert all(i in inbox for i in ids)
    finally:
        srv.stop()
