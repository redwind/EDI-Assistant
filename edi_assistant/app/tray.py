"""System tray icon."""
from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import resource
from .strings import S


class TrayIcon(QSystemTrayIcon):
    """Expects the window to provide show_and_raise(), open_browser() and request_quit()."""

    def __init__(self, window):
        super().__init__(QIcon(str(resource("app.png"))), window)
        self._win = window
        self.setToolTip(S.TRAY_TOOLTIP)
        menu = QMenu()
        for label, slot in ((S.TRAY_SHOW, window.show_and_raise), (S.TRAY_OPEN_BROWSER, window.open_browser),
                            (S.TRAY_QUIT, window.request_quit)):
            act = QAction(label, menu)
            act.triggered.connect(slot)
            menu.addAction(act)
        self._menu = menu  # keep alive
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.show()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._win.show_and_raise()
