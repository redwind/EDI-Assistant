"""Calibrate mode: highlight a key, pick an element, inspector."""
from __future__ import annotations

import logging
import weakref
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from edi_assistant.core.errors import ElementNotFoundError
from edi_assistant.core.events import CalibrationResult, EventSink, LogEvent

from .actions import forbidden_reason_from_attrs
from .selectors import SelectorCandidate, SelectorResolver, SelectorStore
from .session import BrowserSession

PICKER_JS = Path(__file__).with_name("picker.js")
_HIGHLIGHT_JS = """el => { const o = el.style.outline, t = el.style.outlineOffset;
  el.style.outline = '3px solid #ff3b30'; el.style.outlineOffset = '2px';
  el.scrollIntoView({block: 'center'});
  setTimeout(() => { el.style.outline = o; el.style.outlineOffset = t; }, 4000); }"""


def picker_source() -> str:
    try:
        return PICKER_JS.read_text(encoding="utf-8")
    except OSError:   # frozen app: fall back to importlib.resources
        from importlib.resources import files
        return (files("edi_assistant.automation") / "picker.js").read_text(encoding="utf-8")


class Calibrator:
    def __init__(self, session: BrowserSession, store: SelectorStore, resolver: SelectorResolver,
                 sink: EventSink, log: logging.Logger):
        self.session, self.store, self.resolver, self.sink, self.log = session, store, resolver, sink, log
        self._key = ""
        self._exposed: weakref.WeakSet = weakref.WeakSet()

    def _info(self, level: str, msg: str) -> None:
        self.log.log(getattr(logging, level), msg)
        self.sink(LogEvent(level=level, message=msg))

    def highlight(self, key: str, vars: dict) -> bool:
        try:
            loc, cand = self.resolver.resolve(self.session.page, key, vars, timeout_ms=2000)
            loc.evaluate(_HIGHLIGHT_JS)
        except (ElementNotFoundError, PlaywrightError) as ex:
            self._info("WARNING", f"highlight {key}: not found ({ex})")
            return False
        self._info("INFO", f"highlight ok via {cand.describe()}")
        return True

    def pick(self, key: str) -> None:
        page = self.session.page
        self._key = key
        if page not in self._exposed:
            try:
                page.expose_binding("__ediPicked", self._on_picked)
            except PlaywrightError as ex:
                if "already" not in str(ex).lower():   # "function already registered" == success
                    raise
            self._exposed.add(page)
        page.evaluate(picker_source())
        page.evaluate("k => window.__ediPickerStart(k)", key)

    def cancel_pick(self) -> None:
        try:
            self.session.page.evaluate("() => window.__ediPickerCancel && window.__ediPickerCancel()")
        except PlaywrightError:
            pass
        self.sink(CalibrationResult(key=self._key, candidate=None, saved=False))

    def _on_picked(self, source, payload: dict) -> None:
        cands = (payload or {}).get("candidates") or []
        key = self._key
        if not cands:
            self.sink(CalibrationResult(key=key, candidate=None, saved=False))
            return
        best = SelectorCandidate.from_dict(cands[0])
        best.source = "learned"
        # Never learn a guarded element (Submit ASN / Cancel / Clear / Remove / password) for any key.
        # picker.js ships the element attributes with the payload: this runs inside a Playwright binding
        # callback, where making further Playwright calls would deadlock the sync API.
        payload = payload or {}
        why = forbidden_reason_from_attrs(payload.get("element") or [])
        if not why and payload.get("password"):
            why = "password field"
        if why:
            self._info("WARNING", f"pick for {key} refused: {why}")
            self.sink(CalibrationResult(key=key, candidate=None, saved=False))
            return
        site = self.session.site.effective_base_url()
        self.store.add_learned(key, best, "learned", site=site)
        self.store.mark_verified(key)
        self._info("INFO", f"learned {key} <- {best.describe()}")
        self.sink(CalibrationResult(key=key, candidate=best.to_dict(), saved=True))

    def open_inspector(self) -> None:
        """Blocks the worker thread until the Playwright inspector is closed (headed browsers only)."""
        if self.session.cfg.headless:
            self._info("WARNING", "inspector unavailable in headless mode")
            return
        self.session.page.pause()
