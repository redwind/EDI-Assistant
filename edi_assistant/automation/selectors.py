"""Selector store (bundled + learned YAML), resolver and row-key extraction."""
from __future__ import annotations

import logging
import os
import re
import string
import time
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from edi_assistant.core.errors import ElementNotFoundError

KINDS = {"css", "xpath", "text", "role", "label", "placeholder"}
ALLOWED_VARS = {"po", "master_po", "line", "line2", "item_label", "site_no", "shipment_id", "row_key", "vendor"}
_TEMPLATED = ("css", "xpath", "text", "name", "has_text")


PROBE_MS = 300   # budgets at or below this are optional/negative probes: a single candidate sweep, no sleeping


@dataclass(slots=True)
class SelectorCandidate:
    kind: str
    css: str = ""
    xpath: str = ""
    text: str = ""
    role: str = ""
    name: str = ""
    exact: bool = False
    within: str = ""
    has_text: str = ""
    nth: int | None = None
    source: str = "bundled"       # "bundled" | "learned" | "ai"
    note: str = ""

    def describe(self) -> str:
        k = self.kind
        if k == "css":
            s = f"css={self.css}"
        elif k == "xpath":
            s = f"xpath={self.xpath}"
        elif k == "role":
            s = f"role={self.role}" + (f"[name='{self.name}']" if self.name else "")
        else:
            s = f"{k}={self.text}"
        if self.exact and k in ("text", "label", "role"):
            s += " (exact)"
        if self.has_text:
            s += f" has_text={self.has_text}"
        if self.within:
            s += f" within={self.within}"
        if self.nth is not None:
            s += f" nth={self.nth}"
        return s

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        for f in fields(self):
            if f.name in ("kind", "source"):
                continue
            v = getattr(self, f.name)
            if v not in ("", False, None):
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SelectorCandidate":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in d.items() if k in names}
        kw.setdefault("kind", "css")
        return cls(**kw)


@dataclass(slots=True)
class SelectorKey:
    key: str
    description: str
    page: str
    verified: bool
    candidates: list[SelectorCandidate]


def _read_yaml(p: Path) -> dict:
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    return d if isinstance(d, dict) else {}


def _cands(raw: list | None, source: str) -> list[SelectorCandidate]:
    out = []
    for d in raw or []:
        c = SelectorCandidate.from_dict(d)
        c.source = d.get("source", source) if source != "bundled" else "bundled"
        out.append(c)
    return out


class SelectorStore:
    def __init__(self, bundled_path: Path, learned_path: Path):
        self.bundled_path = Path(bundled_path)
        self.learned_path = Path(learned_path)
        self._bundled: dict[str, dict] = {}
        self._learned: dict[str, dict] = {}

    def load(self) -> None:
        self._bundled = dict((_read_yaml(self.bundled_path).get("keys")) or {})
        self._learned = dict((_read_yaml(self.learned_path).get("keys")) or {})

    def validate(self) -> list[str]:
        errs: list[str] = []
        for key, spec in self._bundled.items():
            for i, d in enumerate(spec.get("candidates") or []):
                c = SelectorCandidate.from_dict(d)
                where = f"{key}[{i}]"
                if c.kind not in KINDS:
                    errs.append(f"{where}: unknown kind {c.kind!r}")
                    continue
                need = {"css": c.css, "xpath": c.xpath, "text": c.text, "label": c.text,
                        "placeholder": c.text, "role": c.role}[c.kind]
                if not need:
                    errs.append(f"{where}: missing value for kind {c.kind}")
                for fld in _TEMPLATED:
                    val = getattr(c, fld)
                    try:
                        names = {n for _, n, _, _ in string.Formatter().parse(val) if n}
                    except ValueError as ex:
                        errs.append(f"{where}.{fld}: bad template ({ex})")
                        continue
                    for n in names - ALLOWED_VARS:
                        errs.append(f"{where}.{fld}: unknown placeholder {{{n}}}")
                if c.within and c.within not in self._bundled:
                    errs.append(f"{where}: unknown within key {c.within!r}")
        return errs

    def keys(self) -> list[SelectorKey]:
        return [self.get(k) for k in self._bundled]

    def get(self, key: str) -> SelectorKey:
        if key not in self._bundled:
            raise KeyError(key)
        spec = self._bundled[key]
        lrn = self._learned.get(key) or {}
        verified = bool(lrn["verified"]) if "verified" in lrn else bool(spec.get("verified", False))
        return SelectorKey(key, spec.get("description", ""), spec.get("page", ""), verified, self.candidates(key))

    def candidates(self, key: str) -> list[SelectorCandidate]:
        if key not in self._bundled:
            raise KeyError(key)
        lrn = _cands((self._learned.get(key) or {}).get("candidates"), "learned")
        bun = _cands(self._bundled[key].get("candidates"), "bundled")
        seen: set[str] = set()
        out = []
        for c in lrn + bun:
            d = c.describe()
            if d not in seen:
                seen.add(d)
                out.append(c)
        return out

    def _write_learned(self) -> None:
        self.learned_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.learned_path.with_suffix(self.learned_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"version": 1, "keys": self._learned}, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp, self.learned_path)

    def add_learned(self, key: str, cand: SelectorCandidate, source: str, site: str = "") -> None:
        if key not in self._bundled:
            raise KeyError(key)
        d = cand.to_dict()
        d.update(source=source, learned_at=datetime.now().isoformat(timespec="seconds"))
        if site:
            d["site"] = site
        entry = self._learned.setdefault(key, {})
        lst = [x for x in entry.get("candidates", []) if SelectorCandidate.from_dict(x).describe() != cand.describe()]
        entry["candidates"] = [d] + lst
        self._write_learned()

    def remove_learned(self, key: str, describe: str) -> None:
        entry = self._learned.get(key)
        if not entry:
            return
        entry["candidates"] = [x for x in entry.get("candidates", [])
                               if SelectorCandidate.from_dict(x).describe() != describe]
        self._write_learned()

    def mark_verified(self, key: str) -> None:
        self._learned.setdefault(key, {})["verified"] = True
        self._write_learned()


class _Skip(Exception):
    """Candidate not applicable for the given vars."""


def _fmt(s: str, vars: dict[str, str]) -> str:
    if not s or "{" not in s:
        return s
    try:
        return s.format_map(vars)
    except KeyError as ex:
        raise _Skip(str(ex)) from ex
    except (ValueError, IndexError):
        return s   # literal braces in a learned selector


def _wait(page: Any, ms: int) -> None:
    p = page if hasattr(page, "wait_for_timeout") else page.page
    p.wait_for_timeout(ms)


class SelectorResolver:
    def __init__(self, store: SelectorStore, log: logging.Logger):
        self.store = store
        self.log = log

    def build(self, page: Page | Locator, cand: SelectorCandidate, vars: dict[str, str],
              within_timeout_ms: int = 1500) -> Locator:
        root: Any = page
        if cand.within:
            root, _ = self.resolve(page, cand.within, vars, timeout_ms=within_timeout_ms)
        k = cand.kind
        if k == "css":
            loc = root.locator(_fmt(cand.css, vars))
        elif k == "xpath":
            loc = root.locator("xpath=" + _fmt(cand.xpath, vars))
        elif k == "text":
            loc = root.get_by_text(_fmt(cand.text, vars), exact=cand.exact)
        elif k == "role":
            name = _fmt(cand.name, vars) if cand.name else None
            loc = root.get_by_role(cand.role, name=name, exact=cand.exact)
        elif k == "label":
            loc = root.get_by_label(_fmt(cand.text, vars), exact=cand.exact)
        elif k == "placeholder":
            loc = root.get_by_placeholder(_fmt(cand.text, vars), exact=cand.exact)
        else:
            raise ValueError(f"unknown selector kind {k!r}")
        if cand.has_text:
            loc = loc.filter(has_text=_fmt(cand.has_text, vars))
        if cand.nth is not None:
            loc = loc.last if cand.nth == -1 else loc.nth(cand.nth)
        return loc

    def resolve(self, page: Page | Locator, key: str, vars: dict[str, str] | None = None,
                timeout_ms: int = 4000, require_visible: bool = True) -> tuple[Locator, SelectorCandidate]:
        vars = vars or {}
        cands = self.store.candidates(key)
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            # one sweep over all candidates in priority order (fair: no candidate starves the others)
            unstable = False   # a PlaywrightError during the sweep = page in flux: this sweep proves nothing
            for cand in cands:
                try:
                    loc = self.build(page, cand, vars, within_timeout_ms=0)
                    n = loc.count()
                    if n >= 1:
                        if n > 1 and cand.nth is None:
                            self.log.warning("ambiguous selector %s via %s (%d matches)", key, cand.describe(), n)
                        pick = loc.first
                        if not require_visible or pick.is_visible():
                            return pick, cand
                except (_Skip, ElementNotFoundError):
                    continue
                except PlaywrightError:
                    unstable = True
                    continue   # page navigating; retry next sweep
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (timeout_ms <= PROBE_MS and not unstable):
                # probe budget: ONE CLEAN sweep decides absence; a sweep disturbed by a navigation keeps polling
                # until the (short) deadline so that a post-action check never mistakes "page in flux" for "absent"
                break
            _wait(page, int(min(150, remaining * 1000)) or 1)
        raise ElementNotFoundError(f"element not found: {key}", message_vi=f"Element not found: {key}",
                                   key=key, tried=[c.describe() for c in cands])

    def try_resolve(self, page: Page, key: str, vars: dict[str, str] | None = None,
                    timeout_ms: int = 1500) -> Locator | None:
        try:
            return self.resolve(page, key, vars, timeout_ms=timeout_ms)[0]
        except ElementNotFoundError:
            return None

    def exists(self, page: Page, key: str, vars: dict[str, str] | None = None, timeout_ms: int = 1500) -> bool:
        return self.try_resolve(page, key, vars, timeout_ms) is not None


ROW_KEY_PATTERNS = {
    "pos": re.compile(r"^(?:complete_shipment_|pack_code_|web_sh_packing_type_id_|PO-)(\d+)$"),
    "weight": re.compile(r"^editedSiteWgt(?:qu|um)(\d+)$"),
}


def extract_row_key(row: Locator, page_kind: str) -> str:
    """Numeric id of per-row controls, derived from name/id attributes of inputs inside the row."""
    attrs = row.evaluate(
        "r => [...r.querySelectorAll('input,select')].flatMap(e => [e.name || '', e.id || ''])")
    pat = ROW_KEY_PATTERNS[page_kind]
    for a in attrs:
        m = pat.match(a or "")
        if m:
            return m.group(1)
    raise ElementNotFoundError(f"row key not found ({page_kind})", message_vi="Could not determine the row key",
                               key=f"{page_kind}.row_key", tried=[])
