"""Log tail with a level filter."""
from __future__ import annotations

import time

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ..strings import S

LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class LogView(QWidget):
    MAX_RECORDS = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.level = QComboBox()
        self.level.addItems(list(LEVELS))
        self.level.setCurrentText("INFO")
        self.level.currentTextChanged.connect(self._render)
        top = QHBoxLayout()
        top.addWidget(QLabel(S.LOG_LEVEL))
        top.addWidget(self.level)
        top.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.text, 1)
        self._records: list[tuple[int, str]] = []

    @staticmethod
    def _fmt(ts: float, level: str, msg: str) -> str:
        return f"{time.strftime('%H:%M:%S', time.localtime(ts))} {level:<7} {msg}"

    def append(self, level: str, msg: str, ts: float | None = None) -> None:
        line = self._fmt(ts or time.time(), level, msg)
        self._records.append((LEVELS.get(level, 20), line))
        if len(self._records) > self.MAX_RECORDS:
            del self._records[: len(self._records) - self.MAX_RECORDS]
        if LEVELS.get(level, 20) >= LEVELS[self.level.currentText()]:
            self.text.appendPlainText(line)

    def on_log(self, ev) -> None:
        self.append(ev.level, ev.message, ev.ts)

    def _render(self) -> None:
        mn = LEVELS[self.level.currentText()]
        self.text.setPlainText("\n".join(line for lv, line in self._records if lv >= mn))
