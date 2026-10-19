"""WorkerBridge: converts worker-thread callbacks into Qt signals (queued to the GUI thread)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from edi_assistant.core import events as ev


class WorkerBridge(QObject):
    event_received = Signal(object)
    run_started = Signal(object)
    step_started = Signal(object)
    step_finished = Signal(object)
    progress = Signal(object)
    log = Signal(object)
    needs_user = Signal(object)
    shipment_created = Signal(object)
    browser_state = Signal(object)
    calibration = Signal(object)
    run_finished = Signal(object)

    _TYPED = {
        ev.RunStarted: "run_started", ev.StepStarted: "step_started", ev.StepFinished: "step_finished",
        ev.Progress: "progress", ev.LogEvent: "log", ev.NeedsUser: "needs_user",
        ev.ShipmentCreated: "shipment_created", ev.BrowserState: "browser_state",
        ev.CalibrationResult: "calibration", ev.RunFinished: "run_finished",
    }

    def sink(self, event: ev.Event) -> None:
        """Called from the worker thread; the bridge lives in the GUI thread so delivery is queued."""
        self.event_received.emit(event)
        name = self._TYPED.get(type(event))
        if name:
            getattr(self, name).emit(event)
