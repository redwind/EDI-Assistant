"""Grid + mapping -> list[POLine]."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from edi_assistant.core.models import Flag, POLine

from .excel_reader import SheetGrid, col_index
from .header_detect import HeaderDetection
from .mapping import ColumnMapping, validate_mapping
from .values import parse_decimal, parse_line_cell, parse_po_cell, to_text

COMPANY_RE = re.compile(r"(?i)\b(company|co\.?,?\s*ltd|limited|ltd|factory|industr\w*|textile\w*|garment\w*|manufactur\w*|corp\w*|enterprise\w*|trading)\b")


@dataclass(slots=True)
class RowExtraction:
    lines: list[POLine]
    skipped: list[tuple[int, str]]
    company_text: str
    flags: list[Flag]


def detect_company_text(grid: SheetGrid) -> str:
    for blob in grid.text_blobs():
        for ln in blob.splitlines():
            ln = ln.strip()
            if ln and len(ln) <= 80 and COMPANY_RE.search(ln):
                return ln
    return ""


def assign_line_numbers(lines: list[POLine]) -> None:
    used: dict[str, set[int]] = {}
    for ln in lines:
        if ln.line:
            used.setdefault(ln.master_po, set()).add(ln.line)
    counters: dict[str, int] = {}
    for ln in lines:
        if ln.line:
            continue
        n = counters.get(ln.master_po, 0) + 1
        while n in used.get(ln.master_po, ()):
            n += 1
        counters[ln.master_po] = n
        ln.line = n
        ln.flags.append(Flag("line_assigned",
                             f"Line number {n:02d} auto-assigned for PO {ln.master_po}", "info"))


def extract_rows(grid: SheetGrid, det: HeaderDetection, mapping: ColumnMapping) -> RowExtraction:
    if mapping.profile == "po_tracker":
        from .tracker_rows import extract_tracker_rows
        return extract_tracker_rows(grid, det, mapping)
    validate_mapping(mapping)
    cols = {k: col_index(r.letter) for k, r in mapping.columns.items() if r is not None}
    lines: list[POLine] = []
    skipped: list[tuple[int, str]] = []
    flags: list[Flag] = []
    for r in range(det.data_start_row, grid.max_row + 1):
        parsed = parse_po_cell(grid.get(r, cols["po"]))
        if parsed is None:
            if grid.row_values(r):
                skipped.append((r, "No PO (totals/notes row)"))
                flags.append(Flag("totals_row_skipped", f"Skipped Excel row {r} (no PO)", "info"))
            continue
        master, line = parsed
        raw = {k: grid.get(r, c) for k, c in cols.items()}
        if "line" in cols:
            line = parse_line_cell(raw["line"]) or line
        pl = POLine(master_po=master, line=line or 0, excel_row=r, raw=raw,
                    description=to_text(raw.get("description")), size=to_text(raw.get("size")))
        for key, attr in (("packages", "packages"), ("quantity", "quantity"), ("gross_weight", "gross_weight")):
            d = parse_decimal(raw.get(key))
            if d is None:
                pl.flags.append(Flag("non_integer_units", f"Cannot read value '{key}' in row {r}", "error"))
                d = Decimal(0)
            setattr(pl, attr, d)
        if "net_weight" in cols:
            pl.net_weight = parse_decimal(raw.get("net_weight"))
        if pl.gross_weight <= 0:
            pl.flags.append(Flag("weight_zero", f"Gross weight is zero or missing in row {r}"))
        pl.source_row = r
        lines.append(pl)
    assign_line_numbers(lines)
    return RowExtraction(lines, skipped, detect_company_text(grid), flags)
