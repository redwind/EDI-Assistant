"""Cell value parsing (numbers with units, PO ids)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from edi_assistant.core.dates import parse_date_token

NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_PO_SEP_RE = re.compile(r"^(\d{7})\s*[-_/ ]\s*(\d{1,2})$")


def parse_decimal(v: object) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, Decimal):
        return v
    s = unicodedata.normalize("NFKC", str(v))
    s = re.sub(r"\s+", "", s.replace(",", ""))
    m = NUMBER_RE.search(s)
    return Decimal(m.group(0)) if m else None


def parse_int_exact(v: object) -> int | None:
    d = parse_decimal(v)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


def parse_po_cell(v: object) -> tuple[str, int | None] | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float):
        if v != int(v):
            return None
        raw = str(int(v))
    else:
        raw = unicodedata.normalize("NFKC", str(v)).strip()
    m = _PO_SEP_RE.match(raw)
    if m:
        line = int(m.group(2))
        return m.group(1), (line or None)
    if raw.endswith(".0"):
        raw = raw[:-2]
    s = re.sub(r"\D", "", raw)
    if len(s) == 7:
        return s, None
    if len(s) == 9:
        return s[:7], (int(s[7:]) or None)
    return None


def parse_line_cell(v: object) -> int | None:
    n = parse_int_exact(v)
    return n if n is not None and 1 <= n <= 99 else None


def format_weight(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01'), ROUND_HALF_UP):.2f}"


def to_text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def parse_date_cell(v: object) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not isinstance(v, str):
        return None
    t = v.strip()
    if not t:
        return None
    d = parse_date_token(t)
    if d:
        return d
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m and int(m.group(2)) > 12:       # day/month/year only when mdy is impossible
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def parse_text_or_blank(v: object) -> str:
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v != int(v):
            return str(v)
        return str(int(v))
    return str(v).strip()
