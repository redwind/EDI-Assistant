"""Layout fingerprint and JSON template store."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from edi_assistant.core import paths
from edi_assistant.core.models import FIELD_KEYS
from edi_assistant.core.textnorm import jaccard

from .header_detect import HeaderDetection
from .mapping import ColumnMapping, ColumnRef


TEMPLATE_VERSION = 2


def is_current(d: dict) -> bool:
    """A remembered layout is only reused when it was saved with today's field list. Layouts saved by older
    versions (other tracker formats, before Factory Name / Delivery Address existed) are dropped, so the
    columns are suggested afresh from the file's headers."""
    return int(d.get("version", 1)) >= TEMPLATE_VERSION and set(d.get("fields") or ()) == set(FIELD_KEYS)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(slots=True)
class Template:
    fingerprint: str
    name: str
    created_at: str
    updated_at: str
    sheet_name: str
    header_rows: list[int]
    header_tokens: list[str]
    columns: dict[str, ColumnRef | None]
    factory_id: str = ""
    use_count: int = 0
    profile: str = "packing_list"

    def to_mapping(self) -> ColumnMapping:
        m = ColumnMapping(profile=self.profile or "packing_list")
        for k in FIELD_KEYS:
            r = self.columns.get(k)
            m.columns[k] = ColumnRef(r.letter, r.header) if r else None
        return m

    def to_dict(self) -> dict:
        return {
            "version": TEMPLATE_VERSION,
            "fields": list(FIELD_KEYS),
            "fingerprint": self.fingerprint,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "sheet_name": self.sheet_name,
            "header_rows": list(self.header_rows),
            "header_tokens": list(self.header_tokens),
            "columns": {k: ({"letter": r.letter, "header": r.header} if r else None)
                        for k, r in ((k, self.columns.get(k)) for k in FIELD_KEYS)},
            "factory_id": self.factory_id,
            "use_count": self.use_count,
            "profile": self.profile,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Template":
        cols = {k: (ColumnRef(v["letter"], v["header"]) if v else None)
                for k, v in (d.get("columns") or {}).items()}
        return cls(d["fingerprint"], d.get("name", ""), d.get("created_at", ""), d.get("updated_at", ""),
                   d.get("sheet_name", ""), list(d.get("header_rows", [])), list(d.get("header_tokens", [])),
                   cols, d.get("factory_id", ""), int(d.get("use_count", 0)),
                   d.get("profile") or "packing_list")


def compute_fingerprint(det: HeaderDetection) -> tuple[str, list[str]]:
    tokens = sorted({c.normalized for c in det.columns if c.normalized})
    payload = json.dumps({"tokens": tokens, "ncols": len(det.columns)}, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest(), tokens


@dataclass(slots=True)
class TemplateMatch:
    template: Template
    kind: str            # "exact" | "similar"
    similarity: float


class TemplateStore:
    def __init__(self, directory: Path | None = None):
        self._dir = Path(directory) if directory else None

    @property
    def directory(self) -> Path:
        d = self._dir or paths.templates_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _load(self, p: Path) -> Template | None:
        """Template in `p`; None when corrupt. An outdated layout (see is_current) is deleted and ignored."""
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(d, dict):
            return None
        if not is_current(d):
            p.unlink(missing_ok=True)
            return None
        try:
            return Template.from_dict(d)
        except (KeyError, TypeError, ValueError):
            return None

    def list(self) -> list[Template]:
        return [t for p in sorted(self.directory.glob("*.json")) if (t := self._load(p)) is not None]

    def get(self, fingerprint: str) -> Template | None:
        p = self.directory / f"{fingerprint}.json"
        return self._load(p) if p.exists() else None

    def save(self, t: Template) -> None:
        t.updated_at = _now()
        p = self.directory / f"{t.fingerprint}.json"
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(t.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    def delete(self, fingerprint: str) -> None:
        (self.directory / f"{fingerprint}.json").unlink(missing_ok=True)

    def find(self, det: HeaderDetection) -> TemplateMatch | None:
        fp, tokens = compute_fingerprint(det)
        t = self.get(fp)
        if t:
            return TemplateMatch(t, "exact", 1.0)
        mine = set(tokens)
        best, best_s = None, 0.0
        for cand in self.list():
            s = jaccard(mine, set(cand.header_tokens))
            if s > best_s:
                best, best_s = cand, s
        if best and best_s >= 0.75:
            return TemplateMatch(best, "similar", best_s)
        return None

    def learn(self, det: HeaderDetection, mapping: ColumnMapping, name: str, factory_id: str,
              sheet_name: str) -> Template:
        fp, tokens = compute_fingerprint(det)
        t = self.get(fp)
        cols = {k: mapping.columns.get(k) for k in FIELD_KEYS}
        if t:
            t.use_count += 1
            t.columns = cols
            t.header_rows = list(det.header_rows)
            t.sheet_name = sheet_name
            t.profile = mapping.profile
            if name:
                t.name = name
            if factory_id:
                t.factory_id = factory_id
        else:
            now = _now()
            t = Template(fp, name, now, now, sheet_name, list(det.header_rows), tokens, cols, factory_id, 1, mapping.profile)
        self.save(t)
        return t
