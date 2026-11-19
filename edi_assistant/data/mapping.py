"""Column mapping: suggestion, template re-application, validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from edi_assistant.core.errors import MappingIncompleteError
from edi_assistant.core.models import FIELD_KEYS, REQUIRED_BY_PROFILE
from edi_assistant.core.textnorm import normalize_header

from .header_detect import HeaderDetection
from .synonyms import field_scores

if TYPE_CHECKING:
    from .templates import Template


@dataclass(slots=True)
class ColumnRef:
    letter: str
    header: str


@dataclass(slots=True)
class ColumnMapping:
    columns: dict[str, ColumnRef | None] = field(default_factory=lambda: {k: None for k in FIELD_KEYS})
    profile: str = "packing_list"

    def __post_init__(self) -> None:
        for k in FIELD_KEYS:
            self.columns.setdefault(k, None)

    def required(self) -> tuple[str, ...]:
        return REQUIRED_BY_PROFILE.get(self.profile, REQUIRED_BY_PROFILE["packing_list"])

    def missing_required(self) -> list[str]:
        miss = [k for k in self.required() if self.columns.get(k) is None]
        if "quantity" in miss and self.profile == "po_tracker" and self.columns.get("edi_units") is not None:
            miss.remove("quantity")   # tracker extracted from the PO PDF: EDI Units stands in for Order Units
        return miss

    def is_complete(self) -> bool:
        return not self.missing_required()


def suggest_mapping(det: HeaderDetection, profile: str | None = None) -> tuple[ColumnMapping, dict[str, float]]:
    cands = []
    for c in det.columns:
        for f, sc in field_scores(c.joined).items():
            if sc >= 0.7:
                cands.append((-sc, c.col, f, c))
    cands.sort(key=lambda t: (t[0], t[1]))
    mapping = ColumnMapping()
    scores = {k: 0.0 for k in FIELD_KEYS}
    used_cols: set[int] = set()
    for neg, _, f, c in cands:
        if mapping.columns[f] is not None or c.col in used_cols:
            continue
        mapping.columns[f] = ColumnRef(c.letter, c.joined)
        scores[f] = -neg
        used_cols.add(c.col)
    from .profiles import detect_profile

    mapping.profile = profile or detect_profile(det, scores)[0]
    return mapping, scores


def apply_template_to_detection(tmpl: "Template", det: HeaderDetection) -> ColumnMapping:
    m = ColumnMapping(profile=getattr(tmpl, "profile", "packing_list") or "packing_list")
    by_norm = {}
    for c in det.columns:
        by_norm.setdefault(c.normalized, c)
    by_letter = {c.letter: c for c in det.columns}
    for f in FIELD_KEYS:
        ref = tmpl.columns.get(f)
        if ref is None:
            continue
        col = by_norm.get(normalize_header(ref.header)) or by_letter.get(ref.letter)
        if col is not None:
            m.columns[f] = ColumnRef(col.letter, col.joined)
    return m


def validate_mapping(m: ColumnMapping) -> None:
    missing = m.missing_required()
    if missing:
        raise MappingIncompleteError(f"Mapping incomplete, missing: {missing}",
                                     message_vi="Required columns are not mapped: " + ", ".join(missing),
                                     missing=missing)
