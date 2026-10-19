"""NeedsUser dialog: Continue / Skip / Abort, optional inputs, screenshot and AI explanation."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from edi_assistant.core.events import NeedsUser, UserResponse

from ..strings import S

BUTTON_TEXT = {"continue": S.BTN_CONTINUE, "skip": S.BTN_SKIP, "abort": S.BTN_ABORT}
CONTINUE_TEXT = {"finished_review": S.BTN_REVIEWED, "dry_run_stop": S.BTN_REVIEWED}


class _ClickableLabel(QLabel):
    def __init__(self, path: str):
        super().__init__()
        self._path = path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(S.PAUSE_OPEN_SCREENSHOT)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))


class PauseDialog(QDialog):
    def __init__(self, ev: NeedsUser, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(S.PAUSE_TITLE.get(ev.kind, S.PAUSE_TITLE_DEFAULT))
        self.setMinimumWidth(520)
        self._ev = ev
        self._response: UserResponse | None = None
        self._allow_close = False
        self._edits: dict[str, QLineEdit] = {}

        lay = QVBoxLayout(self)
        msg = QLabel(ev.message_vi)
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(msg)

        self.ai_label: QLabel | None = None
        if ev.ai_explanation_vi:
            self.ai_toggle = QToolButton()
            self.ai_toggle.setText(S.PAUSE_AI_EXPLANATION)
            self.ai_toggle.setCheckable(True)
            self.ai_toggle.setChecked(True)
            self.ai_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.ai_toggle.setArrowType(Qt.ArrowType.DownArrow)
            self.ai_label = QLabel(ev.ai_explanation_vi)
            self.ai_label.setWordWrap(True)
            self.ai_label.setStyleSheet("background:#eef3fd;padding:6px;border-radius:4px")
            self.ai_toggle.toggled.connect(self._toggle_ai)
            lay.addWidget(self.ai_toggle)
            lay.addWidget(self.ai_label)

        if ev.screenshot_path and Path(ev.screenshot_path).is_file():
            pm = QPixmap(ev.screenshot_path)
            if not pm.isNull():
                thumb = _ClickableLabel(ev.screenshot_path)
                thumb.setPixmap(pm.scaledToWidth(480, Qt.TransformationMode.SmoothTransformation))
                lay.addWidget(thumb)

        if ev.input_fields:
            form = QFormLayout()
            for f in ev.input_fields:
                e = QLineEdit(f.default)
                e.setPlaceholderText(f.placeholder)
                self._edits[f.key] = e
                form.addRow(f.label_vi, e)
            lay.addLayout(form)

        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons: dict[str, QPushButton] = {}
        for opt in ev.options:
            text = CONTINUE_TEXT.get(ev.kind, BUTTON_TEXT[opt]) if opt == "continue" else BUTTON_TEXT.get(opt, opt)
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, o=opt: self._choose(o))
            self.buttons[opt] = b
            row.addWidget(b)
        lay.addLayout(row)

    def _toggle_ai(self, on: bool) -> None:
        assert self.ai_label is not None
        self.ai_label.setVisible(on)
        self.ai_toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def values(self) -> dict[str, str]:
        return {k: e.text().strip() for k, e in self._edits.items()}

    def _choose(self, action: str) -> None:
        # inputs only matter when continuing
        vals = self.values() if action == "continue" else {}
        self._response = UserResponse(request_id=self._ev.request_id, action=action, values=vals)
        self._allow_close = True
        self.accept()

    def response(self) -> UserResponse | None:
        return self._response

    def reject(self) -> None:  # Esc / window X must not silently answer the worker
        if self._allow_close:
            super().reject()

    def force_close(self) -> None:
        self._allow_close = True
        super().reject()
