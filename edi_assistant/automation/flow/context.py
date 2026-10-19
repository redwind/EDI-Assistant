"""FlowContext: everything a step needs."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from edi_assistant.core.ai_interface import VisionAdvisor
from edi_assistant.core.config import AppConfig
from edi_assistant.core.errors import UserAbortError
from edi_assistant.core.events import Event, EventSink, InputField, LogEvent, NeedsUser, UserResponse
from edi_assistant.core.models import PlannedLine, RunPlan, ShipmentPlan
from edi_assistant.data.results import ResultsWriter

from ..actions import SafeActions
from ..dialogs import DialogPolicy
from ..healing import Healer
from ..pace import Pacer
from ..selectors import SelectorResolver, SelectorStore
from ..session import BrowserSession


@dataclass
class FlowContext:
    session: BrowserSession
    actions: SafeActions
    resolver: SelectorResolver
    dialogs: DialogPolicy
    healer: Healer
    config: AppConfig
    plan: RunPlan
    run_dir: Path
    sink: EventSink
    log: logging.Logger
    abort_event: threading.Event
    ask_user: Callable[[NeedsUser], UserResponse]
    results: ResultsWriter
    current_shipment: ShipmentPlan | None = None
    current_line: PlannedLine | None = None
    today: Callable[[], date] = date.today      # additive: injectable clock (tests)
    pacer: Pacer | None = None                  # additive: human-pace mode helper (also set on session/actions)
    login_bounces: int = 0                      # times a non-login step found itself back on the login page

    @property
    def page(self):
        return self.session.page

    def vars(self, line: PlannedLine | None = None) -> dict[str, str]:
        sh = self.current_shipment
        line = line or self.current_line or (sh.lines[0] if sh and sh.lines else None)
        v = {"site_no": sh.to_site_no if sh else "", "shipment_id": sh.web_shipment_id if sh else "",
             "vendor": self.config.site.vendor_profile_name, "po": "", "master_po": "", "line": "",
             "line2": "", "item_label": "", "model_no": "", "container": ""}
        if line is not None:
            pl = line.po_line
            v.update(po=pl.po_line_id, master_po=pl.master_po, line=str(pl.line), line2=f"{pl.line:02d}",
                     item_label=pl.item_label, model_no=pl.model_no, container=pl.container)
        return v

    def emit(self, ev: Event) -> None:
        try:
            self.sink(ev)
        except Exception:
            self.log.exception("event sink failed")

    def info(self, msg: str) -> None:
        self.log.info(msg)
        self.emit(LogEvent(level="INFO", message=msg))

    def warn(self, msg: str) -> None:
        self.log.warning(msg)
        self.emit(LogEvent(level="WARNING", message=msg))

    def debug(self, msg: str) -> None:
        self.log.debug(msg)

    def base(self, path: str) -> str:
        return urljoin(self.config.site.effective_base_url(), path)

    def ask(self, kind: str, message_vi: str, *, options: list[str] | None = None,
            input_fields: list[InputField] | None = None, step_id: str = "", screenshot_path: str = "",
            ai_explanation_vi: str = "") -> UserResponse:
        """Pause for the user; 'abort' raises UserAbortError."""
        ev = NeedsUser(request_id=uuid.uuid4().hex, kind=kind, message_vi=message_vi, step_id=step_id,
                       screenshot_path=screenshot_path, ai_explanation_vi=ai_explanation_vi,
                       options=options if options is not None else ["continue", "skip", "abort"],
                       input_fields=input_fields or [])
        resp = self.ask_user(ev)
        if resp.action == "abort":
            raise UserAbortError("aborted by user", message_vi="Aborted by user")
        return resp


def make_context(session: BrowserSession, config: AppConfig, plan: RunPlan, run_dir: Path, sink: EventSink,
                 ask_user: Callable[[NeedsUser], UserResponse], store: SelectorStore,
                 advisor: VisionAdvisor | None = None, abort_event: threading.Event | None = None,
                 log: logging.Logger | None = None) -> FlowContext:
    log = log or logging.getLogger("edi_assistant.flow")
    abort_event = abort_event or threading.Event()
    resolver = SelectorResolver(store, log)
    actions = SafeActions(session, resolver, abort_event, sink, log, config.flow)
    pacer = Pacer(config.pace, abort_event, wait=session.wait, history=session.shipment_starts,
                  log=lambda m: (log.info(m), sink(LogEvent(level="INFO", message=m))))
    session.pacer = pacer if config.pace.enabled else None
    session.block_reason = ""
    healer = Healer(advisor, store, resolver, config.ai.max_calls_per_run, config.ai.vision, sink, log)
    return FlowContext(session=session, actions=actions, resolver=resolver, dialogs=session.dialogs, healer=healer,
                       config=config, plan=plan, run_dir=run_dir, sink=sink, log=log, abort_event=abort_event,
                       ask_user=ask_user, results=ResultsWriter(plan.run_id), pacer=pacer)
