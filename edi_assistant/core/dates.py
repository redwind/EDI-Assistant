"""Ship-date parsing and midpoint/intersection rules."""
from __future__ import annotations

import re
from datetime import date, timedelta

from .models import DateWindow, Flag, ShipDateResult

DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})\b"), "dmy_mon"),   # 09-MAR-26
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),                 # 03/11/2026
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_RE = r"(\d{1,2}-[A-Za-z]{3}-\d{2,4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})"


def parse_date_token(tok: str) -> date | None:
    tok = tok.strip()
    for rx, kind in DATE_PATTERNS:
        m = rx.fullmatch(tok)
        if not m:
            continue
        try:
            if kind == "dmy_mon":
                d, mon, y = m.groups()
                y = int(y)
                y = 2000 + y if y < 100 else y
                return date(y, _MONTHS[mon.lower()], int(d))
            if kind == "mdy":
                mo, d, y = m.groups()
                return date(int(y), int(mo), int(d))
            y, mo, d = m.groups()
            return date(int(y), int(mo), int(d))
        except (ValueError, KeyError):
            return None
    return None


def _dates_in(text: str) -> list[tuple[int, date]]:
    """All parseable date tokens with their start offsets, in order."""
    found = []
    for m in re.finditer(_DATE_RE, text):
        d = parse_date_token(m.group(1))
        if d:
            found.append((m.start(), d))
    return found


def _window(a: date, b: date) -> DateWindow:
    return DateWindow(a, b) if a <= b else DateWindow(b, a)


def parse_ship_dates(text: str) -> DateWindow | None:
    text = re.sub(r"\s+", " ", text or "")
    # A: inline labels
    m1 = re.search(r"Early\s*Ship\s*Date\s*[:\-]?\s*" + _DATE_RE, text, re.I)
    m2 = re.search(r"Late\s*Ship\s*Date\s*[:\-]?\s*" + _DATE_RE, text, re.I)
    if m1 and m2:
        d1, d2 = parse_date_token(m1.group(1)), parse_date_token(m2.group(1))
        if d1 and d2:
            return _window(d1, d2)
    # B: label block then value block
    hits = []
    for m in re.finditer(r"Order\s*Date|Early\s*Ship\s*Date|Late\s*Ship\s*Date", text, re.I):
        low = re.sub(r"\s+", "", m.group(0)).lower()
        hits.append((m.end(), {"orderdate": 0, "earlyshipdate": 1, "lateshipdate": 2}[low]))
    if hits:
        last_end = hits[-1][0]
        nxt = re.search(r"Ship\s*Date", text[last_end:], re.I)
        seg = text[last_end: last_end + nxt.start()] if nxt else text[last_end:]
        dates = [d for _, d in _dates_in(seg)]
        mapping = {}
        for k, (_, lab) in enumerate(hits):
            if k < len(dates):
                mapping[lab] = dates[k]
        if 1 in mapping and 2 in mapping:
            return _window(mapping[1], mapping[2])
    # C: two dates shortly after 'Ship Date'
    m = re.search(r"Ship\s*Date", text, re.I)
    if m:
        dates = [d for _, d in _dates_in(text[m.end(): m.end() + 60])]
        if len(dates) == 2:
            return _window(dates[0], dates[1])
    return None


def midpoint(w: DateWindow) -> date:
    return w.early + timedelta(days=(w.late - w.early).days // 2)


def intersect(windows: list[DateWindow]) -> DateWindow | None:
    if not windows:
        return None
    e = max(w.early for w in windows)
    l = min(w.late for w in windows)
    return DateWindow(e, l) if e <= l else None


def compute_shipping_date(windows: list[DateWindow], today: date) -> ShipDateResult:
    flags: list[Flag] = []
    w = intersect(windows)
    inter = w
    if w is None:
        w = windows[0]
        flags.append(Flag("no_date_intersection",
                          "Ship date windows of the POs do not overlap; using the midpoint of the first PO"))
    d = midpoint(w)
    if d < today:
        # Binding decision: a past midpoint is replaced by today (the portal rejects past shipping dates, so a
        # past "late" date would never be accepted either). flow.past_date_policy='ask' lets the user override in S4.
        d = today
        flags.append(Flag("date_in_past", "Midpoint of the ship window is in the past; using today"))
    return ShipDateResult(d, inter, flags)


def format_mdy(d: date) -> str:
    return d.strftime("%m/%d/%Y")
