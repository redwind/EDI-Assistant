import logging
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

from edi_assistant.core.errors import MappingIncompleteError
from edi_assistant.core.logging_setup import setup_logging
from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import (PlanOptions, ResultsWriter, build_plan, detect_header, extract_rows, load_grid,
                                suggest_mapping, validate_mapping, write_back)
from edi_assistant.data.mapping import ColumnMapping
from edi_assistant.data.results import load_run_history


def _plan(sample_path):
    grid = load_grid(sample_path)
    det = detect_header(grid)
    rx = extract_rows(grid, det, suggest_mapping(det)[0])
    f = FactoryAddress(id="f", name="X", address1="a")
    return det, build_plan(rx.lines, f, PlanOptions("per_file", False, "total_gw"), str(sample_path), "page 1", "fp")


def test_writeback(sample_path, tmp_path):
    import shutil
    src = tmp_path / "pl.xlsx"
    shutil.copy(sample_path, src)
    det, plan = _plan(src)
    plan.shipments[0].web_shipment_id = "9001"
    out = write_back(plan, det)
    assert out.name == "pl_ASN.xlsx"
    ws = openpyxl.load_workbook(out)["page 1"]
    assert ws["J4"].value == "ASN" and ws["J5"].value == "9001" and ws["J6"].value == "9001"
    assert openpyxl.load_workbook(src)["page 1"]["J4"].value is None


def test_validate_mapping():
    with pytest.raises(MappingIncompleteError) as ei:
        validate_mapping(ColumnMapping())
    assert ei.value.ctx["missing"] == ["po", "packages", "quantity", "gross_weight"]


def test_logging_and_history(data_dir):
    p = setup_logging()
    assert setup_logging() == p
    logging.getLogger("x").info("hello")
    assert p.parent == data_dir / "logs"
    assert load_run_history() == []


def test_core_data_have_no_qt_or_playwright():
    code = ("import sys, edi_assistant.core.models, edi_assistant.core.config, edi_assistant.data;"
            "assert not [m for m in sys.modules if m.startswith(('PySide6', 'playwright'))]")
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
