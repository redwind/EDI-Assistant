from datetime import date
from decimal import Decimal

from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import PlanOptions, build_plan, detect_header, extract_rows, load_grid, suggest_mapping
from edi_assistant.data.planner import plan_summary_rows
from edi_assistant.data.profiles import detect_profile

FACTORY = FactoryAddress(id="f1", name="SUMEC", address1="1 ROAD")
IDS = ["582067801", "582067802", "582068001", "582068002", "582068201", "582067701", "582067702",
       "582067901", "582068401"]


def _load(path):
    grid = load_grid(path)
    det = detect_header(grid)
    mapping, scores = suggest_mapping(det)
    return grid, det, mapping, scores


def test_header_profile_mapping(tracker_path):
    grid, det, mapping, scores = _load(tracker_path)
    assert det.header_rows == [1] and det.data_start_row == 2
    assert detect_profile(det) == ("po_tracker", 1.0)
    assert mapping.profile == "po_tracker"
    letters = {k: (r.letter if r else None) for k, r in mapping.columns.items()}
    assert {k: letters[k] for k in ("po", "line", "asn", "model_no", "description", "quantity", "start_ship",
                                    "end_ship", "pack", "gw_per_carton", "container")} == {
        "po": "D", "line": "E", "asn": "F", "model_no": "G", "description": "H", "quantity": "J",
        "start_ship": "M", "end_ship": "N", "pack": "Q", "gw_per_carton": "T", "container": "A"}
    assert letters["net_weight"] is None and letters["packages"] is None and letters["size"] is None
    assert letters["gross_weight"] is None
    assert "AB" not in letters.values()
    assert mapping.is_complete()


def test_extract_rows(tracker_path):
    grid, det, mapping, _ = _load(tracker_path)
    rx = extract_rows(grid, det, mapping)
    assert [ln.po_line_id for ln in rx.lines] == IDS
    l0, l1 = rx.lines[0], rx.lines[1]
    assert l0.existing_asn == "872295" and l0.selected is False
    assert l1.container == "Container 9" and l1.master_po == "5820678"
    assert [int(ln.packages) for ln in rx.lines] == [238, 160, 275, 119, 253, 398, 55, 158, 158]
    assert l0.quantity == 1428 and l0.gross_weight == Decimal(12)
    assert l0.start_ship == date(2026, 11, 30) and l0.end_ship == date(2026, 12, 4)
    assert rx.lines[5].start_ship == date(2026, 11, 9) and rx.lines[5].end_ship == date(2026, 11, 13)
    assert all(ln.excel_row < 11 for ln in rx.lines)
    assert rx.skipped == [] and rx.company_text == ""
    assert [int(ln.gross_weight) for ln in rx.lines] == [12, 10, 8, 7, 10, 12, 9, 8, 6]


def test_plan_and_summary(tracker_path):
    grid, det, mapping, _ = _load(tracker_path)
    rx = extract_rows(grid, det, mapping)
    opts = PlanOptions("per_file", False, "total_gw", profile="po_tracker", today=date(2026, 10, 18))
    plan = build_plan(rx.lines, FACTORY, opts, str(tracker_path), "Vendor ", "fp")
    assert plan.grouping == "per_master_po" and plan.profile == "po_tracker" and plan.qty_strict
    assert len(plan.shipments) == 6
    assert sum(len(s.lines) for s in plan.shipments) == 8
    assert "582067801" not in [pl.po_line.po_line_id for s in plan.shipments for pl in s.lines]
    s5820678 = next(s for s in plan.shipments if s.master_pos == ["5820678"])
    assert [pl.po_line.po_line_id for pl in s5820678.lines] == ["582067802"]
    for s in plan.shipments:
        assert s.dates_source == "excel"
        want = date(2026, 11, 11) if s.master_pos == ["5820677"] else date(2026, 12, 2)
        assert s.planned_ship_date == want
    wt = {pl.po_line.po_line_id: pl.weight_text for s in plan.shipments for pl in s.lines}
    assert wt["582067701"] == "12.00" and wt["582067802"] == "10.00"
    assert [wt[i] for i in IDS[1:]] == ["10.00", "8.00", "7.00", "10.00", "12.00", "9.00", "8.00", "6.00"]
    rows = plan_summary_rows(plan, rx.lines)
    assert len(rows) == 9
    assert rows[0]["shipment_index"] == "" and rows[0]["status_text"] == "already has ASN 872295"
    assert rows[1]["shipment_index"] != "" and rows[1]["ship_date"] == "12/02/2026"
    assert len(plan_summary_rows(plan)) == 8
    # selecting line 0 brings it back into the plan
    rx.lines[0].selected = True
    plan2 = build_plan(rx.lines, FACTORY, opts, str(tracker_path), "Vendor ", "fp")
    assert len(plan2.shipments) == 6 and sum(len(s.lines) for s in plan2.shipments) == 9
    assert len(next(s for s in plan2.shipments if s.master_pos == ["5820678"]).lines) == 2
