import hashlib
import os
import re
import shutil
from datetime import date

import openpyxl

from edi_assistant.core import paths
from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import (PlanOptions, build_plan, detect_header, extract_rows, load_grid, suggest_mapping,
                                write_back, writeback_path_for)

FACTORY = FactoryAddress(id="f1", name="SUMEC", address1="1 ROAD")


def _hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _setup(tracker_path, tmp_path):
    src = tmp_path / "tracker.xlsx"
    shutil.copy(tracker_path, src)
    grid = load_grid(src)
    det = detect_header(grid)
    mapping, _ = suggest_mapping(det)
    rx = extract_rows(grid, det, mapping)
    plan = build_plan(rx.lines, FACTORY, PlanOptions("per_file", False, "total_gw", profile="po_tracker",
                                                     today=date(2026, 10, 18)),
                      str(src), grid.sheet_name, "fp", run_id="20261018-120000-abcd")
    return src, det, mapping, plan


def test_writeback_tracker(tracker_path, tmp_path):
    src, det, mapping, plan = _setup(tracker_path, tmp_path)
    before = _hash(src)
    out = write_back(plan, det, mapping, ids={1: "900001", 2: "900002"})
    assert re.search(r"_ASN_\d{8}-\d{6}\.xlsx$", out.name) and out.parent == src.parent
    assert out.name == "tracker_ASN_20261018-120000.xlsx"
    ws = openpyxl.load_workbook(out)["Vendor "]
    orig = openpyxl.load_workbook(src)["Vendor "]
    assert ws["F3"].value == 900001 and ws["F4"].value == 900002 and ws["F5"].value == 900002
    assert ws["F2"].value == 872295
    assert ws["AB2"].value in (None, "") and ws["L2"].value == "=J2*K2"
    assert sorted(map(str, ws.merged_cells.ranges)) == sorted(map(str, orig.merged_cells.ranges))
    assert ws.auto_filter.ref == orig.auto_filter.ref == "A1:AL10"
    assert ws["F6"].value is None or ws["F6"].value == ""     # shipment 3 has no id yet
    assert _hash(src) == before
    # idempotent
    first = _hash(out)
    assert [c.value for r in ws.iter_rows() for c in r] == \
        [c.value for r in openpyxl.load_workbook(write_back(plan, det, mapping, ids={1: "900001", 2: "900002"},
                                                            dst=out))["Vendor "].iter_rows() for c in r]
    assert out.exists() and len(list(src.parent.glob("*_ASN_*.xlsx"))) == 1 and first


def test_ids_override_and_plan_ids(tracker_path, tmp_path):
    src, det, mapping, plan = _setup(tracker_path, tmp_path)
    plan.shipments[0].web_shipment_id = "111"
    out = write_back(plan, det, mapping)
    assert openpyxl.load_workbook(out)["Vendor "]["F3"].value == 111
    out = write_back(plan, det, mapping, ids={1: "222"}, dst=out)
    assert openpyxl.load_workbook(out)["Vendor "]["F3"].value == 222


def test_skipped_lines_not_written(tracker_path, tmp_path):
    src, det, mapping, plan = _setup(tracker_path, tmp_path)
    plan.shipments[1].lines[0].status = "skipped"
    out = write_back(plan, det, mapping, ids={2: "7"})
    ws = openpyxl.load_workbook(out)["Vendor "]
    assert ws["F5"].value == 7 and ws["F4"].value in (None, "")


def test_path_fallback_when_readonly(tracker_path, tmp_path, monkeypatch):
    src, det, mapping, plan = _setup(tracker_path, tmp_path)
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, m, *a, **k: False if str(p) == str(src.parent) else real(p, m, *a, **k))
    p = writeback_path_for(plan)
    assert p.parent == paths.run_dir(plan.run_id) and p.name.endswith("_ASN_20261018-120000.xlsx")
    plan.profile = "packing_list"
    assert writeback_path_for(plan) == src.with_name("tracker_ASN.xlsx")


def test_already_written_asn_persists_after_later_failure(tracker_path, tmp_path):
    src, det, mapping, plan = _setup(tracker_path, tmp_path)
    written = {}
    out = write_back(plan, det, mapping, ids={1: "900001"}, written=written)
    for pl in plan.shipments[0].lines:      # the shipment exists on the web, but a later step failed
        pl.status = "failed"
    out = write_back(plan, det, mapping, ids={1: "900001"}, dst=out, written=written)
    assert openpyxl.load_workbook(out)["Vendor "]["F3"].value == 900001
    assert not list(out.parent.glob("*.tmp"))
    out2 = write_back(plan, det, mapping, ids={1: "900001"}, dst=tmp_path / "x.xlsx")   # no memory: old behaviour
    assert openpyxl.load_workbook(out2)["Vendor "]["F3"].value in (None, "")
