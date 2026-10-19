"""Input profile detection (po_tracker vs packing_list)."""
from __future__ import annotations

from .header_detect import HeaderDetection
from .synonyms import field_scores

TRACKER_SIGNATURE = ("pack", "gw_per_carton", "start_ship", "end_ship", "asn")


def detect_profile(det: HeaderDetection, scores: dict[str, float] | None = None) -> tuple[str, float]:
    """scores = per-field best scores (computed from the raw header scores when None)."""
    per_col = {c.col: field_scores(c.joined) for c in det.columns}
    if scores is None:
        scores = {}
        for sc in per_col.values():
            for k, v in sc.items():
                scores[k] = max(scores.get(k, 0.0), v)
    hits = sum(1 for k in TRACKER_SIGNATURE if scores.get(k, 0.0) >= 0.85)
    if any(c.normalized.startswith("master po") and per_col[c.col].get("po", 0.0) >= 0.85 for c in det.columns):
        hits += 1
    return ("po_tracker", hits / 6) if hits >= 3 else ("packing_list", 1 - hits / 6)


def profile_label(profile: str) -> str:
    return "PO tracker" if profile == "po_tracker" else "Packing list"


def default_weight_mode(profile: str, cfg_flow) -> str:
    return cfg_flow.tracker_weight_mode if profile == "po_tracker" else cfg_flow.weight_mode


def forced_grouping(profile: str, requested: str) -> str:
    return "per_master_po" if profile == "po_tracker" else requested
