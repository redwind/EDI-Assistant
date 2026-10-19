from edi_assistant.app.dialogs.pause_dialog import PauseDialog
from edi_assistant.core.events import InputField, NeedsUser


def test_default_options_buttons(qtbot):
    dlg = PauseDialog(NeedsUser(request_id="r1", kind="step_failed", message_vi="Lỗi"))
    qtbot.addWidget(dlg)
    assert set(dlg.buttons) == {"continue", "skip", "abort"}
    assert dlg.buttons["skip"].text() == "Skip step"
    dlg.buttons["skip"].click()
    r = dlg.response()
    assert (r.request_id, r.action, r.values) == ("r1", "skip", {})


def test_options_subset_and_esc_ignored(qtbot):
    dlg = PauseDialog(NeedsUser(request_id="r2", kind="finished_review", options=["continue"], message_vi="x"))
    qtbot.addWidget(dlg)
    assert list(dlg.buttons) == ["continue"]
    dlg.reject()
    assert dlg.response() is None
    dlg.buttons["continue"].click()
    assert dlg.response().action == "continue"


def test_input_fields_values(qtbot):
    ev = NeedsUser(request_id="r3", kind="dates_needed", message_vi="Nhập ngày",
                   input_fields=[InputField("early_ship_date", "Ngày sớm", default="03/01/2026"),
                                 InputField("late_ship_date", "Ngày muộn")])
    dlg = PauseDialog(ev)
    qtbot.addWidget(dlg)
    dlg._edits["late_ship_date"].setText(" 03/13/2026 ")
    dlg.buttons["continue"].click()
    assert dlg.response().values == {"early_ship_date": "03/01/2026", "late_ship_date": "03/13/2026"}


def test_abort_discards_values_and_ai_explanation(qtbot, tmp_path):
    from PySide6.QtGui import QImage
    shot = tmp_path / "s.png"
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(0)
    img.save(str(shot))
    ev = NeedsUser(request_id="r4", message_vi="m", ai_explanation_vi="AI nói", screenshot_path=str(shot),
                   input_fields=[InputField("k", "K", default="v")])
    dlg = PauseDialog(ev)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.ai_label.isVisible()
    dlg.ai_toggle.setChecked(False)
    assert not dlg.ai_label.isVisible()
    dlg.buttons["abort"].click()
    assert dlg.response().action == "abort" and dlg.response().values == {}
