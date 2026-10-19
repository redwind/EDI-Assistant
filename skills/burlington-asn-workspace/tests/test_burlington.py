import datetime as dt
import os
import sys

import openpyxl
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "burlington-asn", "scripts"))
SAMPLE = os.path.join(ROOT, "..", "docs", "5803674 & 5803673 PKL.xlsx")

import parse_packing_list as pp  # noqa: E402
import plan_shipment as ps  # noqa: E402
import factories as fa  # noqa: E402
import write_asn as wa  # noqa: E402

TRACKER = os.path.join(ROOT, "..", "docs", "Copy of 6102 - Q4 Pet Beds Current - MDDP-PO tracker-1009 - 副本.xlsx")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BURLINGTON_ASN_HOME", str(tmp_path / "home"))


def make_xlsx(tmp_path, rows, header=("PO", "Description", "Packages", "Quantity", "G.W.(KGS)", "N.W.(KGS)", "Size")):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "ACME GARMENT CO., LTD\nINV.NO. X1 DATE: 2026-01-02"
    ws.append([])
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    p = tmp_path / "t.xlsx"
    wb.save(p)
    return str(p)


def test_sample_file():
    r = pp.parse(SAMPLE)
    assert not r["errors"]
    assert [l["document_id"] for l in r["lines"]] == ["580367401", "580367301"]
    for l in r["lines"]:
        assert l["cartons"] == 85 and l["quantity"] == 510
        assert l["units_per_carton"] == 6 and l["gross_weight"] == 1020.00
    assert r["totals_check"]["status"] == "ok"
    assert "SUMEC" in r["factory_name_guess"]
    assert r["invoice_no"] == "1100QB" and r["invoice_date"] == "2026-09-07"
    assert r["confidence"] == "high"


def test_string_numbers(tmp_path):
    p = make_xlsx(tmp_path, [("5803674", "A", "85", "1,020     PCS", "2,040. KGS", "1.5", "x"),
                             (None, None, 85, "1,020 PCS", 2040, 1, None)])
    r = pp.parse(p)
    l = r["lines"][0]
    assert l["cartons"] == 85 and l["quantity"] == 1020 and l["gross_weight"] == 2040.0
    assert l["units_per_carton"] == 12
    assert r["totals_check"]["status"] == "ok"


def test_nine_vs_seven_digit(tmp_path):
    p = make_xlsx(tmp_path, [(580367402, "A", 10, 100, 50, 40, ""), ("5803673", "B", 10, 100, 50, 40, "")])
    r = pp.parse(p)
    a, b = r["lines"]
    assert a["document_id"] == "580367402" and a["master_po"] == "5803674" and a["line_suffix"] == "02"
    assert not a["warnings"]
    assert b["document_id"] == "580367301"
    assert any("LINE_SUFFIX_ASSIGNED" in w for w in b["warnings"])


def test_duplicate_master_suffix(tmp_path):
    p = make_xlsx(tmp_path, [(5803674, "A", 10, 100, 50, 40, ""), (5803674, "B", 5, 50, 20, 10, ""),
                             (5803673, "C", 1, 6, 2, 1, ""), (5803674, "D", 2, 4, 2, 1, "")])
    ids = [l["document_id"] for l in pp.parse(p)["lines"]]
    assert ids == ["580367401", "580367402", "580367301", "580367403"]


def test_non_integer_units_blocks(tmp_path):
    p = make_xlsx(tmp_path, [(5803674, "A", 7, 100, 50, 40, "")])
    r = pp.parse(p)
    assert r["lines"][0]["units_per_carton"] is None
    assert r["blocking"]


def test_totals_mismatch(tmp_path):
    p = make_xlsx(tmp_path, [(5803674, "A", 10, 100, 50, 40, ""), (None, None, 11, 100, 50, 40, "")])
    assert pp.parse(p)["totals_check"]["status"] == "MISMATCH"


def test_saved_mapping_roundtrip(tmp_path):
    p = make_xlsx(tmp_path, [(5803674, "A", 10, 100, 50, 40, "")])
    r = pp.parse(p)
    d = os.path.join(pp.home_dir(), "mappings")
    os.makedirs(d)
    import json
    with open(os.path.join(d, r["fingerprint"] + ".json"), "w") as f:
        json.dump({"po": "A", "packages": "C", "quantity": "D", "gross_weight": "E", "header_row": 3}, f)
    r2 = pp.parse(p)
    assert r2["mapping_source"].startswith("saved:")
    assert r2["lines"][0]["cartons"] == 10


def test_missing_required_column(tmp_path):
    p = make_xlsx(tmp_path, [(5803674, "A", 10, 100)], header=("PO", "Description", "Packages", "Quantity"))
    assert pp.parse(p)["errors"]


def test_midpoint_and_intersection():
    d = ps.parse_date
    assert ps.midpoint(d("09-MAR-26"), d("13-MAR-26")) == dt.date(2026, 3, 11)
    assert ps.midpoint(d("09-MAR-26"), d("12-MAR-26")) == dt.date(2026, 3, 10)  # floor
    assert ps.midpoint(d("09-MAR-26"), d("09-MAR-26")) == dt.date(2026, 3, 9)
    w = [(d("09-MAR-26"), d("20-MAR-26")), (d("11-MAR-26"), d("15-MAR-26"))]
    assert ps.intersect(w) == (dt.date(2026, 3, 11), dt.date(2026, 3, 15))
    assert ps.intersect([(d("01-MAR-26"), d("05-MAR-26")), (d("07-MAR-26"), d("09-MAR-26"))]) is None
    assert ps.parse_date("03/11/2026") == dt.date(2026, 3, 11)


def test_plan_sample_and_no_intersection():
    parsed = pp.parse(SAMPLE)
    T = dt.date(2026, 3, 1)
    p = ps.plan(parsed, {"580367401": ["09-MAR-26", "13-MAR-26"], "580367301": ["10-MAR-26", "20-MAR-26"]},
                prepack={"580367301": "6"}, ordered={"580367401": "500"}, today=T)
    s = p["shipments"][0]
    assert s["ship_date"] == "03/11/2026" and "ship_date_original" not in s
    # binding rule: a midpoint in the past becomes today, reported (never silently)
    late = ps.plan(parsed, {"580367401": ["09-MAR-26", "13-MAR-26"], "580367301": ["10-MAR-26", "20-MAR-26"]},
                   today=dt.date(2026, 3, 20))
    assert late["shipments"][0]["ship_date"] == "03/20/2026" and late["shipments"][0]["ship_date_original"] == "03/11/2026"
    assert any("SHIP_DATE_IN_PAST" in i for i in late["issues"]) and not late["blocking"]
    assert s["lines"][0]["qty_per_carton"] == 6 and s["lines"][1]["qty_per_carton"] == 1
    assert s["lines"][0]["weight_kg"] == "1020.00"
    assert any("Qty Ordered" in i for i in p["issues"])
    bad = ps.plan(parsed, {"580367401": ["01-MAR-26", "02-MAR-26"], "580367301": ["10-MAR-26", "20-MAR-26"]}, today=T)
    assert any("intersect" in b for b in bad["blocking"])
    per = ps.plan(parsed, {"580367401": ["01-MAR-26", "02-MAR-26"], "580367301": ["10-MAR-26", "20-MAR-26"]}, per_master=True, today=T)
    assert len(per["shipments"]) == 2 and not per["blocking"]
    miss = ps.plan(parsed, {})
    assert miss["blocking"]


def test_factories():
    items = fa.add({"name": "SUMEC TEXTILE COMPANY LIMITED", "address1": "68 Yunlongshan Road", "city": "Nanjing", "country": "CN"}, [])
    fa.save(items)
    assert fa.find("Sumec Textile Co., Ltd")[0]["city"] == "Nanjing"
    assert fa.find("Random Other Factory") == []
    with pytest.raises(ValueError):
        fa.add({"name": "x"}, [])


# ---------------------------------------------------------------- PO tracker profile
TRACKER_HEADER = ["Container", "Shyft SO #", "Shyft PO #", "Master PO #", "Line #", "ASN #", "Model #", "Styles Description ",
                  "Color", "Order Units", "Pack", "EDI PO Start Ship", "EDI PO End Ship", "Gross Weight/Carton(kg)",
                  "Submit ASN # (w/ Date)"]


def make_tracker(tmp_path, rows, secondary=True):
    """rows: (container, master, line, asn, units, pack, start, end, gw). Master/container merged over equal neighbours."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vendor "
    ws.append(TRACKER_HEADER)
    for (cont, master, line, asn, units, pack, st, en, gw) in rows:
        ws.append([cont, None, None, master, line, asn, "M1", "desc", "c", units, pack, st, en, gw, None])
    n = len(rows) + 1
    ws.auto_filter.ref = "A1:O%d" % n
    if secondary:
        ws.cell(n + 5, 4, "Master PO #")
        ws.cell(n + 5, 5, "EDI PO Start Ship")
        ws.cell(n + 6, 4, 5820677)
        ws.cell(n + 6, 5, "09-NOV-26")
    ws.merge_cells("D2:D3")
    p = tmp_path / "tr.xlsx"
    wb.save(p)
    return str(p)


ROWS = [("C9", 5820678, "01", 872295, 1428, 6, "30-NOV-26", "04-DEC-26", 12),
        ("C9", None, "02", "", 960, 6, "30-NOV-26", "04-DEC-26", 10),
        ("C10", 5820680, "01", "", 1650, 6, "30-NOV-26", "04-DEC-26", 8.0),
        ("C14", 5820677, "01", "", 2388, 6, "09-NOV-26", "13-NOV-26", 12)]


def test_tracker_real_file():
    r = pp.parse(TRACKER)
    assert r["profile"] == "po_tracker" and not r["errors"] and not r["blocking"]
    ids = [l["document_id"] for l in r["lines"]]
    assert ids == ["582067802", "582068001", "582068002", "582068201", "582067701", "582067702", "582067901", "582068401"]
    assert [s["document_id"] for s in r["skipped_with_asn"]] == ["582067801"]
    assert [l["cartons"] for l in r["lines"]] == [160, 275, 119, 253, 398, 55, 158, 158]
    assert [l["gross_weight_per_carton"] for l in r["lines"]] == [10, 8, 7, 10, 12, 9, 8, 6]
    assert all(l["pack"] == 6 for l in r["lines"])
    assert r["lines"][0]["start_ship"] == "2026-11-30" and r["lines"][0]["container"] == "Container 9"
    assert r["totals"]["shipments"] == 6  # secondary table below the data is ignored
    full = pp.parse(TRACKER, include_with_asn=True)
    assert len(full["lines"]) == 9 and full["lines"][0]["existing_asn"] == "872295"


def test_tracker_synthetic_merged_and_secondary(tmp_path):
    r = pp.parse(make_tracker(tmp_path, ROWS))
    assert r["profile"] == "po_tracker"
    assert [l["document_id"] for l in r["lines"]] == ["582067802", "582068001", "582067701"]
    assert r["skipped_with_asn"][0]["existing_asn"] == "872295"
    assert r["lines"][0]["master_po"] == "5820678"  # inherited through the merge
    assert len(r["lines"]) + len(r["skipped_with_asn"]) == 4  # secondary table never read


def test_tracker_blocking(tmp_path):
    rows = [("C", 5820678, "01", "", 1000, 6, "30-NOV-26", "04-DEC-26", 12)]
    r = pp.parse(make_tracker(tmp_path, rows))
    assert r["lines"][0]["cartons"] is None and any("NON_INTEGER_CARTONS" in b for b in r["blocking"])


def test_packing_list_unaffected_by_profile():
    assert pp.parse(SAMPLE)["profile"] == "packing_list"
    assert pp.parse(SAMPLE, profile="po_tracker")["errors"]


def test_plan_tracker_defaults_and_rules():
    r = pp.parse(TRACKER)
    p = ps.plan(r, {}, today=dt.date(2026, 10, 18))  # no --dates needed
    assert not p["blocking"]
    assert len(p["shipments"]) == 6  # per master PO
    by = {s["group"]: s for s in p["shipments"]}
    assert by["5820678"]["ship_date"] == "12/02/2026" and by["5820677"]["ship_date"] == "11/11/2026"
    l = by["5820680"]["lines"][0]
    assert (l["qty_per_carton"], l["cartons_per_site"], l["weight_kg"]) == (6, 275, "8.00")
    assert any("ORDERED_NOT_VERIFIED" in w for w in l["warnings"])


def test_plan_tracker_ab_rule_and_dates_cross_check():
    r = pp.parse(TRACKER)
    doc = "582068001"
    T = dt.date(2026, 10, 18)
    a = ps.plan(r, {}, ordered={doc: "1650"}, today=T)
    assert not a["blocking"]
    la = [x for s in a["shipments"] for x in s["lines"] if x["document_id"] == doc][0]
    assert la["qty_per_carton"] == 6 and la["cartons_per_site"] == 275
    b = ps.plan(r, {}, ordered={doc: "275"}, today=T)
    lb = [x for s in b["shipments"] for x in s["lines"] if x["document_id"] == doc][0]
    assert lb["qty_per_carton"] == 1 and lb["qty_per_carton"] * lb["cartons_per_site"] == 275
    c = ps.plan(r, {}, ordered={doc: "1000"}, today=T)
    assert any("neither" in x for x in c["blocking"])
    d = ps.plan(r, {doc: ["01-DEC-26", "05-DEC-26"]}, today=T)
    assert any("WEB_DATES_DIFFER" in x for x in d["issues"]) and not d["blocking"]
    assert [s["ship_date"] for s in d["shipments"] if s["group"] == "5820680"] == ["12/02/2026"]  # Excel wins


def test_write_asn_copy(tmp_path):
    import hashlib
    src = make_tracker(tmp_path, ROWS)
    h = hashlib.sha256(open(src, "rb").read()).hexdigest()
    res = wa.write_asn(src, {"582067802": "900001", "582068001": "900002", "999999901": "1"})
    assert res["not_found"] == ["999999901"] and len(res["written"]) == 2
    assert hashlib.sha256(open(src, "rb").read()).hexdigest() == h  # original untouched
    assert os.path.basename(res["output"]).startswith("tr_ASN_") and res["output"] != src
    ws = openpyxl.load_workbook(res["output"]).active
    assert ws["F3"].value == 900001 and ws["F4"].value == 900002 and ws["F2"].value == 872295
    assert all(ws.cell(r, 15).value is None for r in range(2, 6))  # 'Submit ASN # (w/ Date)' untouched
    keep = wa.write_asn(src, {"582067801": "5"}, out=str(tmp_path / "o2.xlsx"))
    assert keep["kept_existing"] and not keep["output"]
    assert wa.write_asn(src, {"582067801": "5"}, out=src)["errors"]


def test_write_asn_real_tracker(tmp_path):
    out = str(tmp_path / "copy.xlsx")
    res = wa.write_asn(TRACKER, {"582068001": "900010"}, out=out)
    ws = openpyxl.load_workbook(out).active
    assert ws["F4"].value == 900010 and ws["L2"].value == "=J2*K2"
    assert res["written"][0]["cell"] == "F4"
