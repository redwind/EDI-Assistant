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
