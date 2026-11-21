"""Shared helpers for WP-B tests."""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

from edi_assistant.core.config import AppConfig
from edi_assistant.core.models import FactoryAddress, PlannedLine, POLine, RunPlan, ShipmentPlan
from edi_assistant.mock_edi import MockServer

TODAY = date(2026, 3, 1)
TODAY_TRACKER = date(2026, 10, 18)
TRACKER_FILE = Path(__file__).resolve().parents[2] / "docs" / "Copy of 6102 - Q4 Pet Beds Current - MDDP-PO tracker-1009 - 副本.xlsx"


def make_config(server: MockServer) -> AppConfig:
    cfg = AppConfig()
    cfg.site.use_mock = True
    cfg.site.mock_url = server.url
    cfg.browser.channel = os.environ.get("EDI_TEST_BROWSER_CHANNEL", "chromium")   # e.g. "chrome" where no Playwright Chromium is installed
    cfg.browser.headless = True
    cfg.browser.default_timeout_ms = 8000
    cfg.pace.enabled = False   # human-pace delays off by default in tests (dedicated tests enable it with tiny values)
    return cfg


def make_line(po_line_id: str, packages="85", quantity="510", gross="1020.00", excel_row=5) -> PlannedLine:
    pl = POLine(master_po=po_line_id[:7], line=int(po_line_id[7:]), excel_row=excel_row, description="TEST",
                packages=Decimal(packages), quantity=Decimal(quantity), gross_weight=Decimal(gross))
    return PlannedLine(po_line=pl, weight_kg=Decimal(gross), weight_text=f"{Decimal(gross):.2f}")


def make_plan(lines: list[PlannedLine], dry_run: bool = False, run_id: str = "20261018-000000-test") -> RunPlan:
    factory = FactoryAddress(id="f1", name="SUMEC TEXTILE COMPANY LIMITED", address1="1 TEST ROAD", address2="BLDG 2",
                             city="NANJING", state="JIANGSU", zip="210000", country="CHINA")
    masters: list[str] = []
    for ln in lines:
        if ln.po_line.master_po not in masters:
            masters.append(ln.po_line.master_po)
    sh = ShipmentPlan(index=1, label=f"Shipment 1 ({', '.join(masters)})", lines=lines, factory=factory, master_pos=masters)
    return RunPlan(run_id=run_id, source_file="x.xlsx", sheet_name="page 1", template_fingerprint="fp",
                   shipments=[sh], grouping="per_file", dry_run=dry_run, created_at="2026-10-18T00:00:00")


def make_tracker_line(master: str, line: int, units: int, pack: int = 6, gw: str = "10", excel_row: int = 2,
                      start: date = date(2026, 11, 30), end: date = date(2026, 12, 4), container: str = "C1",
                      model: str = "MDL") -> PlannedLine:
    pl = POLine(master_po=master, line=line, excel_row=excel_row, description="TEST", packages=Decimal(units // pack),
                quantity=Decimal(units), gross_weight=Decimal(gw), model_no=model, order_units=Decimal(units),
                pack_qty=Decimal(pack), gw_per_carton=Decimal(gw), start_ship=start, end_ship=end,
                container=container, source_row=excel_row)
    return PlannedLine(po_line=pl, weight_kg=Decimal(gw), weight_text=f"{Decimal(gw):.2f}")


def make_tracker_plan(server=None, run_id: str = "20261018-000000-trk") -> RunPlan:
    """Plan built from the REAL tracker through the data layer (po_tracker profile, SUMEC test factory)."""
    from edi_assistant.data import PlanOptions, build_plan, detect_header, extract_rows, load_grid, suggest_mapping

    grid = load_grid(TRACKER_FILE)
    det = detect_header(grid)
    mapping, _ = suggest_mapping(det)
    rx = extract_rows(grid, det, mapping)
    factory = FactoryAddress(id="f1", name="SUMEC TEXTILE COMPANY LIMITED", address1="1 TEST ROAD", address2="BLDG 2",
                             city="NANJING", state="JIANGSU", zip="210000", country="CHINA")
    opts = PlanOptions("per_file", False, "total_gw", profile="po_tracker", today=TODAY_TRACKER)
    return build_plan(rx.lines, factory, opts, str(TRACKER_FILE), grid.sheet_name, "fp", run_id=run_id)
