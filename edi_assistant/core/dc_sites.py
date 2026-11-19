"""TO Site No (Burlington DC) from a tracker "Delivery Address".

EDI notice: "DC addresses have been changed. When creating shipment ID, please use: CA=512, NJ=053, GA=934".
The address keeps the Bur-tools form "Name, Street, CITY, ST 12345"."""
from __future__ import annotations

import re

DEFAULT_TO_SITES: dict[str, str] = {"CA": "512", "NJ": "053", "GA": "934"}

_STATE_ZIP = re.compile(r"\b([A-Za-z]{2})\.?\s+(\d{5})(?:-\d{4})?\s*$")


def state_of(address: str) -> str:
    """Two-letter state of "..., CITY, ST 12345" ('' when the address does not end that way)."""
    m = _STATE_ZIP.search(" ".join(str(address or "").split()))
    return m.group(1).upper() if m else ""


def zip_of(address: str) -> str:
    m = _STATE_ZIP.search(" ".join(str(address or "").split()))
    return m.group(2) if m else ""


def site_for(address: str, table: dict[str, str] | None = None) -> str:
    """Site No for the address' state ('' when the state is unknown or not in the table)."""
    tbl = {str(k).strip().upper(): str(v).strip() for k, v in (table or DEFAULT_TO_SITES).items()}
    return tbl.get(state_of(address), "")


def same_site(a: str, b: str) -> bool:
    """'053' == '53' == ' 053 '."""
    a, b = str(a or "").strip(), str(b or "").strip()
    return bool(a) and bool(b) and (a == b or (a.isdigit() and b.isdigit() and int(a) == int(b)))


def pick_option(options: list[tuple[str, str]], site: str) -> str | None:
    """Value of the <option> (value, text) for `site`: exact value/text, then text starting with the number."""
    for v, t in options:
        if same_site(v, site) or same_site(t, site):
            return v
    for v, t in options:
        lead = re.match(r"\s*(\d+)\b", t or "")
        if lead and same_site(lead.group(1), site):
            return v
    return None


def parse_table(text: str) -> dict[str, str]:
    """'CA=512, NJ=053; GA=934' -> {'CA': '512', ...} (bad pieces ignored)."""
    out: dict[str, str] = {}
    for part in re.split(r"[,;\n]+", text or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip().upper(), v.strip()
            if re.fullmatch(r"[A-Z]{2}", k) and v:
                out[k] = v
    return out


def format_table(table: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in table.items())
