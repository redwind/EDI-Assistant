"""Native dialog policy: dismiss confirm() by default, accept only when armed."""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

from playwright.sync_api import Dialog, Page

from edi_assistant.core.events import Event, LogEvent

ALWAYS_DISMISS_RE = re.compile(r"submit|transmit|cancel (this|the) shipment|delete|remove", re.I)


class DialogPolicy:
    def __init__(self, log: logging.Logger, sink: Callable[[Event], None]):
        self.log = log
        self.sink = sink
        self._pattern: re.Pattern | None = None
        self._expires = 0.0
        self.history: list[tuple[str, str, bool]] = []

    def install(self, page: Page) -> None:
        page.on("dialog", self._handle)

    def expect_accept(self, pattern: str, timeout_s: float = 20) -> None:
        """Arm: the next confirm whose message matches pattern (re.I) is accepted."""
        self._pattern = re.compile(pattern, re.I)
        self._expires = time.monotonic() + timeout_s

    def disarm(self) -> None:
        self._pattern = None

    def pop_last(self) -> tuple[str, str, bool] | None:
        return self.history.pop() if self.history else None

    def _note(self, level: str, msg: str) -> None:
        getattr(self.log, level.lower() if level != "WARNING" else "warning")(msg)
        try:
            self.sink(LogEvent(level=level, message=msg))
        except Exception:  # sink must never break dialog handling
            pass

    def _record(self, d: Dialog, accepted: bool) -> None:
        self.history.append((d.type, d.message, accepted))
        del self.history[:-50]

    def _handle(self, dialog: Dialog) -> None:
        typ, msg = dialog.type, dialog.message
        try:
            if typ in ("alert", "beforeunload"):
                self._note("INFO", f"dialog {typ}: {msg}")
                self._record(dialog, True)
                dialog.accept()
            elif typ == "confirm":
                armed = self._pattern is not None and time.monotonic() <= self._expires
                if ALWAYS_DISMISS_RE.search(msg):
                    self._note("WARNING", f"confirm dismissed (forbidden text): {msg}")
                    self._record(dialog, False)
                    dialog.dismiss()
                elif armed and self._pattern.search(msg):
                    self._pattern = None
                    self._note("INFO", f"confirm accepted: {msg}")
                    self._record(dialog, True)
                    dialog.accept()
                else:
                    self._note("WARNING", f"unexpected confirm dismissed: {msg}")
                    self._record(dialog, False)
                    dialog.dismiss()
            else:  # prompt
                self._note("WARNING", f"prompt dismissed: {msg}")
                self._record(dialog, False)
                dialog.dismiss()
        except Exception as ex:  # dialog may already be handled/closed
            self.log.debug("dialog handling error: %s", ex)
