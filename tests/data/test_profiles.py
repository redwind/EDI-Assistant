from edi_assistant.data import detect_header, load_grid, suggest_mapping
from edi_assistant.data.profiles import (default_weight_mode, detect_profile, forced_grouping, profile_label)
from edi_assistant.core.config import FlowConfig


def test_packing_list(sample_path):
    det = detect_header(load_grid(sample_path))
    assert detect_profile(det) == ("packing_list", 1.0)
    m, _ = suggest_mapping(det)
    assert m.profile == "packing_list"


def test_tracker(tracker_path):
    det = detect_header(load_grid(tracker_path))
    assert detect_profile(det) == ("po_tracker", 1.0)
    m, _ = suggest_mapping(det, "packing_list")      # explicit override wins
    assert m.profile == "packing_list" and not m.is_complete()


def test_helpers():
    cfg = FlowConfig()
    assert default_weight_mode("po_tracker", cfg) == "per_carton_as_is"
    assert default_weight_mode("packing_list", cfg) == "total_gw"
    assert forced_grouping("po_tracker", "per_file") == "per_master_po"
    assert forced_grouping("packing_list", "per_file") == "per_file"
    assert profile_label("po_tracker") == "PO tracker" and profile_label("packing_list") == "Packing list"
