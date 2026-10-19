"""Copy of the source Excel with the web shipment ids (ASN) written back."""
from __future__ import annotations

import os
import shutil
import warnings
from pathlib import Path

import openpyxl

from edi_assistant.core import paths
from edi_assistant.core.errors import ExcelReadError
from edi_assistant.core.models import RunPlan
from edi_assistant.core.textnorm import normalize_header

from .excel_reader import col_index
from .header_detect import HeaderDetection
from .mapping import ColumnMapping


def _writable_dir(d: Path) -> bool:
    if not os.access(d, os.W_OK):
        return False
    probe = d / f".edi_probe_{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def writeback_path_for(plan: RunPlan) -> Path:
    src = Path(plan.source_file)
    if plan.profile != "po_tracker":
        return src.with_name(f"{src.stem}_ASN.xlsx")
    name = f"{src.stem}_ASN_{plan.run_id[:15]}.xlsx"
    if _writable_dir(src.parent):
        return src.with_name(name)
    return paths.run_dir(plan.run_id) / name


def _asn_column(ws, det: HeaderDetection, mapping: ColumnMapping | None) -> int | None:
    if mapping is not None and mapping.columns.get("asn") is not None:
        return col_index(mapping.columns["asn"].letter)
    hdr = max(det.header_rows)
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=hdr, column=c).value
        if v is not None and normalize_header(v) == "asn":
            return c
    return None


def write_back(plan: RunPlan, det: HeaderDetection, mapping: ColumnMapping | None = None, *,
               ids: dict[int, str] | None = None, dst: Path | None = None,
               written: dict[int, set[int]] | None = None) -> Path:
    """`written` (optional, mutated): shipment index -> Excel rows already given an ASN by an earlier call. Those rows keep
    their ASN even if the line failed later (the shipment exists on the web); the copy is saved atomically so it is
    always a valid workbook."""
    src = Path(plan.source_file)
    dst = Path(dst) if dst else writeback_path_for(plan)
    ids = ids or {}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(dst)
        ws = wb[plan.sheet_name] if plan.sheet_name in wb.sheetnames else wb.worksheets[0]
        col = _asn_column(ws, det, mapping)
        if col is None:
            col = ws.max_column + 1
            ws.cell(row=max(det.header_rows), column=col, value="ASN")
        if "submit" in normalize_header(ws.cell(row=max(det.header_rows), column=col).value).split():
            raise ExcelReadError("Refusing to write into a 'Submit' column",
                                 message_vi="Refusing to write into a 'Submit' column")
        for sh in plan.shipments:
            wid = ids.get(sh.index) or sh.web_shipment_id
            if not wid:
                continue
            val = int(wid) if plan.profile == "po_tracker" and str(wid).isdigit() else str(wid)
            rows = written.setdefault(sh.index, set()) if written is not None else set()
            for pl in sh.lines:
                if pl.status not in ("skipped", "failed"):
                    rows.add(pl.po_line.source_row or pl.po_line.excel_row)
            for r in rows:
                ws.cell(row=r, column=col, value=val)
        tmp = dst.with_name(dst.name + ".tmp")
        wb.save(tmp)
        os.replace(tmp, dst)
    except ExcelReadError:
        raise
    except Exception as e:
        raise ExcelReadError(f"Cannot write back Excel: {e}",
                             message_vi="Could not write the ASN number into the Excel copy") from e
    return dst
