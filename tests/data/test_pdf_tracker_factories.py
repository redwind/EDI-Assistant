"""PO tracker extracted from the PO PDF (Order Units empty -> EDI Units, Factory Name column) + factory list xlsx."""
from __future__ import annotations

from decimal import Decimal

import openpyxl

from edi_assistant.data import detect_header, extract_rows, load_grid, suggest_mapping
from edi_assistant.data.factories import FactoryStore, read_factories_xlsx

HEAD = ["Factory Name", "Delivery Address", "Container # ", "Shyft SO #", "Shyft PO #", "Master PO #", "Line #",
        "ASN #", "Model #", "Styles Description ", "Color", "Order Units", "Order Price ($)",
        "Order Cost (Units x Cost)", "EDI PO Start Ship", "EDI PO End Ship", "EDI Units", "Buyer's Price ($)",
        "Buyer's Cost (Units x Cost)", "Pack", "Transfer PO (w/ Dates)", "Pre Price Stickers (w/ Date)",
        "Gross Weight/Carton(kg)", "Submit ASN # (w/ Date)"]


def _tracker(tmp_path, order_units=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vendor "
    ws.append(HEAD)
    for i, (units, pack) in enumerate(((600, 6), (600, 12)), 1):
        row = dict.fromkeys(HEAD)
        row.update({"Factory Name": "Ningbo Bright Max Co., Ltd", "Delivery Address": "GA Savanah (SAV) DC",
                    "Shyft PO #": "P14277", "Master PO #": "6723460", "Line #": f"{i:02d}",
                    "Model #": f"ECO-{i}", "EDI PO Start Ship": "25-JAN-27", "EDI PO End Ship": "29-JAN-27",
                    "EDI Units": units, "Order Units": order_units, "Pack": pack, "Gross Weight/Carton(kg)": 1})
        ws.append([row[h] for h in HEAD])
    p = tmp_path / "tracker.xlsx"
    wb.save(p)
    return p


def _extract(p):
    g = load_grid(p, "Vendor ")
    det = detect_header(g)
    m, _ = suggest_mapping(det)
    return m, extract_rows(g, det, m)


def test_edi_units_give_the_cartons(tmp_path):
    m, rx = _extract(_tracker(tmp_path))
    assert m.profile == "po_tracker"
    assert m.columns["edi_units"].letter == "Q" and m.columns["factory"].letter == "A"
    assert [(ln.line, ln.quantity, ln.packages) for ln in rx.lines] == [(1, Decimal(600), Decimal(100)),
                                                                        (2, Decimal(600), Decimal(50))]
    assert all(not any(f.severity == "error" for f in ln.flags) for ln in rx.lines)
    assert rx.company_text == "Ningbo Bright Max Co., Ltd"


def test_edi_units_win_over_order_units(tmp_path):
    """Cartons = EDI Units (Q) / Pack (T), whatever Order Units (L) says."""
    _, rx = _extract(_tracker(tmp_path, order_units=300))
    assert [(ln.quantity, ln.packages) for ln in rx.lines] == [(Decimal(600), Decimal(100)), (Decimal(600), Decimal(50))]
    assert not any(f.code == "units_from_order" for ln in rx.lines for f in ln.flags)


def test_order_units_used_when_edi_units_empty(tmp_path):
    p = _tracker(tmp_path, order_units=300)
    wb = openpyxl.load_workbook(p)
    ws = wb["Vendor "]
    col = HEAD.index("EDI Units") + 1
    for r in (2, 3):
        ws.cell(r, col).value = None
    wb.save(p)
    _, rx = _extract(p)
    assert [(ln.quantity, ln.packages) for ln in rx.lines] == [(Decimal(300), Decimal(50)), (Decimal(300), Decimal(25))]
    assert all(any(f.code == "units_from_order" for f in ln.flags) for ln in rx.lines)


def _factories_xlsx(tmp_path, zip_code="315048"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Factories"
    ws.append(["Factory Name", "Address 1", "Address 2", "City", "State", "Zip", "Country", "Aliases", "Code",
               "Transportation Method", "SCAC Code", "Carrier", "Original Address", "To check"])
    ws.append(["Ningbo Bright Max Co., Ltd", "20F Building 1", "Xinming Street", "Ningbo", "ZJ", zip_code, "china",
               "Ningbo Bright Max; Bright Max", None, None, None, None, "x", None])
    ws.append(["Organizacion Reynera", "20 de Noviembre #1112", None, "Cadereyta Jimenez", "NL", 67480, "MEXICO",
               "Reynera", 2596, "LTL", "ABCD-SOME TRUCKING", None, None, None])
    ws.append([None] * 5)
    wb.create_sheet("How to use").append(["ignored"])
    p = tmp_path / "factories.xlsx"
    wb.save(p)
    return p


def test_read_factories_xlsx(tmp_path):
    items = read_factories_xlsx(_factories_xlsx(tmp_path))
    assert [f.name for f in items] == ["Ningbo Bright Max Co., Ltd", "Organizacion Reynera"]
    nb, rey = items
    assert nb.aliases == ["Ningbo Bright Max", "Bright Max"] and nb.country == "CHINA" and nb.zip == "315048"
    assert rey.zip == "67480" and rey.code == "2596" and rey.transport_method == "LTL" and rey.scac_code == "ABCD"


def test_merge_updates_by_name_and_keeps_ids(tmp_path):
    st = FactoryStore(tmp_path / "factories.json")
    assert st.merge(read_factories_xlsx(_factories_xlsx(tmp_path))) == (2, 0)
    ids = {f.name: f.id for f in st.list()}
    nb = st.get(ids["Ningbo Bright Max Co., Ltd"])
    nb.site_no = "SITE-1"
    st.upsert(nb)
    assert st.merge(read_factories_xlsx(_factories_xlsx(tmp_path, zip_code="999999"))) == (0, 2)
    again = {f.name: f for f in st.list()}
    assert {n: f.id for n, f in again.items()} == ids
    assert again["Ningbo Bright Max Co., Ltd"].zip == "999999"
    assert again["Ningbo Bright Max Co., Ltd"].site_no == "SITE-1"


def test_tracker_factory_matches_imported_list(tmp_path):
    st = FactoryStore(tmp_path / "factories.json")
    st.merge(read_factories_xlsx(_factories_xlsx(tmp_path)))
    _, rx = _extract(_tracker(tmp_path))
    f, score = st.suggest(rx.company_text)
    assert f is not None and f.name == "Ningbo Bright Max Co., Ltd" and score == 1.0
    assert st.by_file_code("2596 - Q4 tracker.xlsx").name == "Organizacion Reynera"
    assert st.by_file_code("tracker.xlsx") is None
