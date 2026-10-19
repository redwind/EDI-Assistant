import re
import sys
from pathlib import Path

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
