"""PO-tracker profile: grid + mapping -> list[POLine] (one Excel row per PO line)."""
from __future__ import annotations

from decimal import Decimal

from edi_assistant.core.errors import MappingIncompleteError
from edi_assistant.core.models import Flag, POLine
from edi_assistant.core.textnorm import normalize_header

from .excel_reader import SheetGrid, col_index
from .header_detect import HeaderDetection
from .mapping import ColumnMapping
from .rows import RowExtraction
from .values import (parse_date_cell, parse_decimal, parse_line_cell, parse_po_cell, parse_text_or_blank,
                     to_text)

# 'line' is required for the UI, but the extractor can still derive it from a 9-digit / 'PO-01' PO cell.
_EXTRACT_REQUIRED = ("po", "edi_units", "pack", "gw_per_carton", "start_ship", "end_ship")


def extract_tracker_rows(grid: SheetGrid, det: HeaderDetection, mapping: ColumnMapping) -> RowExtraction:
    missing = [k for k in _EXTRACT_REQUIRED if mapping.columns.get(k) is None]
    if "edi_units" in missing and mapping.columns.get("quantity") is not None:
        missing.remove("edi_units")
    if missing:
        raise MappingIncompleteError(f"Mapping incomplete, missing: {missing}",
                                     message_vi="Required columns are not mapped: " + ", ".join(missing),
                                     missing=missing)
    cols = {k: col_index(r.letter) for k, r in mapping.columns.items() if r is not None}
    first = det.data_start_row
    last_hint = grid.filter_last_row()
    header_norms = {normalize_header(c.joined) for c in det.columns}
    identity_cols = [cols[k] for k in ("container", "po") if k in cols]
    prev_master = ""
    prev_container = ""
    prev_dest = ""
    lines: list[POLine] = []
    skipped: list[tuple[int, str]] = []
    flags: list[Flag] = []
    factory_names: dict[str, str] = {}   # normalized -> first spelling seen

    def cell(r: int, key: str) -> object:
        return grid.get(r, cols[key]) if key in cols else None

    for r in range(first, grid.max_row + 1):
        # end-of-table detection
        if grid.is_blank(r, cols.values()) and grid.is_blank(r, identity_cols):
            break
        if last_hint and r > last_hint:
            break
        if any(isinstance(grid.get(r, c), str) and normalize_header(grid.get(r, c)) in header_norms
               for c in cols.values()):
            break
        # identity with merged inheritance
        inherited = False
        po_raw = grid.get_merged(r, cols["po"])
        if po_raw is None or (isinstance(po_raw, str) and not po_raw.strip()):
            if prev_master:
                po_raw = prev_master
                inherited = True
        parsed = parse_po_cell(po_raw)
        if parsed is None:
            skipped.append((r, "No master PO"))
            flags.append(Flag("totals_row_skipped", f"Skipped Excel row {r} (no PO)", "info"))
            continue
        master, po_line = parsed
        row_flags: list[Flag] = []
        line = parse_line_cell(cell(r, "line")) if "line" in cols else None
        if line is None:
            line = po_line
        if line is None:
            row_flags.append(Flag("line_missing", f"Row {r}: Line # unreadable", "error"))
        container = parse_text_or_blank(grid.get_merged(r, cols["container"])) if "container" in cols else ""
        if not container and master == prev_master:
            container = prev_container
        dest = parse_text_or_blank(grid.get_merged(r, cols["delivery_address"])) if "delivery_address" in cols else ""
        if not dest and master == prev_master:
            dest = prev_dest
        # numbers
        # Cartons = EDI Units / Pack; Order Units only stands in when EDI Units is empty
        J = parse_decimal(cell(r, "edi_units"))
        if (J is None or J == 0) and "quantity" in cols:
            J = parse_decimal(cell(r, "quantity"))
            if J is not None and J > 0 and "edi_units" in cols:
                row_flags.append(Flag("units_from_order", f"Row {r}: EDI Units empty - using Order Units {J}", "info"))
        fac = parse_text_or_blank(grid.get_merged(r, cols["factory"])) if "factory" in cols else ""
        if fac:
            factory_names.setdefault(" ".join(fac.lower().split()), fac)
        Q = parse_decimal(cell(r, "pack"))
        T = parse_decimal(cell(r, "gw_per_carton"))
        ok = True
        if J is None or J <= 0:
            row_flags.append(Flag("non_integer_units", f"Row {r}: EDI Units unreadable", "error"))
            ok = False
        if Q is None or Q <= 0:
            row_flags.append(Flag("pack_invalid", f"Row {r}: Pack unreadable or zero", "error"))
            ok = False
        cartons = Decimal(0)
        if ok:
            cartons = J / Q
            if cartons != cartons.to_integral_value():
                row_flags.append(Flag("non_integer_units",
                                      f"EDI Units {J} not divisible by Pack {Q}", "error"))
        if T is None or T <= 0:
            row_flags.append(Flag("weight_zero", f"Gross weight per carton is zero or missing in row {r}"))
            T = Decimal(0)
        # dates
        start = parse_date_cell(cell(r, "start_ship"))
        end = parse_date_cell(cell(r, "end_ship"))
        if start is None or end is None:
            row_flags.append(Flag("dates_missing_excel", f"Row {r}: ship window missing/unreadable", "warning"))
        elif start > end:
            start, end = end, start
            row_flags.append(Flag("dates_swapped", f"Row {r}: start/end ship dates were swapped", "info"))
        asn = parse_text_or_blank(cell(r, "asn"))
        raw = {k: grid.get(r, c) for k, c in cols.items()}
        pl = POLine(master_po=master, line=line or 0, excel_row=r, description=to_text(cell(r, "description")),
                    packages=cartons, quantity=J or Decimal(0), gross_weight=T, raw=raw,
                    model_no=to_text(cell(r, "model_no")), order_units=J, pack_qty=Q, gw_per_carton=T,
                    start_ship=start, end_ship=end, existing_asn=asn, container=container, delivery_address=dest,
                    source_row=r,
                    line_no_text=to_text(cell(r, "line")), selected=(asn == ""))
        pl.flags += row_flags
        if asn:
            pl.flags.append(Flag("already_has_asn", f"Row {r} already has ASN {asn}", "info"))
        if inherited:
            pl.flags.append(Flag("master_po_inherited",
                                 f"Row {r}: master PO {master} inherited from the row above", "info"))
        lines.append(pl)
        prev_master, prev_container, prev_dest = master, container, dest
    seen: dict[tuple[str, int], POLine] = {}
    for pl in lines:
        if not pl.line:
            continue
        key = (pl.master_po, pl.line)
        if key in seen:
            for x in (seen[key], pl):
                x.flags.append(Flag("duplicate_line",
                                    f"Duplicate line {pl.line:02d} for master PO {pl.master_po}", "error"))
        else:
            seen[key] = pl
    company = next(iter(factory_names.values()), "")
    if len(factory_names) > 1:
        flags.append(Flag("multiple_factories",
                          "File lists several factories (" + "; ".join(factory_names.values())
                          + ") - one run uses one ship-from factory", "warning"))
    return RowExtraction(lines, skipped, company, flags)
