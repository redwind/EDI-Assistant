"""VisionAdvisor protocol + request/response dataclasses."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class LocatorRequest:
    key: str
    description: str
    page_url: str
    page_title: str
    aria_snapshot: str
    dom_excerpt: str
    screenshot_jpeg: bytes | None
    tried: list[str]


@dataclass(slots=True)
class LocatorProposal:
    candidates: list[dict]
    confidence: float
    notes: str = ""


@dataclass(slots=True)
class ExplainRequest:
    step_id: str
    step_title_vi: str
    error_text: str
    page_url: str
    aria_snapshot: str
    dom_excerpt: str
    screenshot_jpeg: bytes | None


@dataclass(slots=True)
class Explanation:
    explanation_vi: str
    likely_cause: str
    user_action_vi: str


@dataclass(slots=True)
class ReadFieldsRequest:
    fields: list[str]
    hint: str
    screenshot_jpeg: bytes


@dataclass(slots=True)
class ReadFieldsResult:
    values: dict[str, str]
    confidence: float


class VisionAdvisor(Protocol):
    name: str
    supports_vision: bool

    def propose_locator(self, req: LocatorRequest) -> LocatorProposal | None: ...
    def explain_error(self, req: ExplainRequest) -> Explanation | None: ...
    def read_fields(self, req: ReadFieldsRequest) -> ReadFieldsResult | None: ...
