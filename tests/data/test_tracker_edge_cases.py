from datetime import date, datetime

import openpyxl

from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import PlanOptions, build_plan, detect_header, extract_rows, load_grid, suggest_mapping

HEADERS = ["Container", "Master PO #", "Line #", "ASN #", "Model #", "Styles Description", "Order Units",
           "EDI PO Start Ship", "EDI PO End Ship", "Pack", "Gross Weight/Carton(kg)"]
FACTORY = FactoryAddress(id="f", name="F", address1="1")


def _book(tmp_path, rows, headers=HEADERS, merges=(), extra=None, auto_filter=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    for m in merges:
        ws.merge_cells(m)
    if extra:
        extra(ws)
    if auto_filter:
        ws.auto_filter.ref = auto_filter
    p = tmp_path / "t.xlsx"
    wb.save(p)
    grid = load_grid(p)
    det = detect_header(grid)
    mapping, _ = suggest_mapping(det)
    assert mapping.profile == "po_tracker"
    return grid, det, mapping


def _row(master, line, units=60, pack=6, start="30-NOV-26", end="04-DEC-26", asn=None, container="C1"):
    return [container, master, line, asn, "MDL", "desc", units, start, end, pack, 5]


def test_blank_row_and_second_table(tmp_path):
    def extra(ws):
        ws.append([None] * 11)
        ws.append([None, "Master PO #", "EDI PO Start Ship", "EDI PO End Ship"])
        ws.append([None, 5820677, "09-NOV-26", "13-NOV-26"])
    grid, det, m = _book(tmp_path, [_row(5820678, "01"), _row(5820678, "02")], extra=extra)
    rx = extract_rows(grid, det, m)
    assert [ln.po_line_id for ln in rx.lines] == ["582067801", "582067802"] and rx.skipped == []


def test_auto_filter_respected(tmp_path):
    def extra(ws):
        ws.append(_row(5820677, "01"))     # directly below, no blank row
    grid, det, m = _book(tmp_path, [_row(5820678, "01")], extra=extra, auto_filter="A1:K2")
    assert grid.filter_last_row() == 2
    assert [ln.po_line_id for ln in extract_rows(grid, det, m).lines] == ["582067801"]


def test_header_text_row_stops(tmp_path):
    def extra(ws):
        ws.append(["Container", "Master PO #", "Line #", "ASN #", "Model #", "Styles Description", "Order Units",
                   "EDI PO Start Ship", "EDI PO End Ship", "Pack", "Gross Weight/Carton(kg)"])
        ws.append(_row(5820677, "01"))
    grid, det, m = _book(tmp_path, [_row(5820678, "01")], extra=extra)
    assert len(extract_rows(grid, det, m).lines) == 1


def test_forward_fill_without_merge(tmp_path):
    rows = [_row(5820678, "01"), _row(None, "02", container=None)]
    grid, det, m = _book(tmp_path, rows)
    rx = extract_rows(grid, det, m)
    assert [ln.po_line_id for ln in rx.lines] == ["582067801", "582067802"]
    assert rx.lines[1].container == "C1"
    assert any(f.code == "master_po_inherited" for f in rx.lines[1].flags)


def test_merged_inheritance(tmp_path):
    rows = [_row(5820678, "01"), _row(None, "02", container=None)]
    grid, det, m = _book(tmp_path, rows, merges=["A2:A3", "B2:B3"])
    rx = extract_rows(grid, det, m)
    assert [ln.master_po for ln in rx.lines] == ["5820678", "5820678"] and rx.lines[1].container == "C1"


def test_asn_whitespace_and_selection(tmp_path):
    grid, det, m = _book(tmp_path, [_row(5820678, "01", asn="  "), _row(5820678, "02", asn=872295)])
    a, b = extract_rows(grid, det, m).lines
    assert a.existing_asn == "" and a.selected and b.existing_asn == "872295" and not b.selected


def test_non_integer_and_duplicate(tmp_path):
    grid, det, m = _book(tmp_path, [_row(5820678, "01", units=61), _row(5820678, "01")])
    a, b = extract_rows(grid, det, m).lines
    assert any(f.code == "non_integer_units" and f.severity == "error" for f in a.flags)
    assert any(f.code == "duplicate_line" for f in a.flags) and any(f.code == "duplicate_line" for f in b.flags)


def test_pack_invalid(tmp_path):
    grid, det, m = _book(tmp_path, [_row(5820678, "01", pack=0)])
    assert any(f.code == "pack_invalid" for f in extract_rows(grid, det, m).lines[0].flags)


def test_datetime_dates_and_swap(tmp_path):
    rows = [_row(5820678, "01", start=datetime(2026, 11, 30), end=datetime(2026, 12, 4)),
            _row(5820679, "01", start="04-DEC-26", end="30-NOV-26")]
    grid, det, m = _book(tmp_path, rows)
    a, b = extract_rows(grid, det, m).lines
    assert a.start_ship == date(2026, 11, 30) and a.end_ship == date(2026, 12, 4)
    assert b.start_ship == date(2026, 11, 30) and any(f.code == "dates_swapped" for f in b.flags)


def test_missing_dates_use_web_ladder(tmp_path):
    grid, det, m = _book(tmp_path, [_row(5820678, "01", start=None, end=None), _row(5820679, "01")])
    rx = extract_rows(grid, det, m)
    assert any(f.code == "dates_missing_excel" for f in rx.lines[0].flags)
    plan = build_plan(rx.lines, FACTORY, PlanOptions("per_file", False, "total_gw", profile="po_tracker",
                                                     today=date(2026, 10, 18)), "x", "s", "fp")
    by = {s.master_pos[0]: s for s in plan.shipments}
    assert by["5820678"].dates_source == "web" and by["5820678"].planned_ship_date is None
    assert by["5820679"].dates_source == "excel"


def test_nine_digit_po_without_line_column(tmp_path):
    heads = [h for h in HEADERS if h != "Line #"]
    rows = [[c for i, c in enumerate(_row("5820678-01", "x")) if i != 2]]
    grid, det, m = _book(tmp_path, rows, headers=heads)
    assert m.columns["line"] is None
    rx = extract_rows(grid, det, m)
    assert rx.lines[0].po_line_id == "582067801"


def test_non_overlapping_windows_flag(tmp_path):
    rows = [_row(5820678, "01"), _row(5820678, "02", start="01-JAN-27", end="05-JAN-27")]
    grid, det, m = _book(tmp_path, rows)
    plan = build_plan(extract_rows(grid, det, m).lines, FACTORY,
                      PlanOptions("per_file", False, "total_gw", profile="po_tracker", today=date(2026, 10, 18)),
                      "x", "s", "fp")
    codes = [f.code for f in plan.shipments[0].flags]
    assert codes.count("no_date_intersection") == 1
