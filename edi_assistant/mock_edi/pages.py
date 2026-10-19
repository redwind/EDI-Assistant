"""HTML rendering for the mock EDI Gateway. Layout uses divs (no nested layout tables)."""
from __future__ import annotations

from html import escape as _e

from .state import MockOrder, MockShipment, MockState

VENDOR = "SHYFT GLOBAL LLC"
CSS = """
body{font-family:Arial,sans-serif;font-size:13px;margin:8px}
.hdr{background:#234;color:#fff;padding:6px}.hdr a{color:#fff;margin-right:14px}
tr.stricken{text-decoration:line-through}.error{color:red;font-weight:bold}
table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:3px 6px}
.row{margin:4px 0}.row label{display:inline-block;min-width:160px}
"""


def e(v: object) -> str:
    return _e(str(v), quote=True)


def layout(title: str, body: str, tabs: bool = True) -> str:
    nav = ""
    if tabs:
        nav = ('<div class="hdr"><b>' + VENDOR + '</b> &nbsp; <a href="inbox.do">INBOX</a>'
               '<a href="outbox.do">OUTBOX</a><a href="drafts.do">SHIPMENTS</a></div>')
    return (f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>{e(title)}</title>"
            f"<style>{CSS}</style></head><body>{nav}{body}</body></html>")


# ---------------------------------------------------------------- login / profile
def login_page() -> str:
    body = ('<h3>Login</h3><form method="POST" action="login.do">'
            '<div class="row"><label for="userid">User ID</label>'
            '<input type="text" name="userid" id="userid" value="Grayson@shyftglobal.com"></div>'
            '<div class="row"><label for="password">Password</label>'
            '<input type="password" name="password" id="password"></div>'
            '<input type="submit" value="Go"></form>')
    return layout("Vendor Management Suite -- Login", body, tabs=False)


def profile_page() -> str:
    body = ('<div class="news">DC addresses have been changed... CA=512, NJ=053, GA=934</div>'
            '<h3>Search Vendor</h3><table><tr><th>Vendor</th></tr>'
            f'<tr><td><a href="vendor.do?vendor_id=1&amp;profile">{VENDOR}</a></td></tr></table>')
    return layout("Vendor Management Suite -- Select Profile", body, tabs=False)


def vendor_page() -> str:
    body = (f'<h3>{VENDOR}</h3><form action="gateway/inbox.do" method="GET">'
            '<input type="submit" value="EDI Gateway"></form>')
    return layout("Vendor Management Suite -- View Profile", body, tabs=False)


# ---------------------------------------------------------------- inbox
FILTERS = ("unread", "read", "submitted", "resubmitted", "replaced", "acknowledged",
           "notshipped", "fullyshipped", "partiallyshipped")


def inbox_page(state: MockState, doc_id: str | None) -> str:
    boxes = "".join(f'<label><input type="checkbox" name="filter_{f}" value="on"> {f}</label> ' for f in FILTERS)
    form = ('<form name="filterinbox" action="filter_inbox.do" method="GET"><div>' + boxes + '</div>'
            '<div class="row"><label for="documentID">Document ID</label>'
            f'<input type="text" name="documentID" id="documentID" value="{e(doc_id or "")}"></div>'
            '<div class="row"><label for="start_date">Start Date</label><input type="text" name="start_date" id="start_date">'
            '<label for="end_date">End Date</label><input type="text" name="end_date" id="end_date"></div>'
            '<select name="orderperpage"><option>10</option><option>25</option></select> '
            '<input type="submit" value="Search"> <input type="button" name="reset" value="Reset"></form>')
    rows = []
    n = 0
    for o in state.orders.values():
        if doc_id and o.po_line_id != doc_id.strip():
            continue
        for v in range(o.versions):
            n += 1
            last = v == o.versions - 1
            replaced = (not last) or o.status == "REPLACED"
            status = "REPLACED" if replaced else o.status
            oid = o.order_id if last else o.order_id * 100 + v
            cls = "odd" if n % 2 else "even"
            if replaced:
                cls += " stricken"
            elif not o.read:
                cls += " unviewed"
            ship = "Not Shipped"
            rows.append(
                f'<tr class="{cls}"><td>{n}</td><td>{"R" if o.read else "U"}</td><td><a href="#">850</a></td>'
                f'<td><a href="view_order.do?order_id={oid}&amp;orderNo={o.po_line_id}">{o.po_line_id}</a></td>'
                f'<td>10-JAN-26</td><td>{status}</td><td>{ship}</td>'
                '<td>[<a href="new_shipment.do">New Shipment</a>]</td></tr>')
    heads = "".join(f"<th>{h}</th>" for h in
                    ("#", "Read", "Type", "Document ID", "Transmission Date", "Status", "Shipment Status", "Turn Around"))
    table = f'<table id="inboxTable"><tr>{heads}</tr>{"".join(rows)}</table>'
    return layout("Vendor Management Suite -- EDI Gateway Inbox", form + table)


def view_order_page(o: MockOrder, oid: str, dates_in_pdf: bool) -> str:
    head = (f'<div>850 - Purchase Order : <b>{o.po_line_id}</b> | {o.status} | Not Shipped</div>'
            '<div><a href="inbox.do">&lt;&lt; Return To Order List</a> '
            f'<a href="new_shipment.do?orderNo={o.po_line_id}">Create New Shipment</a></div>')
    if dates_in_pdf:
        body = f'<iframe src="order_pdf.do?order_id={e(oid)}" width="800" height="600"></iframe>'
    else:
        a = o.site_addr
        body = ('<div id="poSummary"><table>'
                '<tr><td>Order Date</td><td>10-JAN-26</td></tr>'
                f'<tr><td>Early Ship Date</td><td>{o.early}</td></tr>'
                f'<tr><td>Late Ship Date</td><td>{o.late}</td></tr>'
                f'<tr><td>Destination</td><td>{a[1]}, {a[2]} WAREHOUSE {a[0]} {a[1]} {a[2]} {a[3]}</td></tr>'
                '</table></div>')
    return layout("Vendor Management Suite -- View Order", head + body)


def order_pdf_lines(o: MockOrder) -> list[str]:
    a = o.site_addr
    return ["Bill To Burlington Merchandising Corp.", "Order Date Early Ship Date Late Ship Date",
            f"10-JAN-26 {o.early} {o.late}", f"Destination {a[1]} {a[2]} WAREHOUSE {a[0]} {a[3]}"]


def drafts_page(state: MockState) -> str:
    rows = "".join(
        f'<tr><td><a href="new_shipment.do?readyForLabels=N&amp;shipment_id={s.shipment_id}&amp;ReadOnly=false">'
        f'{s.shipment_id}</a></td><td>10-JAN-26</td><td>CREATED</td><td>Shipment Created Ready To Add PO</td></tr>'
        for s in state.shipments.values())
    table = ('<table><tr><th>Shipment ID</th><th>Create Date</th><th>Status</th><th>State</th></tr>'
             + rows + '</table>')
    return layout("BCF EDI Gateway -- Drafts", table)


# ---------------------------------------------------------------- shipment header
SHIPPING_TYPES = (("0", "Select One"), ("1", "Pack by store and ship to DC"), ("2", "Drop ship to the stores"),
                  ("3", "Ship to DC"), ("4", "Direct to customer"))
TRANS = (("", "Select One"), ("O", "Containerized Ocean"), ("S", "Ocean"), ("A", "Air"),
         ("M", "Motor (Common Carrier)"), ("LT", "LTL"))
SCACS = (("", "Select One"), ("MAEU", "MAEU-MAERSK"), ("UNKN", "UNKN-UNKNOWN"), ("CMDU", "CMDU-CMA CGM"))
COUNTRY_TEXT = {"US": "UNITED STATES", "CA": "CANADA", "CN": "CHINA"}
REQUIRED = (("txtFromName", "Name"), ("txtFromAddress1", "Address 1"), ("txtFromCity", "City"),
            ("txtFromState", "State"), ("txtFromZip", "Zip"), ("OptShippingType", "Shipping Type"),
            ("txtShippingDate", "Shipping Date"), ("OptTransMethod", "Transportation Method"),
            ("OptSCACCode", "SCAC Code"))


def _opts(options, sel: str) -> str:
    return "".join(f'<option value="{e(v)}"{" selected" if v == sel else ""}>{e(t)}</option>' for v, t in options)


def _txt(name: str, v: dict, label: str = "", ident: bool = True, ro: bool = False, extra: str = "") -> str:
    idattr = f' id="{name}"' if ident else ""
    lab = f'<label for="{name}">{label}</label>' if (label and ident) else (f"<label>{label}</label>" if label else "")
    return (f'<div class="row">{lab}<input type="text" name="{name}"{idattr} value="{e(v.get(name, ""))}"'
            f'{" readonly" if ro else ""} {extra}></div>')


def shipment_page(state: MockState, countries: tuple[str, ...], sh: MockShipment | None,
                  order: MockOrder | None, error: str = "", posted: dict | None = None) -> str:
    v: dict[str, str] = dict(sh.header) if sh else {}
    if posted:
        v.update(posted)
    sid = str(sh.shipment_id) if sh else ""
    if order and not v.get("optToSiteNo"):
        a = order.site_addr
        v.update({"optToSiteNo": order.site_no, "txtToName": "BURLINGTON DC", "txtToAddress1": a[0],
                  "txtToCity": a[1], "txtToState": a[2], "txtToZip": a[3], "txtToCountryUnHidden": "US"})
    v["txtWebShipmentId"] = sid
    v["txtASNId"] = sid
    carrier = v.get("txtcarrier", "")
    if not carrier and v.get("OptSCACCode"):
        carrier = dict(SCACS).get(v["OptSCACCode"], "").split("-", 1)[-1]
    v["txtcarrier"] = carrier
    ctry = "".join(f'<option value="{c}"{" selected" if v.get("txtFromCountry") == c else ""}>'
                   f'{COUNTRY_TEXT.get(c, c)}</option>' for c in countries)
    chk = "".join(f'<input type="radio" name="CartonRadio" value="{x}"{" checked" if v.get("CartonRadio") == x else ""}>{x} '
                  for x in ("Y", "N"))
    req_js = ";".join(f"if(!f.{n}.value||f.{n}.value=='0'){{alert('Please enter {m}');return false}}" for n, m in REQUIRED)
    script = ("<script>function setCarrier(){var s=document.getElementById('OptSCACCode');"
              "var t=s.options[s.selectedIndex].text;document.getElementsByName('txtcarrier')[0].value="
              "t.indexOf('-')>=0?t.split('-').slice(1).join('-'):'';}"
              "function DirtyFlag(){}function checkform(f){" + req_js + ";return true}"
              "function setNext(x){document.getElementById('nextField').value=x}</script>")
    asn_dis = "" if sh else " disabled"
    err = f'<div><span class="error">{e(error)}</span></div>' if error else ""
    form = (
        script + err +
        '<form name="new_shipment" id="new_shipment" method="POST" action="new_shipment.do" onsubmit="return checkform(this)">'
        f'<input type="hidden" name="action" value=""><input type="hidden" name="shipment_id" value="{sid}">'
        '<input type="hidden" name="Dirty_Flag" value="N"><input type="hidden" name="AddUpdate" value="Update">'
        '<input type="hidden" name="next" id="nextField" value="">'
        + _txt("txtWebShipmentId", v, "Web Shipment ID", ro=True) + _txt("txtASNId", v, "ASN Shipment ID")
        + f'<div class="row"><label>Shipment With Cartons</label>{chk}</div>'
        '<div class="row"><label for="OptShippingType">Shipping Type</label>'
        f'<select name="OptShippingType" id="OptShippingType">{_opts(SHIPPING_TYPES, v.get("OptShippingType", "0"))}</select></div>'
        + _txt("txtShippingDate", v, "Shipping Date", extra='placeholder="MM/DD/YYYY"')
        + '<div class="row"><label for="OptTransMethod">Transportation Method</label>'
        f'<select name="OptTransMethod" id="OptTransMethod">{_opts(TRANS, v.get("OptTransMethod", ""))}</select></div>'
        '<div class="row"><label for="OptSCACCode">SCAC Code</label>'
        f'<select name="OptSCACCode" id="OptSCACCode" onchange="setCarrier();DirtyFlag()">{_opts(SCACS, v.get("OptSCACCode", ""))}</select></div>'
        + _txt("txtcarrier", v, "Carrier", ident=False, ro=True)
        + _txt("txtBillLading", v, "Bill Of Lading", ident=False) + _txt("txtPRONumber", v, "PRO Number", ident=False)
        + '<div class="row"><label>UPS Shipment</label><input type="checkbox" name="chkShipment" value="Y"></div>'
        '<div class="row"><label>From Site No</label><select name="OptSiteNO">'
        '<option value="">Select One</option><option value="ADD">Add New Address</option></select></div>'
        + _txt("txtSiteNO", v, ident=False)
        + _txt("txtFromName", v, "From Name") + _txt("txtFromAddress1", v, "From Address 1")
        + _txt("txtFromAddress2", v, ident=False) + _txt("txtFromCity", v, "From City")
        + _txt("txtFromState", v, "From State") + _txt("txtFromZip", v, "From Zip")
        + '<div class="row"><label for="txtFromCountry">From Country</label>'
        f'<select name="txtFromCountry" id="txtFromCountry">{ctry}</select> '
        '<a href="#" onclick="alert(\'More countries popup (mock)\');return false">More..</a></div>'
        + _txt("optToSiteNo", v, ident=False, ro=True)
        + "".join(_txt(n, v, ident=False, ro=True) for n in
                  ("txtToName", "txtToAddress1", "txtToAddress2", "txtToCity", "txtToState", "txtToZip", "txtToCountryUnHidden"))
        + '<div class="row"><input type="button" value="&lt;&lt; Back To Drafts" onclick="location=\'drafts.do\'"> '
        '<input type="reset" name="btnCancel" value="Clear Values"> '
        '<input type="submit" id="submit123" value="Selected Purchase Orders &gt;&gt;" onclick="setNext(\'pos\')"> '
        '<input type="submit" id="saveonly" value="Save" onclick="setNext(\'\')"> '
        '<input type="button" id="cancelShipment" value="Cancel" '
        'onclick="if(confirm(\'Do you want to cancel this shipment?\')) location=\'cancel_shipment.do\'"> '
        '<input type="button" name="label" value="Label" disabled> '
        '<input type="button" name="validateShipment" value="Validate"> '
        f'<input type="button" name="btnSubmitASN" value="Submit ASN" onclick="document.location.href=\'asn.do?shipment_id={sid}\'"{asn_dis}>'
        '</div></form>')
    return layout("Vendor Management Suite -- Shipment", form)


# ---------------------------------------------------------------- selected POs
def _pos_tabs(sid: int) -> str:
    return (f'<div class="row"><a href="selected_pos.do?shipment_id={sid}">Selected Purchase Orders</a> | '
            f'<a href="selected_pos.do?shipment_id={sid}&amp;tab=search">Search Purchase Orders</a></div>')


def _breadcrumb(sid: int) -> str:
    return f'<div>Web Shipment ID: <a href="new_shipment.do?shipment_id={sid}&amp;ReadOnly=false">{sid}</a> &gt;&gt; Selecting Purchase Orders</div>'


def _bottom(sid: int) -> str:
    return ('<div class="row"><input type="button" value="&lt;&lt; Back To Shipment Header" '
            f'onclick="location=\'new_shipment.do?shipment_id={sid}&amp;ReadOnly=false\'"> '
            f'<input type="button" name="poSiteShipment" value="View Shipment Orders Detail" onclick="location=\'po_site_shipment.do?shipment_id={sid}\'"> '
            '<input type="button" name="validateShipment" value="Validate Shipment"> '
            f'<input type="button" name="btnSubmitASN" value="Submit ASN" onclick="document.location.href=\'asn.do?shipment_id={sid}\'"></div>')


def selected_pos_page(state: MockState, sh: MockShipment, tab: str, po_filter: str) -> str:
    sid = sh.shipment_id
    head = _breadcrumb(sid) + _pos_tabs(sid)
    if tab == "search":
        rows = []
        for o in state.orders.values():
            if o.po_line_id in sh.pos or (po_filter and po_filter not in o.po_line_id):
                continue
            st = "Replaced" if o.status == "REPLACED" else "Available"
            rows.append(f'<tr><td><input type="checkbox" name="selPo" value="{o.po_line_id}"></td>'
                        f'<td><a href="#">{o.po_line_id}</a></td><td>{st}</td></tr>')
        body = (f'<form method="GET" action="selected_pos.do"><input type="hidden" name="shipment_id" value="{sid}">'
                '<input type="hidden" name="tab" value="search">'
                '<div class="row"><label for="purchaseOrderNo">Purchase Order No</label>'
                f'<input type="text" name="purchaseOrderNo" id="purchaseOrderNo" value="{e(po_filter)}"></div>'
                '<select name="status"><option>Available</option></select> '
                '<input type="submit" value="Search"> <input type="reset" value="Reset"></form>'
                f'<form method="POST" action="selected_pos_add.do"><input type="hidden" name="shipment_id" value="{sid}">'
                '<table><tr><th>All None</th><th>Purchase Order No</th><th>Status</th></tr>' + "".join(rows) + '</table>'
                '<input type="submit" value="Add Selected" onclick="return confirm(\'Do you want to add the selected Purchase Orders ?\')"> '
                '<input type="button" value="Cancel"></form>')
    else:
        rows = []
        for po, d in sh.pos.items():
            n = d["po_header_id"]
            cp = "".join(f'<option value="{x}"{" selected" if d["complete_partial"] == x else ""}>{x}</option>'
                         for x in ("Complete", "Partial"))
            packs = (("CTN25", "Corrugated or Solid Carton"), ("CTN01", "Carton 01"), ("BAG01", "Bag"), ("PLT01", "Pallet"))
            pk = "".join(f'<option value="{v}"{" selected" if d["pack_code"] == v else ""}>{t}</option>' for v, t in packs)
            rows.append(
                f'<tr><td><input type="checkbox" name="PO-{n}"></td><td><a href="#">{po}</a></td><td>{d["status"]}</td>'
                f'<td><select name="complete_shipment_{n}">{cp}</select></td>'
                f'<td><select name="web_sh_packing_type_id_{n}" disabled><option value="0">Select One</option>'
                f'<option value="6" selected>Customized quantities and cartons</option></select></td>'
                f'<td><select name="pack_code_{n}" id="pack_code">{pk}</select></td>'
                f'<td><input type="button" value="Save" onclick="saveCarton(\'saveCarton\', {n}, \'{po}\', \'Y\')"> '
                f'<input type="button" value="Create Carton" onclick="insertCarton(\'insertCarton\', {n}, \'{po}\', \'Y\')"></td></tr>')
        hidden = "".join(f'<input type="hidden" name="{h}" value="">' for h in
                         ("action", "poHeaderID", "purchaseOrderNo", "packaging_code", "cart_def_id", "site", "webShOrdId",
                          "webShOrdAddr", "packing_type", "complete_partial", "carton_definition_name", "required",
                          "selectedCartId", "isCustomizedPage", "savepo"))
        js = ("<script>function saveCarton(a,n,po,y){var f=document.createElement('form');f.method='POST';"
              "f.action='selected_pos_save.do';function add(k,v){var i=document.createElement('input');i.type='hidden';"
              "i.name=k;i.value=v;f.appendChild(i)}add('shipment_id','" + str(sid) + "');add('poHeaderID',n);add('po',po);"
              "add('complete_partial',document.getElementsByName('complete_shipment_'+n)[0].value);"
              "add('packaging_code',document.getElementsByName('pack_code_'+n)[0].value);document.body.appendChild(f);f.submit()}"
              "function insertCarton(a,n,po,y){location='carton.do?shipment_id=" + str(sid) + "&po='+po}</script>")
        heads = "".join(f"<th>{h}</th>" for h in ("", "Purchase Order", "Status", "Complete/Partial", "Packing Type", "Packaging Code", ""))
        body = (js + f'<form name="form1" method="POST" action="selected_pos.do"><input type="hidden" name="webshipmentId" value="{sid}">'
                + hidden + f'<table><tr>{heads}</tr>{"".join(rows)}</table></form>')
    return layout("BCF EDI Gateway -- Selected Purchase Orders", head + body + _bottom(sid))


# ---------------------------------------------------------------- carton page
def carton_page(state: MockState, sh: MockShipment, po: str, itab: str, stab: str, error: str) -> str:
    sid = sh.shipment_id
    o = state.orders[po]
    c = sh.cartons[po]
    lab = o.item_label
    crumb = (f'<h3>Create Carton Definition : Customized quantities and cartons</h3><div>Web Shipment ID: {sid} &gt;&gt; '
             f'Purchase Order: {po} &gt;&gt; Carton Definition: {c["cart_def_id"]}</div>')
    err = f'<div><span class="error">{e(error)}</span></div>' if error else ""
    base = f"carton.do?shipment_id={sid}&amp;po={po}"
    main = [f'<form name="cartonForm" method="POST" action="carton_save.do"><input type="hidden" name="shipment_id" value="{sid}">'
            f'<input type="hidden" name="po" value="{po}">']
    # items block
    main.append(f'<div class="row"><a href="{base}">Selected Items</a> | <a href="{base}&amp;itab=search">Search Items</a></div>')
    if itab != "search":
        if c["items_added"]:
            pk = "".join(f'<option value="{v}"{" selected" if c["packaging_code"] == v else ""}>{t}</option>' for v, t in
                         (("", "Select One"), ("PCC", "Physical Container - Carton"), ("PLT", "Pallet"), ("BAG", "Bag")))
            um = "AS" if (o.prepack and not o.ordered_in_packs) else "EA"
            heads = "".join(f"<th>{h}</th>" for h in ("All None", "Sku/Upc/Prepack", "Style", "Color/Size", "Qty Ordered",
                                                      "Qty Per Carton", "Unit of Measure"))
            row = (f'<tr><td><input type="checkbox"></td><td><a href="#">{lab}</a></td><td>RCS310DUC2</td><td>TEAL/M</td>'
                   f'<td>{o.qty_ordered}</td><td><input type="text" name="qty_per_carton_1" size="5" value="{e(c["qty_per_carton"])}"></td>'
                   f'<td>{um}</td></tr>')
            if o.prepack and not o.ordered_in_packs:
                row += (f'<tr class="prepack"><td></td><td>46602776 RCS310DUC2</td><td>TEALIIIIIIA0/QTY</td>'
                        f'<td>{o.prepack}</td><td></td><td>EA</td></tr>')
            main.append('<div class="row"><label for="carton_definition_name">Carton Name</label>'
                        f'<input type="text" name="carton_definition_name" id="carton_definition_name" value="CARTON 1"> '
                        f'<label for="packaging_code">Packaging Code</label><select name="packaging_code" id="packaging_code">{pk}</select> '
                        '<input type="submit" value="Save"> <input type="button" value="Undo"></div>'
                        f'<table><tr>{heads}</tr>{row}</table>')
        else:
            main.append("<div>No items selected</div>")
    # sites block
    main.append(f'<div class="row"><a href="{base}">Selected Sites</a> | <a href="{base}&amp;stab=search">Search Sites</a></div>')
    if stab != "search":
        if c["sites_added"]:
            heads = "".join(f"<th>{h}</th>" for h in ("All None", "State", "City", "Site No", "Site Name/Address", "Cartons Per Site"))
            a = o.site_addr
            main.append(f'<table><tr>{heads}</tr><tr><td><input type="checkbox"></td><td>{a[2]}</td><td>{a[1]}</td>'
                        f'<td><a href="#">{o.site_no}</a></td><td>{a[0]}</td>'
                        f'<td><input type="text" name="cartons_per_site_{o.site_no}" size="5" value="{e(c["cartons_per_site"])}"></td></tr></table>')
        else:
            main.append("<div>No sites selected</div>")
    main.append(f'<div class="row"><input type="button" value="&lt;&lt; Back to Purchase Order" '
                f'onclick="location=\'selected_pos.do?shipment_id={sid}\'"> '
                '<input type="button" value="Auto populate Qty (Carton &amp; Site)"> '
                '<input type="button" value="Auto populate Qty (Site)"> <input type="submit" value="Save"> '
                '<input type="button" value="Undo"></div></form>')
    out = crumb + err + "".join(main)
    if itab == "search":
        heads = "".join(f"<th>{h}</th>" for h in ("All None", "SKU No", "UPC", "Style", "Color", "Size", "UM", "Ordered", "Shipped"))
        out += (f'<form method="POST" action="carton_items_add.do"><input type="hidden" name="shipment_id" value="{sid}">'
                f'<input type="hidden" name="po" value="{po}"><table><tr>{heads}</tr>'
                f'<tr><td><input type="checkbox" name="selItem" value="1"></td><td colspan="8">{lab}</td></tr>'
                '<tr><td></td><td>46602776</td><td>0001</td><td>RCS310DUC2</td><td>TEAL</td><td>M</td>'
                f'<td>{"AS" if o.prepack else "EA"}</td><td>{o.qty_ordered}</td><td>0</td></tr></table>'
                '<input type="submit" value="Add Selected" onclick="return confirm(\'Do you want to add the selected Items ?\')"></form>')
    if stab == "search":
        heads = "".join(f"<th>{h}</th>" for h in ("All None", "Site", "Address", "City", "State", "Zip Code"))
        a = o.site_addr
        out += (f'<form method="POST" action="carton_sites_add.do"><input type="hidden" name="shipment_id" value="{sid}">'
                f'<input type="hidden" name="po" value="{po}"><table><tr>{heads}</tr>'
                f'<tr><td><input type="checkbox" name="selSite" value="{o.site_no}"></td><td>{o.site_no}</td><td>{a[0]}</td>'
                f'<td>{a[1]}</td><td>{a[2]}</td><td>{a[3]}</td></tr></table>'
                '<input type="submit" value="Add Selected" onclick="return confirm(\'Do you want to add the selected Sites ?\')"></form>')
    return layout("BCF EDI Gateway -- Carton Definition", out)


# ---------------------------------------------------------------- weight page
def weight_page(state: MockState, sh: MockShipment, per_page: int) -> str:
    sid = sh.shipment_id
    pp = "".join(f'<option value="{v}"{" selected" if v == per_page else ""}>{t}</option>'
                 for v, t in ((10, "10"), (15, "15"), (20, "20"), (25, "25"), (100000, "All")))
    rows = []
    for po, w in list(sh.weights.items())[:per_page]:
        o = state.orders[po]
        c = sh.cartons.get(po, {})
        try:
            lading = int(c.get("qty_per_carton") or 0) * int(c.get("cartons_per_site") or 0)
        except ValueError:
            lading = 0
        m = w["site_wgt_id"]
        um = "".join(f'<option value="{x}"{" selected" if w["um"] == x else ""}>{x}</option>' for x in ("KG", "LB"))
        a = o.site_addr
        rows.append(f'<tr><td><a href="#">{po}</a></td><td>{o.site_no}</td><td>{a[0]}</td><td>{a[1]}</td><td>{a[2]}</td>'
                    f'<td>{lading}</td><td><input type="text" name="editedSiteWgtqu{m}" id="editedSiteWgt{m}" value="{e(w["weight"])}" '
                    f'onchange="setHiddenOnChange({m})"></td><td><select name="editedSiteWgtum{m}" onchange="setHiddenOnChange({m})">{um}</select></td></tr>')
    heads = "".join(f"<th>{h}</th>" for h in ("PO #", "SITE", "ADDRESS", "CITY", "STATE", "LADING QUANTITY", "WEIGHT", "WEIGHT UM"))
    body = (f'<script>function setHiddenOnChange(m){{document.getElementsByName("editedElement")[0].value=m}}'
            f'function updateDD(){{}}</script>'
            f'<form name="po_site_shipment" method="POST" action="po_site_shipment_save.do">'
            f'<input type="hidden" name="shipment_id" value="{sid}"><input type="hidden" name="actionItemAdded" value="">'
            '<input type="hidden" name="editedElement" value="">'
            '<div class="row"><label>Change ALL Weight UM</label><select name="commonunit" onchange="updateDD()">'
            '<option value="">Select One</option><option>KG</option><option>LB</option></select> '
            '<label>Orders per page</label><select name="orderperpage" '
            f'onchange="location=\'po_site_shipment.do?shipment_id={sid}&amp;orderperpage=\'+this.value">{pp}</select> '
            '<a href="#">Set Weight for all PO\'s</a></div>'
            f'<table><tr>{heads}</tr>{"".join(rows)}</table>'
            '<input type="button" name="backtoorders" value="&lt;&lt; Back To Select Purchase Order" '
            f'onclick="location=\'selected_pos.do?shipment_id={sid}\'"> '
            '<input type="submit" name="SaveCarton2" value="Save"></form>')
    return layout("Vendor Management Suite -- Create User", body)


def asn_page() -> str:
    return layout("SUBMITTED", "<h3>ASN SUBMITTED (MOCK)</h3>")
