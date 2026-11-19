import os
import re
import sys
from pathlib import Path

import pytest

from PySide6.QtWidgets import QSystemTrayIcon

from edi_assistant.app import autostart, resource, strings_en, strings_vi
from edi_assistant.app.browser_install import chromium_available, install_command
from edi_assistant.app.single_instance import SingleInstance
from edi_assistant.app.widgets.log_view import LogView
from edi_assistant.app.widgets.plan_table import PlanTable
from edi_assistant.app.widgets.steps_view import StepsView
from edi_assistant.core.events import LogEvent, Progress, StepFinished, StepStarted


def test_single_instance_second_launch_signals_first(qtbot):
    key = "EDIAssistant-test-" + str(id(qtbot))
    first, second = SingleInstance(key), SingleInstance(key)
    try:
        assert first.try_acquire() is True
        with qtbot.waitSignal(first.show_requested, timeout=3000):
            assert second.try_acquire() is False
    finally:
        first.release()


def test_autostart_noop_off_windows():
    if sys.platform == "win32":
        return
    autostart.set_start_with_windows(True)
    assert autostart.is_start_with_windows() is False


def test_resources_exist():
    for n in ("app.ico", "app.png", "notify.wav"):
        assert resource(n).is_file()


def test_no_vietnamese_literals_outside_strings():
    viet = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]")
    root = Path(strings_en.__file__).parent
    bad = [str(p.relative_to(root)) for p in root.rglob("*.py")
           if p.name not in ("strings_vi.py", "strings_en.py", "prompts.py") and viet.search(p.read_text(encoding="utf-8"))]
    assert bad == []


def test_notification_text_constant():
    from edi_assistant.app.strings import S, set_language
    assert strings_vi.NOTIFY_FILLED_DONE == "Đã nhập xong, vui lòng kiểm tra và tự bấm Submit"
    assert strings_en.NOTIFY_FILLED_DONE == "Entry finished - please review and click Submit yourself"
    assert S.NOTIFY_FILLED_DONE == strings_en.NOTIFY_FILLED_DONE   # English is the default UI language
    try:
        set_language("vi")
        assert S.NOTIFY_FILLED_DONE == strings_vi.NOTIFY_FILLED_DONE
    finally:
        set_language("en")


def test_install_command_dev():
    cmd = install_command()
    assert cmd[-2:] == ["install", "chromium"]
    assert chromium_available() is False  # empty temp data dir


def test_steps_view(qtbot):
    v = StepsView()
    qtbot.addWidget(v)
    v.on_step_started(StepStarted(step_id="S1", title_vi="Mở inbox", index=1, total=4))
    v.on_step_finished(StepFinished(step_id="S1", status="ok"))
    v.on_step_started(StepStarted(step_id="S2", title_vi="Điền", index=2, total=4))
    v.on_step_finished(StepFinished(step_id="S2", status="skipped", detail="bỏ qua"))
    v.on_step_started(StepStarted(step_id="S3", title_vi="Lưu", index=3, total=4))
    assert v.statuses() == ["✓", "↷", "●"]
    v.on_progress(Progress(percent=60, message_vi="đang chạy"))
    assert v.bar.value() == 60 and v.message.text() == "đang chạy"
    v.clear()
    assert v.list.count() == 0


def test_log_view_filter(qtbot):
    v = LogView()
    qtbot.addWidget(v)
    v.on_log(LogEvent(level="DEBUG", message="dbg"))
    v.on_log(LogEvent(level="ERROR", message="err"))
    assert "dbg" not in v.text.toPlainText() and "err" in v.text.toPlainText()
    v.level.setCurrentText("DEBUG")
    assert "dbg" in v.text.toPlainText()


def test_plan_table_error_state(qtbot):
    t = PlanTable()
    qtbot.addWidget(t)
    rows = [{"shipment_index": 1, "po_line_id": "580367401"}, {"shipment_index": 1, "po_line_id": "580367301"}]
    t.set_rows(rows, ["", "error"])
    assert t.rowCount() == 2 and t.has_errors()
    t.set_rows(rows, ["warning", ""])
    assert not t.has_errors()


def test_aumid_guarded(monkeypatch):
    import sys
    import types
    from edi_assistant.app import main as m
    calls = []
    fake = types.SimpleNamespace(windll=types.SimpleNamespace(shell32=types.SimpleNamespace(
        SetCurrentProcessExplicitAppUserModelID=lambda i: calls.append(i))))
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert m.set_app_user_model_id() is False and calls == []
    monkeypatch.setattr(sys, "platform", "win32")
    assert m.set_app_user_model_id() is True and calls == ["ShyftGlobal.EDIAssistant"]
    monkeypatch.setitem(sys.modules, "ctypes", types.SimpleNamespace())   # no windll -> swallowed
    assert m.set_app_user_model_id() is False


def test_autostart_command_quotes_exe_path_with_space(monkeypatch):
    exe = r"C:\Users\x\Programs\EDI Assistant\EDI Assistant.exe"
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart._command() == f'"{exe}" --minimized'
    assert autostart.VALUE_NAME == "EDIAssistant"   # registry value name stays space-free



_RUNNING_APP = r"""
import sys
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtNetwork import QLocalServer
key, version = sys.argv[1], sys.argv[2]
app = QCoreApplication([])
if version == "legacy":            # protocol of builds <= 0.1.1: reads the message, never answers
    QLocalServer.removeServer(key)
    srv = QLocalServer()
    srv.listen(key)
    def on_conn():
        while srv.hasPendingConnections():
            c = srv.nextPendingConnection()
            c.waitForReadyRead(200)
            print("GOT", bytes(c.readAll()).decode(), flush=True)
            c.disconnectFromServer()
    srv.newConnection.connect(on_conn)
else:
    from edi_assistant.app.single_instance import SingleInstance
    g = SingleInstance(key, version=version)
    assert g.try_acquire()
    g.show_requested.connect(lambda: print("SHOW", flush=True))
    g.quit_requested.connect(lambda: (print("QUIT", flush=True), g.release(), app.quit()))
print("READY", flush=True)
QTimer.singleShot(20000, app.quit)
app.exec()
"""


@pytest.fixture
def running_app(tmp_path):
    procs = []

    def start(key, version):
        import subprocess
        script = tmp_path / "running_app.py"
        script.write_text(_RUNNING_APP)
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   PYTHONPATH=str(Path(__file__).resolve().parents[2]))
        pr = subprocess.Popen([sys.executable, str(script), key, version], stdout=subprocess.PIPE, text=True, env=env)
        procs.append(pr)
        assert pr.stdout.readline().strip() == "READY"
        return pr

    yield start
    for pr in procs:
        pr.kill()
        pr.wait()


def _key(tag):
    return f"EDIAssistant-test-{tag}-{os.getpid()}"


def test_single_instance_same_version_shows(running_app):
    key = _key("same")
    pr = running_app(key, "0.1.2")
    new = SingleInstance(key, version="0.1.2")
    assert new.try_acquire() is False and new.running_version is None
    assert pr.stdout.readline().strip() == "SHOW"


def test_single_instance_other_version_reported_and_replaced(running_app):
    key = _key("other")
    pr = running_app(key, "0.1.1")
    new = SingleInstance(key, version="0.1.2")
    try:
        assert new.try_acquire() is False and new.running_version == "0.1.1"
        assert new.replace_running(timeout_s=10) is True
        assert pr.stdout.readline().strip() == "QUIT"     # did not raise its window before quitting
        assert new.running_version is None
    finally:
        new.release()


def test_single_instance_old_build_without_version_reply(running_app):
    key = _key("legacy")
    pr = running_app(key, "legacy")
    new = SingleInstance(key, version="0.1.2")
    assert new.try_acquire() is False and new.running_version == "?"
    assert pr.stdout.readline().strip() == "GOT SHOW 0.1.2"
