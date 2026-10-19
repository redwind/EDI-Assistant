"""PO-tracker UI: profile combo, plan-table checkboxes, factory per run, write-back copy, settings."""
import hashlib
import shutil

import pytest
from PySide6.QtCore import Qt

pytest.importorskip("edi_assistant.automation.commands")

from edi_assistant.app.dialogs.mapping_dialog import MappingDialog  # noqa: E402
from edi_assistant.app.dialogs.settings_dialog import SettingsDialog  # noqa: E402
from edi_assistant.app.main_window import MainWindow  # noqa: E402
from edi_assistant.app.widgets.plan_table import PlanTable  # noqa: E402
from edi_assistant.app.worker_bridge import WorkerBridge  # noqa: E402
from edi_assistant.automation.commands import RunPlanCommand  # noqa: E402
from edi_assistant.core.config import AppConfig, load_config  # noqa: E402
from edi_assistant.core.events import ShipmentCreated  # noqa: E402
from edi_assistant.core.models import REQUIRED_BY_PROFILE, FactoryAddress  # noqa: E402
from edi_assistant.data import FactoryStore, detect_header, load_grid, suggest_mapping  # noqa: E402


@pytest.fixture
def win(qtbot, fake_worker):
    FactoryStore().upsert(FactoryAddress(id="", name="SUMEC TEXTILE COMPANY LIMITED", address1="68 Yunlongshan Road"))
    w = MainWindow(AppConfig(), fake_worker, WorkerBridge(), open_mapping_on_load=False)
    qtbot.addWidget(w)
    return w


@pytest.fixture
def local_tracker(tracker_xlsx, tmp_path):
    dst = tmp_path / "tracker.xlsx"
    shutil.copyfile(tracker_xlsx, dst)
    return dst


def _rows(master_a="A", master_b="B", sev_b=""):
    return [{"master_po": master_a, "shipment_index": 1, "po_line_id": "1", "selected": True},
            {"master_po": master_a, "shipment_index": 1, "po_line_id": "2", "selected": True},
            {"master_po": master_b, "shipment_index": 2, "po_line_id": "3", "selected": True}]


def test_plan_table_checkbox_toggles_whole_master(qtbot):
    t = PlanTable()
    qtbot.addWidget(t)
    t.set_rows(_rows(), ["", "", ""])
    assert t.columnCount() == 15 and t.selected_count() == 3
    with qtbot.waitSignal(t.selection_changed) as sig:
        t.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert sig.args == ["A", False]
    assert not t.is_checked(1) and t.is_checked(2)


def test_plan_table_errors_only_count_when_selected(qtbot):
    t = PlanTable()
    qtbot.addWidget(t)
    t.set_rows(_rows(), ["", "", "error"])
    assert t.has_errors()
    t.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not t.has_errors()
    rows = _rows()
    rows[0].update(selected=False, existing_asn="872295")
    t.set_rows(rows, ["", "", ""])
    assert "872295" in t.item(0, 13).text() and not t.is_checked(0)


def test_mapping_dialog_profile_switch(qtbot, tracker_xlsx, sample_xlsx):
    grid = load_grid(tracker_xlsx)
    det = detect_header(grid)
    mapping, scores = suggest_mapping(det)
    assert mapping.profile == "po_tracker"
    dlg = MappingDialog(det, mapping, scores, [])
    qtbot.addWidget(dlg)
    assert dlg.profile_combo.currentData() == "po_tracker"
    assert dlg.field_order()[: len(REQUIRED_BY_PROFILE["po_tracker"])] == list(REQUIRED_BY_PROFILE["po_tracker"])
    assert dlg.table.item(0, 0).text().endswith("*")
    dlg._on_accept()
    m, _ = dlg.result()
    assert m.profile == "po_tracker" and m.is_complete()
    dlg.profile_combo.setCurrentIndex(dlg.profile_combo.findData("packing_list"))
    assert dlg.field_order()[0] == "po" and dlg.result()[0].profile == "packing_list"
    dlg._on_accept()
    assert dlg.error_label.text()   # tracker file has no cartons / total weight columns for the packing-list profile


def test_load_tracker_defaults_and_start(win, fake_worker, local_tracker):
    win.load_excel(local_tracker)
    assert win.mapping.profile == "po_tracker" and "PO tracker" in win.template_status.text()
    assert win.plan_table.rowCount() == 9 and win.plan_table.selected_count() == 8
    assert not win.plan_table.is_checked(0) and "872295" in win.plan_table.item(0, 13).text()
    assert win.rb_master.isChecked() and not win.rb_master.isEnabled() and win.rb_master.toolTip()
    assert win.factory_hint.text().startswith("This file has no factory column")
    win.mapping_confirmed = True
    win._rebuild_plan()
    assert win.btn_start.isEnabled()
    win.factory_combo.setCurrentIndex(1)
    win.start_run()
    plan = fake_worker.commands[-1].plan
    assert isinstance(fake_worker.commands[-1], RunPlanCommand)
    assert plan.profile == "po_tracker" and len(plan.shipments) == 6
    assert sum(len(s.lines) for s in plan.shipments) == 8
    assert load_config().ui.last_factory_id == win.factory_combo.currentData()   # saved at Start


def test_untick_master_and_no_selection(win, fake_worker, local_tracker, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[-1]))
    win.load_excel(local_tracker)
    win.mapping_confirmed = True
    win.factory_combo.setCurrentIndex(1)
    masters = sorted({ln.master_po for ln in win.rx.lines})
    for m in masters[:-1]:
        win._on_selection_changed(m, False)
    assert win.plan_table.selected_count() == sum(1 for ln in win.rx.lines if ln.master_po == masters[-1])
    win._on_selection_changed(masters[-1], False)
    assert win.plan_table.selected_count() == 0 and not win.btn_start.isEnabled() and win.plan_table.rowCount() == 9
    win.start_run()
    assert not fake_worker.commands and shown
    win._on_selection_changed(masters[0], True)
    assert win.btn_start.isEnabled()


def test_shipment_created_writes_copy_not_original(win, fake_worker, local_tracker, qtbot):
    import openpyxl
    h = hashlib.sha256(local_tracker.read_bytes()).hexdigest()
    win.load_excel(local_tracker)
    win.mapping_confirmed = True
    win.factory_combo.setCurrentIndex(1)
    win.start_run()
    plan = win.run_plan
    win.bridge.sink(ShipmentCreated(shipment_index=1, web_shipment_id="900001"))
    out = win._writeback_path
    qtbot.waitUntil(lambda: out.exists(), timeout=3000)
    assert "_ASN_" in out.name and out != local_tracker
    ws = openpyxl.load_workbook(out).active
    first = plan.shipments[0].lines[0].po_line.source_row
    assert ws.cell(first, 6).value == 900001
    assert hashlib.sha256(local_tracker.read_bytes()).hexdigest() == h


def test_dry_run_never_writes_back(win, local_tracker, qtbot):
    win.load_excel(local_tracker)
    win.mapping_confirmed = True
    win.factory_combo.setCurrentIndex(1)
    win.cb_dry.setChecked(True)
    win.start_run()
    win.bridge.sink(ShipmentCreated(shipment_index=1, web_shipment_id="900001"))
    qtbot.wait(100)
    assert not win._writeback_path.exists()


def test_settings_tracker_options(qtbot):
    cfg = AppConfig()
    dlg = SettingsDialog(cfg)
    qtbot.addWidget(dlg)
    assert dlg.tracker_weight.currentData() == "per_carton_as_is" and not dlg.review_between.isChecked()
    dlg.tracker_weight.setCurrentIndex(dlg.tracker_weight.findData("total_gw"))
    dlg.review_between.setChecked(True)
    out = dlg.result_config()
    assert out.flow.tracker_weight_mode == "total_gw" and out.flow.review_between_shipments is True
