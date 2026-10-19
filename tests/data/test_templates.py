import json

from edi_assistant.data import TemplateStore, detect_header, load_grid, suggest_mapping
from edi_assistant.data.mapping import apply_template_to_detection
from edi_assistant.data.templates import compute_fingerprint


def test_learn_find_similar(sample_path, tmp_path):
    det = detect_header(load_grid(sample_path))
    mapping, _ = suggest_mapping(det)
    store = TemplateStore(tmp_path / "tpl")
    assert store.find(det) is None
    t = store.learn(det, mapping, "SUMEC packing list", "fid", "page 1")
    m = store.find(det)
    assert m.kind == "exact" and m.similarity == 1.0 and m.template.name == "SUMEC packing list"
    assert store.learn(det, mapping, "", "", "page 1").use_count == 2

    data = json.loads((tmp_path / "tpl" / f"{t.fingerprint}.json").read_text(encoding="utf-8"))
    assert set(data) == {"version", "fingerprint", "name", "created_at", "updated_at", "sheet_name",
                         "header_rows", "header_tokens", "columns", "factory_id", "use_count", "profile"}
    assert data["columns"]["po"] == {"letter": "A", "header": "PO"}
    assert data["columns"]["line"] is None
    assert "包装 packages" in data["header_tokens"]
    assert store.get(t.fingerprint).to_mapping().columns["packages"].letter == "C"

    # rename one header slightly -> similar
    for c in det.columns:
        if c.letter == "H":
            c.normalized = "尺码 dimension"
    assert compute_fingerprint(det)[0] != t.fingerprint
    m2 = store.find(det)
    assert m2.kind == "similar" and m2.similarity >= 0.75
    am = apply_template_to_detection(m2.template, det)
    assert am.columns["size"].letter == "H" and am.columns["packages"].letter == "C"
    store.delete(t.fingerprint)
    assert store.list() == []


def test_profile_roundtrip(tracker_path, tmp_path):
    det = detect_header(load_grid(tracker_path))
    mapping, _ = suggest_mapping(det)
    assert mapping.profile == "po_tracker"
    store = TemplateStore(tmp_path / "tpl")
    t = store.learn(det, mapping, "tracker", "fid", "Vendor ")
    assert t.profile == "po_tracker"
    m = store.get(t.fingerprint).to_mapping()
    assert m.profile == "po_tracker" and m.columns["pack"].letter == "Q"
    assert apply_template_to_detection(store.get(t.fingerprint), det).profile == "po_tracker"
    old = store.directory / f"{t.fingerprint}.json"
    d = json.loads(old.read_text(encoding="utf-8"))
    d.pop("profile")
    old.write_text(json.dumps(d), encoding="utf-8")
    assert store.get(t.fingerprint).profile == "packing_list"
