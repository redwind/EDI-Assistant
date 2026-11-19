"""Chromium fallback download via the Playwright driver CLI."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEventLoop, QProcess, QProcessEnvironment
from PySide6.QtWidgets import QProgressDialog, QWidget

from edi_assistant.core import paths
from edi_assistant.core.browser_detect import chrome_available, chromium_available, edge_available  # noqa: F401

from .strings import S


def install_command() -> list[str]:
    """Command that runs `playwright install chromium` (dev vs frozen)."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "playwright", "install", "chromium"]
    from playwright._impl._driver import compute_driver_executable
    drv = compute_driver_executable()
    node, cli = (drv if isinstance(drv, tuple) else (drv, None))
    cmd = [str(node)] + ([str(cli)] if cli else [])
    return cmd + ["install", "chromium"]


def install_chromium(parent: QWidget | None) -> bool:
    cmd = install_command()
    dlg = QProgressDialog(S.INSTALL_CHROMIUM_PROGRESS, S.BTN_CANCEL, 0, 0, parent)
    dlg.setWindowTitle(S.INSTALL_CHROMIUM_TITLE)
    dlg.setMinimumDuration(0)
    proc = QProcess(dlg)
    env = QProcessEnvironment.systemEnvironment()
    import os
    env.insert("PLAYWRIGHT_BROWSERS_PATH", os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(paths.playwright_browsers_dir()))
    proc.setProcessEnvironment(env)
    proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    loop = QEventLoop()

    def on_out() -> None:
        lines = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").strip().splitlines()
        if lines:
            dlg.setLabelText(S.INSTALL_CHROMIUM_PROGRESS + "\n" + lines[-1][:120])

    proc.readyReadStandardOutput.connect(on_out)
    proc.finished.connect(lambda *_: loop.quit())
    proc.errorOccurred.connect(lambda *_: loop.quit())
    dlg.canceled.connect(proc.kill)
    proc.start(cmd[0], cmd[1:])
    dlg.show()
    loop.exec()
    dlg.close()
    return proc.exitStatus() == QProcess.ExitStatus.NormalExit and proc.exitCode() == 0
