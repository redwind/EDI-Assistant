"""openpyxl loading into a merged-cell aware sheet grid."""
from __future__ import annotations

import re
import warnings
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter

from edi_assistant.core.errors import ExcelReadError


@dataclass(slots=True)
class CellInfo:
    row: int
    col: int                       # 1-based
    value: object
    merged_span: tuple[int, int]   # (n_rows, n_cols) when top-left of a merged range
    is_merged_child: bool = False


@dataclass(slots=True)
class SheetGrid:
    sheet_name: str
    max_row: int
    max_col: int
    cells: dict[tuple[int, int], CellInfo]
    merged_parent: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    auto_filter_ref: str = ""

    def get_merged(self, row: int, col: int) -> object:
        """Value of the merged range covering (row, col) when it is a child; else get(row, col)."""
        parent = self.merged_parent.get((row, col))
        if parent is not None:
            return self.get(*parent)
        return self.get(row, col)

    def is_blank(self, row: int, cols: Iterable[int] | None = None) -> bool:
        """True when every cell in `cols` (default: all) is None or an empty/whitespace string."""
        if cols is None:
            cols = [c for (r, c) in self.cells if r == row]
        for c in cols:
            v = self.get(row, c)
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            return False
        return True

    def filter_last_row(self) -> int | None:
        ref = self.auto_filter_ref
        if not ref or ":" not in ref:
            return None
        try:
            return int(re.sub(r"\D", "", ref.split(":")[1]))
        except ValueError:
            return None

    def get(self, row: int, col: int) -> object:
        c = self.cells.get((row, col))
        return None if c is None else c.value

    def row_values(self, row: int) -> dict[int, object]:
        return {c: ci.value for (r, c), ci in sorted(self.cells.items())
                if r == row and ci.value is not None}

    def text_blobs(self) -> list[str]:
        """Every str value longer than 20 chars (title/footer blocks), document order."""
        return [ci.value for _, ci in sorted(self.cells.items())
                if isinstance(ci.value, str) and len(ci.value) > 20]


def col_letter(col: int) -> str:
    return get_column_letter(col)


def col_index(letter: str) -> int:
    return column_index_from_string(letter)


def _open(path: Path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as e:  # zipfile.BadZipFile, InvalidFileException, OSError ...
        raise ExcelReadError(f"Cannot read Excel file {path}: {e}",
                             message_vi=f"Cannot read Excel file: {Path(path).name}") from e


def list_sheets(path: Path) -> list[str]:
    wb = _open(Path(path))
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def load_grid(path: Path, sheet_name: str | None = None) -> SheetGrid:
    wb = _open(Path(path))
    try:
        if sheet_name is None:
            ws = wb.worksheets[0]
        elif sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
        else:
            raise ExcelReadError(f"Sheet not found: {sheet_name}",
                                 message_vi=f"Sheet not found: {sheet_name}")
        spans: dict[tuple[int, int], tuple[int, int]] = {}
        children: set[tuple[int, int]] = set()
        parents: dict[tuple[int, int], tuple[int, int]] = {}
        for rng in ws.merged_cells.ranges:
            spans[(rng.min_row, rng.min_col)] = (rng.max_row - rng.min_row + 1, rng.max_col - rng.min_col + 1)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    if (r, c) != (rng.min_row, rng.min_col):
                        children.add((r, c))
                        parents[(r, c)] = (rng.min_row, rng.min_col)
        cells: dict[tuple[int, int], CellInfo] = {}
        for row in ws.iter_rows():
            for c in row:
                key = (c.row, c.column)
                if key in children:
                    continue
                if c.value is None and key not in spans:
                    continue
                cells[key] = CellInfo(c.row, c.column, c.value, spans.get(key, (1, 1)), False)
        af = ""
        try:
            af = ws.auto_filter.ref or ""
        except Exception:
            af = ""
        return SheetGrid(ws.title, ws.max_row, ws.max_column, cells, parents, af)
    finally:
        wb.close()
