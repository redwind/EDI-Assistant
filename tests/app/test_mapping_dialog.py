import pytest

from edi_assistant.app.dialogs.mapping_dialog import MappingDialog
from edi_assistant.core.models import FIELD_KEYS
from edi_assistant.data import detect_header, load_grid, suggest_mapping


@pytest.fixture
def det_map(sample_xlsx):
    grid = load_grid(sample_xlsx)
    det = detect_header(grid)
    mapping, scores = suggest_mapping(det)
    preview = [grid.row_values(r) for r in range(det.data_start_row, det.data_start_row + 5)]
    return det, mapping, scores, preview


def test_prefills_from_suggestion(qtbot, det_map):
    det, mapping, scores, preview = det_map
    dlg = MappingDialog(det, mapping, scores, preview, "tpl")
    qtbot.addWidget(dlg)
    for key in FIELD_KEYS:
        ref = mapping.columns[key]
        assert dlg._combos[key].currentData() == (ref.letter if ref else None)
    assert dlg.preview.columnCount() == len(det.columns)
    assert dlg.name_edit.text() == "tpl"


def test_change_column_and_result(qtbot, det_map):
    det, mapping, scores, preview = det_map
    dlg = MappingDialog(det, mapping, scores, preview)
    qtbot.addWidget(dlg)
    combo = dlg._combos["size"]
    combo.setCurrentIndex(0)  # (không dùng)
    dlg.name_edit.setText("  my layout ")
    dlg._on_accept()
    m, name = dlg.result()
    assert m.columns["size"] is None
    assert m.columns["po"].letter == mapping.columns["po"].letter
    assert name == "my layout"
    assert dlg.remember_layout()


def test_missing_required_blocks_accept(qtbot, det_map):
    det, mapping, scores, preview = det_map
    dlg = MappingDialog(det, mapping, scores, preview)
    qtbot.addWidget(dlg)
    dlg._combos["po"].setCurrentIndex(0)
    dlg._on_accept()
    assert dlg.error_label.text()
    assert not dlg.result()[0].is_complete()
