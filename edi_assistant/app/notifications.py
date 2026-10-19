"""Tray balloon + sound. Windows-only parts are guarded."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import resource


def notify(tray: QSystemTrayIcon | None, title: str, text: str, *, sound: bool, balloon: bool,
           icon=QSystemTrayIcon.MessageIcon.Information) -> None:
    if balloon and tray is not None:
        tray.showMessage(title, text, icon, 10000)
    if sound:
        play_sound()


def play_sound() -> None:
    if sys.platform == "win32":
        try:
            import winsound
            winsound.PlaySound(str(resource("notify.wav")), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        except Exception:  # noqa: BLE001
            pass
    QApplication.beep()
