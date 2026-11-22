"""SafeActions: guarded click/fill/select with logging and abort checks."""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from edi_assistant.core.config import FlowConfig
from edi_assistant.core.errors import DataMismatchError, ForbiddenActionError, PostconditionFailed, UserAbortError
from edi_assistant.core.events import EventSink, LogEvent

from .selectors import SelectorCandidate, SelectorResolver
from .session import BrowserSession

FORBIDDEN_NAME_IDS = {"btnSubmitASN", "cancelShipment", "btnCancel"}
FORBIDDEN_TEXT_RE = re.compile(r"submit", re.I)
NAV_TIMEOUT_MS = 30000   # the EDI server sometimes needs 10-20 s for a page
SAVE_NAV_TIMEOUT_MS = 60000   # Save clicks: wait longer for the server response page (a rejected Save must be seen)
TYPE_CHUNK = 8         # characters typed per press_sequentially call (abort is checked between chunks)
SELECT_SETTLE_MS = 150  # let onchange handlers run before reading a select back

_ATTRS_JS = """el => {
  const grab = e => e ? ({name: e.name||"", id: e.id||"", value: (typeof e.value === 'string' ? e.value : "")||"",
     text: (e.innerText||e.textContent||"").trim().slice(0, 200), onclick: (e.getAttribute("onclick")||"")}) : null;
  return [grab(el), grab(el.closest('button,a,input[type=submit],input[type=button]'))];
}"""
_IS_PASSWORD_JS = "el => (el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'password')"


def forbidden_reason_from_attrs(infos: list[dict | None], *, click_validate: bool = False) -> str:
    """Pure check over [attrs(el), attrs(closest button/link)] dicts (name/id/value/text/onclick).
    Single source of truth for G1/G8: used by SafeActions, by healing (AI proposals) and by picker.js payloads
    (calibrate), so that no candidate can ever target a guarded element."""
    for a in infos or []:
        if not a:
            continue
        name, id_, value = str(a.get("name", "")), str(a.get("id", "")), str(a.get("value", ""))
        text, onclick = str(a.get("text", "")), str(a.get("onclick", ""))
        if name in FORBIDDEN_NAME_IDS or id_ in FORBIDDEN_NAME_IDS:
            return f"forbidden element {name or id_}"
        if "asn.do" in onclick or FORBIDDEN_TEXT_RE.search(value) or FORBIDDEN_TEXT_RE.search(text):
            return "submit-like element"
        if name == "validateShipment" and not click_validate:
            return "validateShipment"
        if text.strip().lower() == "remove":
            return "Remove link"
    return ""


def forbidden_reason(loc: Locator, *, click_validate: bool = False) -> str:
    """Why clicking `loc` is forbidden ('' when allowed). Must not be called from inside a Playwright callback."""
    return forbidden_reason_from_attrs(loc.evaluate(_ATTRS_JS), click_validate=click_validate)


def is_password_field(loc: Locator) -> bool:
    return bool(loc.evaluate(_IS_PASSWORD_JS))


class SafeActions:
    def __init__(self, session: BrowserSession, resolver: SelectorResolver, abort_event: threading.Event,
                 sink: EventSink, log: logging.Logger, flow_cfg: FlowConfig):
        self.session = session
        self.resolver = resolver
        self.abort_event = abort_event
        self.sink = sink
        self.log = log
        self.flow_cfg = flow_cfg

    # ------------------------------------------------------------------ helpers
    def _check_abort(self) -> None:
        if self.abort_event.is_set():
            raise UserAbortError("aborted by user", message_vi="Aborted by user")

    def _dbg(self, msg: str) -> None:
        self.log.debug(msg)
        try:
            self.sink(LogEvent(level="DEBUG", message=msg))
        except Exception:
            pass

    @property
    def page(self):
        return self.session.page

    @property
    def pacer(self):
        return self.session.pacer

    def _pace(self) -> None:
        """Random human-like delay between actions (no-op unless human-pace mode is active)."""
        p = self.pacer
        if p is not None:
            p.sleep_action()
        self.session.check_blocked()

    def _after_navigation(self) -> None:
        self.session.after_navigation()

    def resolve(self, key: str, vars: dict | None = None, timeout_ms: int = 4000,
                require_visible: bool = True) -> tuple[Locator, SelectorCandidate]:
        self._check_abort()
        return self.resolver.resolve(self.page, key, vars, timeout_ms=timeout_ms, require_visible=require_visible)

    def _guard_click(self, loc: Locator) -> None:
        why = forbidden_reason(loc, click_validate=self.flow_cfg.click_validate)
        if why:
            msgs = {"submit-like element": "The tool never clicks Submit ASN",
                    "validateShipment": "Clicking Validate is not allowed", "Remove link": "Clicking Remove is not allowed"}
            raise ForbiddenActionError(f"click refused: {why}",
                                       message_vi=msgs.get(why, "The tool is not allowed to click this button"))

    # ------------------------------------------------------------------ actions
    def click(self, key: str, vars: dict | None = None, *, timeout_ms: int = 4000, expect_navigation: bool = False,
              nav_timeout_ms: int | None = None) -> bool:
        loc, cand = self.resolve(key, vars, timeout_ms)
        self._dbg(f"click {key} via {cand.describe()}")
        return self.click_locator(loc, expect_navigation=expect_navigation, nav_timeout_ms=nav_timeout_ms)

    def click_locator(self, loc: Locator, *, expect_navigation: bool = False, nav_timeout_ms: int | None = None) -> bool:
        """Guarded click. Returns True when `expect_navigation` was set and a navigation was observed
        (post-Save checks use this: no reload after Save is never treated as success)."""
        self._check_abort()
        self._guard_click(loc)
        if self.pacer is not None and self.pacer.enabled:
            loc.scroll_into_view_if_needed()   # human-pace only; click() auto-scrolls and actionability-checks anyway
        self._pace()
        navigated = False
        if expect_navigation:
            try:
                with self.page.expect_navigation(wait_until="domcontentloaded",
                                                 timeout=nav_timeout_ms or NAV_TIMEOUT_MS):
                    loc.click()
                navigated = True
            except PlaywrightTimeoutError:
                self.log.warning("no navigation after click (step postcondition decides)")
            self._after_navigation()
        else:
            loc.click()
        return navigated

    def fill(self, key: str, value: str, vars: dict | None = None, *, dispatch_change: bool = False) -> None:
        loc, cand = self.resolve(key, vars)
        self._dbg(f"fill {key} via {cand.describe()}")
        self.fill_locator(loc, value, dispatch_change=dispatch_change)

    def fill_locator(self, loc: Locator, value: str, *, dispatch_change: bool = False) -> None:
        self._check_abort()
        if is_password_field(loc):   # G9: the tool never types into a password box (even via a learned/AI locator)
            raise ForbiddenActionError("fill refused: password field", message_vi="The tool never types passwords")
        self._pace()
        p = self.pacer
        if p is not None and p.enabled and value:
            self._type(loc, value, p)
        else:
            loc.fill(value)
        if dispatch_change:
            loc.dispatch_event("change")

    def _type(self, loc: Locator, value: str, pacer) -> None:
        """Clear the field, type the value with per-keystroke delays, verify; fall back to fill() on mismatch."""
        loc.fill("")
        for i in range(0, len(value), TYPE_CHUNK):
            self._check_abort()
            loc.press_sequentially(value[i:i + TYPE_CHUNK], delay=pacer.type_delay())
        if loc.input_value() != value:
            self.log.warning("typed value mismatch; retrying with fill()")
            loc.fill(value)
            if loc.input_value() != value:
                raise PostconditionFailed("typed value not accepted", message_vi="The field did not accept the typed value")

    def select(self, key: str, *, value: str | None = None, label: str | None = None, label_prefix: str | None = None,
               label_contains: str | None = None, vars: dict | None = None) -> str:
        loc, cand = self.resolve(key, vars)
        self._dbg(f"select {key} via {cand.describe()}")
        try:
            return self.select_locator(loc, value=value, label=label, label_prefix=label_prefix,
                                       label_contains=label_contains)
        except DataMismatchError as ex:
            ex.ctx["key"] = key
            ex.message_vi = f'Option "{ex.ctx.get("wanted")}" not found in list {key}'
            raise

    def select_locator(self, loc: Locator, *, value: str | None = None, label: str | None = None,
                       label_prefix: str | None = None, label_contains: str | None = None) -> str:
        """value match -> exact label -> text startswith label_prefix -> contains (case-insensitive)."""
        self._check_abort()
        opts: list[list[str]] = loc.evaluate("el => [...el.options].map(o => [o.value, (o.text||'').trim()])")
        chosen: list[str] | None = None
        if value is not None:
            chosen = next((o for o in opts if o[0] == value), None)
        if chosen is None and label is not None:
            chosen = next((o for o in opts if o[1].lower() == label.lower()), None)
        if chosen is None and label_prefix:
            chosen = next((o for o in opts if o[1].lower().startswith(label_prefix.lower())), None)
        if chosen is None and label_contains:
            chosen = next((o for o in opts if label_contains.lower() in o[1].lower()), None)
        if chosen is None:
            wanted = value or label or label_prefix or label_contains or ""
            raise DataMismatchError(f'option "{wanted}" not found', message_vi=f'Option "{wanted}" not found',
                                    options=[o[1] for o in opts], wanted=wanted)
        self._pace()
        loc.select_option(value=chosen[0])
        if self.pacer is not None and self.pacer.enabled:
            self.page.wait_for_timeout(SELECT_SETTLE_MS)   # onchange handlers (SCAC -> carrier, weights -> hidden)
            if loc.input_value() != chosen[0]:
                self.log.warning("select read-back mismatch; retrying once")
                loc.select_option(value=chosen[0])
                if loc.input_value() != chosen[0]:
                    raise PostconditionFailed(f'selection "{chosen[1]}" did not stick',
                                              message_vi=f'The selection "{chosen[1]}" did not stick')
        return chosen[1]

    def check(self, key: str, vars: dict | None = None) -> None:
        loc, cand = self.resolve(key, vars)
        self._dbg(f"check {key} via {cand.describe()}")
        self._check_abort()
        self._pace()
        loc.check()

    def read_value(self, key: str, vars: dict | None = None, timeout_ms: int = 4000) -> str:
        loc, _ = self.resolve(key, vars, timeout_ms, require_visible=False)
        return self.value_of(loc)

    @staticmethod
    def value_of(loc: Locator) -> str:
        is_field = loc.evaluate("el => ['INPUT','SELECT','TEXTAREA'].includes(el.tagName)")
        return (loc.input_value() if is_field else loc.inner_text()).strip()

    def read_text(self, key: str, vars: dict | None = None, timeout_ms: int = 4000) -> str:
        loc, _ = self.resolve(key, vars, timeout_ms, require_visible=False)
        return loc.inner_text().strip()

    def exists(self, key: str, vars: dict | None = None, timeout_ms: int = 1500) -> bool:
        self._check_abort()
        return self.resolver.exists(self.page, key, vars, timeout_ms)

    def _wait_until(self, pred, timeout_ms: int) -> bool:
        import time
        end = time.monotonic() + timeout_ms / 1000
        while True:
            self._check_abort()
            try:
                if pred():
                    return True
            except PlaywrightError:
                pass
            if time.monotonic() >= end:
                return False
            self.page.wait_for_timeout(150)

    def wait_title_contains(self, text: str, timeout_ms: int) -> bool:
        return self._wait_until(lambda: text in self.session.title(), timeout_ms)

    def wait_url_contains(self, text: str, timeout_ms: int) -> bool:
        return self._wait_until(lambda: text in self.session.url(), timeout_ms)

    def body_text(self) -> str:
        return self.page.locator("body").inner_text()
