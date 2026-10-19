"""Healer: budgeted AI locator proposals, error explanations and date reading."""
from __future__ import annotations

import logging

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from edi_assistant.core.ai_interface import (ExplainRequest, Explanation, LocatorRequest, ReadFieldsRequest,
                                              VisionAdvisor)
from edi_assistant.core.dates import parse_date_token
from edi_assistant.core.errors import AiError
from edi_assistant.core.events import EventSink, LogEvent
from edi_assistant.core.models import DateWindow

from .actions import forbidden_reason, is_password_field
from .dom_snapshot import PageSnapshot
from .selectors import SelectorCandidate, SelectorResolver, SelectorStore


class Healer:
    def __init__(self, advisor: VisionAdvisor | None, store: SelectorStore, resolver: SelectorResolver,
                 max_calls: int, vision: bool, sink: EventSink, log: logging.Logger):
        self.advisor = advisor
        self.store = store
        self.resolver = resolver
        self.max_calls = max_calls
        self.vision = vision
        self.sink = sink
        self.log = log
        self.calls_used = 0

    def can_call(self) -> bool:
        return self.advisor is not None and self.calls_used < self.max_calls

    def _image(self, snap: PageSnapshot) -> bytes | None:
        return snap.screenshot_jpeg if (self.vision and snap.screenshot_jpeg) else None

    def heal_locator(self, page: Page, key: str, vars: dict, snap: PageSnapshot) -> Locator | None:
        if not self.can_call():
            return None
        try:
            desc = self.store.get(key).description
        except KeyError:
            desc = ""
        tried = [c.describe() for c in self.store.candidates(key)]
        req = LocatorRequest(key=key, description=desc, page_url=snap.url, page_title=snap.title,
                             aria_snapshot=snap.aria, dom_excerpt=snap.dom, screenshot_jpeg=self._image(snap), tried=tried)
        self.calls_used += 1
        try:
            proposal = self.advisor.propose_locator(req)  # type: ignore[union-attr]
        except AiError as ex:
            self.log.warning("AI propose_locator failed: %s", ex)
            return None
        if proposal is None:
            return None
        for d in proposal.candidates[:3]:
            try:
                cand = SelectorCandidate.from_dict(d)
                cand.source = "ai"
                loc = self.resolver.build(page, cand, vars)
                if loc.count() >= 1 and loc.first.is_visible():
                    why = forbidden_reason(loc.first) or ("password field" if is_password_field(loc.first) else "")
                    if why:   # an AI proposal must never point a key at a guarded element
                        self.sink(LogEvent(level="WARNING", message=f"AI candidate for {key} rejected: {why}"))
                        continue
                    self.store.add_learned(key, cand, "ai", site="")
                    self.sink(LogEvent(level="INFO", message=f"learned selector {key} <- {cand.describe()}"))
                    return loc.first
            except (PlaywrightError, KeyError, ValueError, TypeError) as ex:
                self.log.debug("AI candidate rejected: %s", ex)
        return None

    def explain(self, step_id: str, title_vi: str, err: Exception, snap: PageSnapshot) -> Explanation | None:
        if not self.can_call():
            return None
        req = ExplainRequest(step_id=step_id, step_title_vi=title_vi, error_text=str(err), page_url=snap.url,
                             aria_snapshot=snap.aria, dom_excerpt=snap.dom, screenshot_jpeg=self._image(snap))
        self.calls_used += 1
        try:
            return self.advisor.explain_error(req)  # type: ignore[union-attr]
        except AiError as ex:
            self.log.warning("AI explain_error failed: %s", ex)
            return None

    def read_dates(self, snap: PageSnapshot) -> DateWindow | None:
        if not self.can_call() or not self.vision or not getattr(self.advisor, "supports_vision", False) \
                or not snap.screenshot_jpeg:
            return None
        req = ReadFieldsRequest(
            fields=["early_ship_date", "late_ship_date"],
            hint="PO document; labels 'Early Ship Date' and 'Late Ship Date' with values like 09-MAR-26",
            screenshot_jpeg=snap.screenshot_jpeg)
        self.calls_used += 1
        try:
            res = self.advisor.read_fields(req)  # type: ignore[union-attr]
        except AiError as ex:
            self.log.warning("AI read_fields failed: %s", ex)
            return None
        if res is None:
            return None
        a = parse_date_token(res.values.get("early_ship_date", ""))
        b = parse_date_token(res.values.get("late_ship_date", ""))
        if a is None or b is None:
            return None
        return DateWindow(min(a, b), max(a, b))
