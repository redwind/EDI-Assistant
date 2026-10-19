"""Header row scoring and two-row header merge."""
from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass

from edi_assistant.core.errors import HeaderNotFoundError
from edi_assistant.core.textnorm import normalize_header

from .excel_reader import SheetGrid, col_letter
from .synonyms import is_headerish


@dataclass(slots=True)
class HeaderColumn:
    col: int
    letter: str
    texts: list[str]
    joined: str
    normalized: str
    span_cols: int


@dataclass(slots=True)
class HeaderDetection:
    header_rows: list[int]
    data_start_row: int
    columns: list[HeaderColumn]
    score: float


def _cells(grid: SheetGrid, row: int):
    return [grid.cells[(row, c)] for c in grid.row_values(row)]


def score_row(grid: SheetGrid, row: int) -> float:
    cells = _cells(grid, row)
    if len(cells) < 3:
        return -math.inf
    total = 0.0
    for ci in cells:
        v = ci.value
        if isinstance(v, str):
            if is_headerish(v):
                total += 3
            elif len(v) <= 30:
                total += 1
            elif len(v) > 40:
                total -= 1
        elif isinstance(v, (int, float, _dt.date, _dt.datetime)):
            total -= 2
        if ci.merged_span[1] >= 4:
            total -= 2
    return total


def detect_header(grid: SheetGrid, max_scan_rows: int = 40) -> HeaderDetection:
    last = min(max_scan_rows, grid.max_row)
    best_row, best = 0, -math.inf
    for r in range(1, last + 1):
        s = score_row(grid, r)
        if s > best:
            best_row, best = r, s
    if best_row == 0 or best < 6:
        raise HeaderNotFoundError("No header row found",
                                  message_vi="No header row found in the Excel file")
    rows = [best_row]
    p = best_row - 1
    if p >= 1:
        cp, ch = set(grid.row_values(p)), set(grid.row_values(best_row))
        if score_row(grid, p) >= 0.5 * best and cp and len(cp & ch) / len(cp) >= 0.5:
            rows = [p, best_row]
    cols: dict[int, list] = {}
    for r in rows:
        for c, v in grid.row_values(r).items():
            text = str(v).replace("\n", " ").strip()
            if text:
                cols.setdefault(c, []).append((text, grid.cells[(r, c)].merged_span[1]))
    columns = []
    for c in sorted(cols):
        texts = [t for t, _ in cols[c]]
        joined = " / ".join(texts)
        columns.append(HeaderColumn(c, col_letter(c), texts, joined, normalize_header(joined),
                                    max(s for _, s in cols[c])))
    return HeaderDetection(rows, max(rows) + 1, columns, best)
