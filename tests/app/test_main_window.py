import pytest

pytest.importorskip("edi_assistant.automation.commands")

from edi_assistant.app.main_window import MainWindow  # noqa: E402
from edi_assistant.app.worker_bridge import WorkerBridge  # noqa: E402
from edi_assistant.automation.commands import RunPlanCommand  # noqa: E402
from edi_assistant.core.config import AppConfig  # noqa: E402
from edi_assistant.core.events import NeedsUser, RunFinished  # noqa: E402
from edi_assistant.core.models import FactoryAddress, RunResult  # noqa: E402
from edi_assistant.data import FactoryStore, TemplateStore  # noqa: E402


@pytest.fixture
def win(qtbot, fake_worker):
    FactoryStore().upsert(FactoryAddress(id="", name="SUMEC TEXTILE COMPANY LIMITED", address1="68 Yunlongshan Road"))
    w = MainWindow(AppConfig(), fake_worker, WorkerBridge(), open_mapping_on_load=False)
    qtbot.addWidget(w)
    return w


def test_load_start_and_learn(win, fake_worker, sample_xlsx):
    win.load_excel(sample_xlsx)
    assert win.det is not None and win.rx is not None and len(win.rx.lines) == 2
    assert win.plan_table.rowCount() == 2
    assert win.factory_combo.currentText().startswith("SUMEC")  # auto-suggested from the footer
    assert not win.btn_start.isEnabled()  # new layout: mapping must be confirmed first
    win.mapping_confirmed = True
    win.template_name = "sumec"
    win._rebuild_plan()
    assert win.btn_start.isEnabled()
    win.start_run()
    cmd = fake_worker.commands[-1]
    assert isinstance(cmd, RunPlanCommand)
    assert [pl.po_line.po_line_id for pl in cmd.plan.shipments[0].lines] == ["580367401", "580367301"]
    assert TemplateStore().find(win.det).kind == "exact"
    # second load of the same file is recognised and needs no confirmation
    win.load_excel(sample_xlsx)
    assert win.mapping_confirmed and "sumec" in win.template_status.text()


def test_start_requires_factory(win, fake_worker, sample_xlsx, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    win.load_excel(sample_xlsx)
    win.mapping_confirmed = True
    win.factory_combo.setCurrentIndex(0)
    win.start_run()
    assert not fake_worker.commands


def test_needs_user_roundtrip(win, fake_worker, qtbot):
    win.bridge.sink(NeedsUser(request_id="rq1", kind="step_failed", message_vi="Lỗi"))
    qtbot.waitUntil(lambda: "rq1" in win._pause_dialogs, timeout=3000)
    win._pause_dialogs["rq1"].buttons["skip"].click()
    qtbot.waitUntil(lambda: bool(fake_worker.responses), timeout=3000)
    r = fake_worker.responses[0]
    assert (r.request_id, r.action) == ("rq1", "skip")


def test_run_finished_writes_back(win, fake_worker, sample_xlsx, qtbot):
    win.load_excel(sample_xlsx)
    win.mapping_confirmed = True
    win._rebuild_plan()
    win.start_run()
    plan = win.run_plan
    plan.shipments[0].web_shipment_id = "12345"
    res = RunResult(run_id=plan.run_id, status="done", shipments=plan.shipments, results_csv="",
                    started_at="", finished_at="")
    win.bridge.sink(RunFinished(result=res))
    out = sample_xlsx.with_name(f"{sample_xlsx.stem}_ASN.xlsx")
    qtbot.waitUntil(out.exists, timeout=3000)
    out.unlink()


def test_settings_applied(win, fake_worker, monkeypatch):
    from edi_assistant.app.dialogs import settings_dialog as sd
    orig = sd.SettingsDialog.exec

    def fake_exec(self):
        self.dry_run.setChecked(True)
        return 1

    monkeypatch.setattr(sd.SettingsDialog, "exec", fake_exec)
    win.open_settings()
    assert win.cfg.flow.dry_run and win.cb_dry.isChecked()
    assert fake_worker.configs and fake_worker.advisors == [None]
    monkeypatch.setattr(sd.SettingsDialog, "exec", orig)
