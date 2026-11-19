"""FactoryStore (factories.json) + name suggestion + footer parsing."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict
from pathlib import Path

from edi_assistant.core import paths
from edi_assistant.core.models import FactoryAddress
from edi_assistant.core.textnorm import jaccard, normalize_company, token_set

from .rows import COMPANY_RE


class FactoryStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path else None

    @property
    def path(self) -> Path:
        return self._path or paths.factories_path()

    def list(self) -> list[FactoryAddress]:
        p = self.path
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for d in data.get("factories", []):
            known = {k: v for k, v in d.items() if k in FactoryAddress.__dataclass_fields__}
            try:
                out.append(FactoryAddress(**known))
            except TypeError:
                continue
        return out

    def _write(self, items: list[FactoryAddress]) -> None:
        p = self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "factories": [asdict(f) for f in items]},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    def get(self, factory_id: str) -> FactoryAddress | None:
        return next((f for f in self.list() if f.id == factory_id), None)

    def upsert(self, f: FactoryAddress) -> None:
        if not f.id:
            f.id = uuid.uuid4().hex
        items = self.list()
        for i, x in enumerate(items):
            if x.id == f.id:
                items[i] = f
                break
        else:
            items.append(f)
        self._write(items)

    def delete(self, factory_id: str) -> None:
        self._write([f for f in self.list() if f.id != factory_id])

    def merge(self, incoming: list[FactoryAddress]) -> tuple[int, int]:
        """Add/update factories by name (case/punctuation ignored); keeps ids and factories not in `incoming`.

        Returns (added, updated)."""
        items = self.list()
        by_key = {normalize_company(f.name) or f.name.lower(): i for i, f in enumerate(items)}
        added = updated = 0
        for f in incoming:
            key = normalize_company(f.name) or f.name.lower()
            if key in by_key:
                old = items[by_key[key]]
                f.id = old.id
                if not f.site_no:
                    f.site_no = old.site_no     # Site No is picked in the app, not in the Excel list
                items[by_key[key]] = f
                updated += 1
            else:
                f.id = f.id or uuid.uuid4().hex
                by_key[key] = len(items)
                items.append(f)
                added += 1
        self._write(items)
        return added, updated

    def by_file_code(self, file_name: str) -> FactoryAddress | None:
        """Factory whose Code equals the number at the start of the file name ('2596 - xxx.xlsx')."""
        m = re.match(r"\s*(\d+)", Path(file_name).name)
        if not m:
            return None
        return next((f for f in self.list() if f.code and f.code.strip().lstrip("0") == m.group(1).lstrip("0")),
                    None)

    def suggest(self, company_text: str) -> tuple[FactoryAddress | None, float]:
        target = normalize_company(company_text)
        if not target:
            return None, 0.0
        tset = token_set(target)
        best, best_s = None, 0.0
        for f in self.list():
            for name in [f.name, *f.aliases]:
                n = normalize_company(name)
                if not n:
                    continue
                s = jaccard(token_set(n), tset)
                if n in target or target in n:
                    s = 1.0
                if s > best_s:
                    best, best_s = f, s
        return (best, best_s) if best_s >= 0.5 else (None, best_s)


_COUNTRIES = {"china": "CHINA", "中国": "CHINA", "vietnam": "VIETNAM", "viet nam": "VIETNAM",
              "việt nam": "VIETNAM"}


def _split_name(line: str) -> tuple[str, str]:
    """Split 'NAME addr...' at the end of the contiguous run of company words."""
    ms = list(COMPANY_RE.finditer(line))
    if not ms:
        return line.strip(), ""
    end = ms[0].end()
    for m in ms[1:]:
        gap = line[end:m.start()]
        if re.search(r"\d", gap) or len(gap.split()) > 1:
            break
        end = m.end()
    return line[:end].strip(" ,"), line[end:].strip(" ,")


def factory_from_excel_footer(text: str) -> FactoryAddress:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    idx = next((i for i, ln in enumerate(lines) if COMPANY_RE.search(ln)), None)
    if idx is None:
        return FactoryAddress(id="", name="", address1="")
    name, rest = _split_name(lines[idx])
    # address may wrap onto following lines
    tail = " ".join(lines[idx + 1:idx + 3]) if idx + 1 < len(lines) else ""
    addr_text = (rest + " " + tail).strip() if rest else tail
    parts = [p.strip() for p in addr_text.split(",") if p.strip()]
    country = "CHINA"
    if parts and parts[-1].lower() in _COUNTRIES:
        country = _COUNTRIES[parts.pop().lower()]
    else:
        low = addr_text.lower()
        country = next((v for k, v in _COUNTRIES.items() if k in low), "CHINA")
    addr1 = addr2 = city = ""
    if len(parts) == 1:
        addr1 = parts[0]
    elif len(parts) == 2:
        addr1, city = parts
    elif len(parts) >= 3:
        addr1, city = parts[0], parts[-1]
        addr2 = ", ".join(parts[1:-1])
    return FactoryAddress(id="", name=name, address1=addr1, address2=addr2, city=city, country=country)


# ---------------------------------------------------------------- Excel factory list
_XLSX_COLUMNS = {
    "name": ("factory name", "factory", "name", "tên nhà máy"),
    "address1": ("address 1", "address1", "address line 1", "địa chỉ 1"),
    "address2": ("address 2", "address2", "address line 2", "địa chỉ 2"),
    "city": ("city", "thành phố"),
    "state": ("state", "province", "state province", "tỉnh"),
    "zip": ("zip", "zip code", "postal code", "postcode", "mã bưu điện"),
    "country": ("country", "quốc gia"),
    "aliases": ("aliases", "alias", "other names", "tên khác"),
    "code": ("code", "factory code", "mã"),
    "site_no": ("site no", "site", "site number"),
    "transport_method": ("transportation method", "transport method", "transportation"),
    "scac_code": ("scac code", "scac"),
}


def _norm_head(v: object) -> str:
    return " ".join(re.sub(r"[^\w ]", " ", str(v or "").lower()).split())


def _cell_text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return " ".join(str(v).split())


def read_factories_xlsx(path: str | Path) -> list[FactoryAddress]:
    """Read the factory list workbook (first sheet, header row with 'Factory Name').

    One row = one factory. Aliases are separated by ';' (or ',')."""
    from openpyxl import load_workbook

    from edi_assistant.core.errors import EdiAssistantError

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    lookup = {syn: key for key, syns in _XLSX_COLUMNS.items() for syn in syns}
    header_idx, cols = None, {}
    for i, row in enumerate(rows[:20]):
        found = {}
        for j, v in enumerate(row):
            key = lookup.get(_norm_head(v))
            if key and key not in found:
                found[key] = j
        if "name" in found and "address1" in found:
            header_idx, cols = i, found
            break
    if header_idx is None:
        raise EdiAssistantError("factory list header not found",
                                message_vi="Header row not found (needs 'Factory Name' and 'Address 1' columns) "
                                           "in the first sheet.")
    out: list[FactoryAddress] = []
    for row in rows[header_idx + 1:]:
        def get(key: str) -> str:
            j = cols.get(key)
            return _cell_text(row[j]) if j is not None and j < len(row) else ""
        name = get("name")
        if not name:
            continue
        aliases = [a.strip() for a in re.split(r"[;,\n]", get("aliases")) if a.strip()]
        scac = get("scac_code").split("-", 1)[0].strip().upper()   # 'MAEU-MAERSK' -> 'MAEU'
        out.append(FactoryAddress(
            id="", name=name, address1=get("address1"), address2=get("address2"), city=get("city"),
            state=get("state"), zip=get("zip"), country=(get("country") or "CHINA").upper(),
            site_no=get("site_no"), aliases=aliases, code=get("code"), transport_method=get("transport_method"),
            scac_code=scac))
    return out
