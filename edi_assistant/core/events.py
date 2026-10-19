"""Worker -> GUI events."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import RunResult


@dataclass(slots=True)
class Event:
    ts: float = field(default_factory=time.time)


@dataclass(slots=True)
class RunStarted(Event):
    run_id: str = ""
    total_steps: int = 0


@dataclass(slots=True)
class StepStarted(Event):
    step_id: str = ""
    title_vi: str = ""
    shipment_index: int = 0
    po_line_id: str = ""
    index: int = 0
    total: int = 0


@dataclass(slots=True)
class StepFinished(Event):
    step_id: str = ""
    status: str = "ok"
    detail: str = ""
    duration_s: float = 0.0


@dataclass(slots=True)
class Progress(Event):
    percent: int = 0
    message_vi: str = ""


@dataclass(slots=True)
class LogEvent(Event):
    level: str = "INFO"
    message: str = ""


@dataclass(slots=True)
class InputField:
    key: str
    label_vi: str
    default: str = ""
    placeholder: str = ""


@dataclass(slots=True)
class NeedsUser(Event):
    request_id: str = ""
    kind: str = ""
    message_vi: str = ""
    step_id: str = ""
    screenshot_path: str = ""
    ai_explanation_vi: str = ""
    options: list[str] = field(default_factory=lambda: ["continue", "skip", "abort"])
    input_fields: list[InputField] = field(default_factory=list)


@dataclass(slots=True)
class UserResponse:
    request_id: str
    action: str
    values: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ShipmentCreated(Event):
    shipment_index: int = 0
    web_shipment_id: str = ""
    asn_shipment_id: str = ""


@dataclass(slots=True)
class BrowserState(Event):
    is_open: bool = False
    url: str = ""
    logged_in: bool | None = None


@dataclass(slots=True)
class CalibrationResult(Event):
    key: str = ""
    candidate: dict | None = None
    saved: bool = False


@dataclass(slots=True)
class RunFinished(Event):
    result: "RunResult | None" = None


EventSink = Callable[[Event], None]
