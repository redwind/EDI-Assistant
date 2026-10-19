import pytest

pytest.importorskip("edi_assistant.automation.commands")

from edi_assistant.app.dialogs.calibrate_dialog import CalibrateDialog, vars_from_inputs  # noqa: E402
from edi_assistant.automation.commands import Highlight, Pick  # noqa: E402
from edi_assistant.automation.selectors import SelectorStore  # noqa: E402
from edi_assistant.core import paths  # noqa: E402


def test_vars_from_inputs():
    v = vars_from_inputs("580367401", "S1", "")
    assert v["master_po"] == "5803674" and v["line"] == "1" and v["line2"] == "01"
    assert v["item_label"] == "PO5803674LN1" and v["site_no"] == "S1" and "row_key" not in v


def test_dialog_lists_keys_and_submits(qtbot, fake_worker):
    store = SelectorStore(paths.bundled_selectors_path(), paths.learned_selectors_path())
    store.load()
    dlg = CalibrateDialog(store, fake_worker)
    qtbot.addWidget(dlg)
    assert dlg.table.rowCount() == len(store.keys())
    # unverified keys are listed first
    assert dlg.table.item(0, 2).text() == "✗"
    dlg.table.selectRow(0)
    key = dlg.current_key()
    dlg.po.setText("580367401")
    dlg.highlight()
    dlg.pick()
    assert isinstance(fake_worker.commands[0], Highlight) and fake_worker.commands[0].vars["po"] == "580367401"
    assert isinstance(fake_worker.commands[1], Pick) and fake_worker.commands[1].key == key
    assert "Waiting" in dlg.status.text()
