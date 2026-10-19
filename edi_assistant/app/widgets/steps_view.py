"""Step list with status icons + progress bar + current message."""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QProgressBar, QVBoxLayout, QWidget

ICONS = {"running": "●", "ok": "✓", "failed": "✗", "skipped": "↷"}
COLORS = {"running": "#1a73e8", "ok": "#188038", "failed": "#d93025", "skipped": "#80868b"}


class StepsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.list = QListWidget()
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.bar)
        lay.addWidget(self.message)
        self._items: dict[str, QListWidgetItem] = {}
        self._titles: dict[str, str] = {}

    def clear(self) -> None:
        self.list.clear()
        self._items.clear()
        self._titles.clear()
        self.bar.setValue(0)
        self.message.setText("")

    def _set(self, step_id: str, status: str, suffix: str = "") -> None:
        item = self._items.get(step_id)
        if item is None:
            return
        item.setText(f"{ICONS[status]}  {self._titles[step_id]}{suffix}")
        item.setForeground(QColor(COLORS[status]))

    def on_step_started(self, ev) -> None:
        key = ev.step_id
        # the same step id can repeat (per shipment / PO line): make the key unique
        if key in self._items:
            key = f"{ev.step_id}#{self.list.count()}"
        item = QListWidgetItem()
        self.list.addItem(item)
        self._items[key] = item
        self._titles[key] = ev.title_vi or ev.step_id
        self._last = key
        self._set(key, "running")
        self.list.scrollToItem(item)
        if ev.total:
            self.bar.setValue(int(100 * max(ev.index - 1, 0) / ev.total))

    def on_step_finished(self, ev) -> None:
        key = getattr(self, "_last", ev.step_id)
        if key not in self._items:
            return
        status = ev.status if ev.status in ICONS else "ok"
        self._set(key, status, f" — {ev.detail}" if ev.detail else "")

    def on_progress(self, ev) -> None:
        self.bar.setValue(max(0, min(100, ev.percent)))
        if ev.message_vi:
            self.message.setText(ev.message_vi)

    def statuses(self) -> list[str]:
        return [self.list.item(i).text()[:1] for i in range(self.list.count())]
