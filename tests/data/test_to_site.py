"""TO Site No from the tracker's Delivery Address (EDI notice: CA=512, NJ=053, GA=934)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import openpyxl

from edi_assistant.core import dc_sites as dc
from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import detect_header, extract_rows, load_grid, suggest_mapping
from edi_assistant.data.planner import PlanOptions, build_plan
from tests.data.test_pdf_tracker_factories import HEAD

GA = "GA Savanah (SAV) DC, 447 LOGISTICS DRIVE, ELLABELL, GA 31308"
CA = "CA Riverside DC, 1 MAIN ST, RIVERSIDE, CA 92501-1234"


def test_state_and_site():
    assert dc.state_of(GA) == "GA" and dc.zip_of(GA) == "31308"
    assert dc.site_for(GA) == "934" and dc.site_for(CA) == "512"
    assert dc.site_for("Somewhere, TX 75001") == "" and dc.site_for("GA Savanah (SAV) DC") == ""
    assert dc.site_for("x, NJ 07001", {"nj": "53"}) == "53"


def test_pick_option_and_table():
    opts = [("", "Select One"), ("53", "53"), ("512", "512 - RIVERSIDE"), ("x934", "934 ELLABELL GA")]
    assert dc.pick_option(opts, "053") == "53"
    assert dc.pick_option(opts, "512") == "512"
    assert dc.pick_option(opts, "934") == "x934"
    assert dc.pick_option(opts, "777") is None
    assert dc.parse_table("ca=512; NJ = 053,GA=934, bad, X=1") == {"CA": "512", "NJ": "053", "GA": "934"}
    assert dc.format_table(dc.DEFAULT_TO_SITES) == "CA=512, NJ=053, GA=934"


def _tracker(tmp_path, addrs):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Vendor "
    ws.append(HEAD)
    for i, addr in enumerate(addrs, 1):
        row = dict.fromkeys(HEAD)
        row.update({"Factory Name": "F", "Delivery Address": addr, "Master PO #": "6723460", "Line #": f"{i:02d}",
                    "EDI PO Start Ship": "25-JAN-27", "EDI PO End Ship": "29-JAN-27", "EDI Units": 60, "Pack": 6,
                    "Gross Weight/Carton(kg)": 1})
        ws.append([row[h] for h in HEAD])
    p = tmp_path / "t.xlsx"
    wb.save(p)
    g = load_grid(p, "Vendor ")
    det = detect_header(g)
    m, _ = suggest_mapping(det)
    assert m.columns["delivery_address"].letter == "B" and m.columns["factory"].letter == "A"
    rx = extract_rows(g, det, m)
    plan = build_plan(rx.lines, FactoryAddress(id="f", name="F", address1="A"), PlanOptions("per_file", False, "total_gw", profile="po_tracker",
                                                                       today=date(2026, 11, 19)), "t.xlsx", "Vendor ", "fp")
    return rx, plan.shipments[0]


def test_plan_gets_to_site_and_blank_rows_inherit(tmp_path):
    rx, sh = _tracker(tmp_path, [GA, None])
    assert [ln.delivery_address for ln in rx.lines] == [GA, GA]
    assert sh.to_site_no == "934" and "TO 934" in sh.label
    assert not any(f.code.startswith("to_site") or f.code == "multiple_dc" for f in sh.flags)


def test_plan_flags_unknown_and_mixed_dc(tmp_path):
    _, sh = _tracker(tmp_path, ["GA Savanah (SAV) DC"])
    assert sh.to_site_no == "" and any(f.code == "to_site_unknown" for f in sh.flags)
    _, sh = _tracker(tmp_path, [GA, CA])
    assert sh.to_site_no == "" and any(f.code == "multiple_dc" and f.severity == "error" for f in sh.flags)


def test_config_roundtrip_keeps_table():
    from edi_assistant.core.config import AppConfig, config_from_dict, config_to_dict
    cfg = AppConfig()
    assert cfg.flow.to_sites == {"CA": "512", "NJ": "053", "GA": "934"}
    cfg.flow.to_sites = {"TX": "100"}
    assert config_from_dict(config_to_dict(cfg)).flow.to_sites == {"TX": "100"}



def test_layout_from_older_version_is_dropped(tmp_path):
    """A layout remembered by an older version (no Delivery Address) is deleted, so the new format is
    mapped afresh from its headers."""
    import json
    from edi_assistant.data.templates import TemplateStore
    _tracker(tmp_path, [GA])
    det = detect_header(load_grid(tmp_path / "t.xlsx", "Vendor "))
    m, _ = suggest_mapping(det)
    store = TemplateStore(tmp_path / "tpl")
    t = store.learn(det, m, "new", "", "Vendor ")
    assert store.find(det).template.columns["delivery_address"].letter == "B"
    f = store.directory / f"{t.fingerprint}.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["version"] = 1
    d.pop("fields")
    d["columns"].pop("delivery_address")
    f.write_text(json.dumps(d), encoding="utf-8")
    assert store.find(det) is None and not f.exists() and store.list() == []
