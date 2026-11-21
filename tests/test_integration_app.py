"""Integration: REAL GUI stack end to end, headless.

MainWindow (offscreen Qt) -> WorkerBridge -> AutomationWorker (own thread, headless chromium) -> MockServer,
with the sample Excel going through the real data layer (auto mapping + MappingDialog confirm).
Any NeedsUser pause is answered through the real PauseDialog the window opens.
"""
from __future__ import annotations

import csv
import os
import shutil
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytestmark = pytest.mark.e2e

SAMPLE = Path(__file__).resolve().parent.parent / "docs" / "5803674 & 5803673 PKL.xlsx"
POS = ("580367401", "580367301")


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("EDI_ASSISTANT_DATA_DIR", str(d))
    return d


@pytest.fixture
def mock_server():
    from edi_assistant.mock_edi import MockOptions, MockServer
    srv = MockServer(MockOptions(port=0, require_login=False))   # default seed contains both sample POs
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def stack(qtbot, tmp_path, mock_server, monkeypatch):
    """Real worker + bridge + window wired exactly like app/main.py (minus tray/single-instance)."""
    from edi_assistant.app.dialogs.mapping_dialog import MappingDialog
    from edi_assistant.app.main_window import MainWindow
    from edi_assistant.app.worker_bridge import WorkerBridge
    from edi_assistant.automation.worker import AutomationWorker
    from edi_assistant.core.config import AppConfig
    from edi_assistant.core.models import FactoryAddress
    from edi_assistant.data import FactoryStore

    if not SAMPLE.exists():
        pytest.skip("sample Excel missing")
    cfg = AppConfig()
    cfg.site.use_mock, cfg.site.mock_url = True, mock_server.url
    cfg.pace.enabled = False   # keep the suite fast; pacing has its own tests
    cfg.browser.channel, cfg.browser.headless, cfg.browser.default_timeout_ms = (
        os.environ.get("EDI_TEST_BROWSER_CHANNEL", "chromium"), True, 8000)

    FactoryStore().upsert(FactoryAddress(id="", name="SUMEC TEXTILE COMPANY LIMITED", address1="1 TEST ROAD",
                                         address2="BLDG 2", city="NANJING", state="JIANGSU", zip="210000",
                                         country="CHINA"))
    # the user confirms the auto-suggested mapping in the dialog (real dialog object, accepted without a click)
    monkeypatch.setattr(MappingDialog, "exec", lambda self: 1)

    bridge = WorkerBridge()
    worker = AutomationWorker(cfg, bridge.sink, None, profile_dir=tmp_path / "profile")
    worker.start()
    win = MainWindow(cfg, worker, bridge, open_mapping_on_load=False)
    qtbot.addWidget(win)
    try:
        yield cfg, worker, bridge, win
    finally:
        worker.stop(30)


def test_gui_to_mock_full_run(qtbot, stack, mock_server, tmp_path):
    from PySide6.QtCore import QTimer

    from edi_assistant.core.dates import compute_shipping_date, format_mdy, parse_date_token
    from edi_assistant.core.events import ShipmentCreated
    from edi_assistant.core.models import DateWindow

    cfg, worker, bridge, win = stack
    xlsx = tmp_path / SAMPLE.name
    shutil.copyfile(SAMPLE, xlsx)

    # --- Excel through the real data layer -------------------------------------------------------
    win.load_excel(xlsx)
    assert win.det is not None and win.mapping is not None and win.mapping.is_complete()
    assert [ln.po_line_id for ln in win.rx.lines] == list(POS)
    assert not win.mapping_confirmed and not win.btn_start.isEnabled()      # new layout: confirm first
    win.edit_mapping()                                                       # MappingDialog accepted
    assert win.mapping_confirmed and win.preview_plan is not None
    assert win.factory_combo.currentText().startswith("SUMEC")              # picked from the Excel footer
    assert win.rb_file.isChecked() and not win.cb_dry.isChecked()            # one shipment per file, real run
    assert win.can_start()

    # --- answer any pause through the real PauseDialog ---------------------------------------------
    asked: list[str] = []
    events: list = []
    bridge.event_received.connect(events.append)

    def auto_answer(ev):
        asked.append(ev.kind)
        action = "continue" if ev.kind in ("finished_review", "dry_run_stop") else "abort"

        def click():
            dlg = win._pause_dialogs.get(ev.request_id)
            if dlg is not None:
                dlg.buttons[action].click()
        QTimer.singleShot(0, click)
    bridge.needs_user.connect(auto_answer)

    # --- run ---------------------------------------------------------------------------------------
    with qtbot.waitSignal(bridge.run_finished, timeout=240_000) as blocker:
        win.start_run()
        # the Start button is disabled synchronously (no window to double-submit a run)
        assert worker.is_running and not win.btn_start.isEnabled()
    result = blocker.args[0].result
    assert asked == [], f"unexpected pauses: {asked}"
    assert result.status == "done", result.error
    assert worker.is_running is False

    # --- results ------------------------------------------------------------------------------------
    sh_out = result.shipments[0]
    assert len(result.shipments) == 1 and len(sh_out.lines) == 2
    assert sh_out.web_shipment_id.isdigit() and len(sh_out.web_shipment_id) >= 3
    assert any(isinstance(e, ShipmentCreated) and e.web_shipment_id == sh_out.web_shipment_id for e in events)
    assert Path(result.results_csv).is_file()
    with open(result.results_csv, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["po_line_id"] for r in rows] == list(POS)
    assert all(r["web_shipment_id"] == sh_out.web_shipment_id and r["status"] == "weight_done" for r in rows)
    assert all((r["qty_per_carton"], r["cartons_per_site"], r["weight_kg"]) == ("6", "85", "1020.00") for r in rows)

    # --- mock state matches the user's business rules -----------------------------------------------
    st = mock_server.state
    assert st.submit_called is False and st.submit_attempts == 0
    assert len(st.shipments) == 1
    sh = next(iter(st.shipments.values()))
    assert str(sh.shipment_id) == sh_out.web_shipment_id
    h = sh.header
    o = st.orders[POS[0]]
    expected_date = compute_shipping_date([DateWindow(parse_date_token(o.early), parse_date_token(o.late))],
                                          date.today()).shipping_date
    assert h["txtShippingDate"] == format_mdy(expected_date)                 # midpoint, clamped to today
    assert h["OptShippingType"] == "3" and h["OptTransMethod"] == "O" and h["OptSCACCode"] == "MAEU"
    assert h["txtFromName"] == "SUMEC TEXTILE COMPANY LIMITED" and h["txtFromCountry"] == "CN"
    assert set(sh.pos) == set(POS)
    for po in POS:
        assert sh.pos[po]["complete_partial"] == "Partial"
        assert sh.cartons[po]["saved"] is True
        assert (sh.cartons[po]["qty_per_carton"], sh.cartons[po]["cartons_per_site"]) == ("6", "85")
        assert (sh.weights[po]["weight"], sh.weights[po]["um"]) == ("1020.00", "KG")

    # --- GUI side effects: history row, Excel write-back copy, template learned -----------------------
    qtbot.waitUntil(lambda: win.history.rowCount() == 1, timeout=5000)
    assert win.history.item(0, 2).text() == "done" and sh_out.web_shipment_id in win.history.item(0, 4).text()
    out = xlsx.with_name(f"{xlsx.stem}_ASN.xlsx")
    qtbot.waitUntil(out.exists, timeout=5000)
    assert win.templates.find(win.det).kind == "exact"
    assert worker.is_browser_open                                            # browser left open for the user


TRACKER = Path(__file__).resolve().parent.parent / "docs" / "Copy of 6102 - Q4 Pet Beds Current - MDDP-PO tracker-1009 - 副本.xlsx"


def test_gui_to_mock_tracker_run(qtbot, stack, mock_server, tmp_path):
    import hashlib

    import openpyxl
    from PySide6.QtCore import QTimer

    from edi_assistant.core.events import ShipmentCreated

    if not TRACKER.exists():
        pytest.skip("tracker sample missing")
    cfg, worker, bridge, win = stack
    mock_server.state.seed_tracker()
    xlsx = tmp_path / TRACKER.name                       # never write next to the sample in docs/
    shutil.copyfile(TRACKER, xlsx)
    digest = hashlib.sha256(xlsx.read_bytes()).hexdigest()

    win.load_excel(xlsx)
    assert win.mapping.profile == "po_tracker" and win.mapping.is_complete()
    win.edit_mapping()
    assert win.mapping_confirmed and win.rb_master.isChecked() and not win.rb_file.isEnabled()
    for i in range(win.factory_combo.count()):
        if win.factory_combo.itemText(i).startswith("SUMEC"):
            win.factory_combo.setCurrentIndex(i)
    assert win.factory_combo.currentText().startswith("SUMEC") and win.can_start()

    asked: list[str] = []
    events: list = []
    bridge.event_received.connect(events.append)

    def auto_answer(ev):
        asked.append(ev.kind)
        action = "continue" if ev.kind in ("finished_review", "dry_run_stop") else "abort"

        def click():
            dlg = win._pause_dialogs.get(ev.request_id)
            if dlg is not None:
                dlg.buttons[action].click()
        QTimer.singleShot(0, click)
    bridge.needs_user.connect(auto_answer)

    with qtbot.waitSignal(bridge.run_finished, timeout=420_000) as blocker:
        win.start_run()
    result = blocker.args[0].result
    assert result.status == "done", result.error
    assert set(asked) <= {"finished_review"}
    ids = [s.web_shipment_id for s in result.shipments]
    assert len(ids) == 6 and len(set(ids)) == 6 and all(i.isdigit() for i in ids)
    assert len([e for e in events if isinstance(e, ShipmentCreated)]) == 6
    assert mock_server.state.submit_called is False

    outs = list(tmp_path.glob("*_ASN_*.xlsx"))
    assert len(outs) == 1
    ws = openpyxl.load_workbook(outs[0])["Vendor "]
    assert ws["F2"].value == 872295                                         # existing ASN untouched
    assert [ws.cell(row=r, column=6).value for r in range(3, 11)] == \
        [int(i) for i in (ids[0], ids[1], ids[1], ids[2], ids[3], ids[3], ids[4], ids[5])]
    assert hashlib.sha256(xlsx.read_bytes()).hexdigest() == digest          # original untouched
