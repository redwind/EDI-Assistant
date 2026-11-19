"""QApplication bootstrap: single instance, worker, window, tray."""
from __future__ import annotations

import argparse
import os
import socket
import sys


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="EDI Assistant")
    p.add_argument("--minimized", action="store_true", help="start in the tray")
    p.add_argument("--mock", action="store_true", help="use the built-in mock EDI site for this session")
    p.add_argument("--data-dir", default="", help="override the user-data directory")
    ns, _unknown = p.parse_known_args(argv)  # Qt may add its own flags
    return ns


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


APP_USER_MODEL_ID = "ShyftGlobal.EDIAssistant"


def set_app_user_model_id() -> bool:
    """Windows only: attribute toasts/taskbar to EDI Assistant instead of python(w).exe. Never raises."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.data_dir:
        os.environ["EDI_ASSISTANT_DATA_DIR"] = args.data_dir
    # Must happen BEFORE playwright is imported anywhere.
    from edi_assistant.core import paths
    if not paths.use_bundled_browsers():   # full portable zip: <exe dir>\browsers wins over the user cache
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(paths.playwright_browsers_dir()))

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from edi_assistant import APP_DISPLAY_NAME, __version__
    from edi_assistant.core.config import load_config, save_config
    from edi_assistant.core.logging_setup import setup_logging

    from . import autostart, resource
    from .ai import build_advisor
    from .main_window import MainWindow
    from .single_instance import SingleInstance
    from .tray import TrayIcon
    from .worker_bridge import WorkerBridge

    setup_logging()
    cfg = load_config()
    from .strings import set_language
    set_language(cfg.ui.language)

    set_app_user_model_id()   # must precede QApplication creation
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("SHYFT GLOBAL")
    app.setWindowIcon(QIcon(str(resource("app.png"))))

    guard = SingleInstance(version=__version__)
    if not guard.try_acquire():
        if guard.running_version is None:
            return 0   # same version already running: it raised its window
        if not _replace_other_version(guard):
            return 0

    mock = None
    if args.mock:
        from edi_assistant.mock_edi.server import MockOptions, MockServer
        mock = MockServer(MockOptions(port=_free_port(), require_login=False))
        from edi_assistant.core.config import set_runtime_mock_url
        set_runtime_mock_url(mock.start())   # process-only override: never written to config.yaml

    from edi_assistant.automation.worker import AutomationWorker

    bridge = WorkerBridge()
    worker = AutomationWorker(cfg, bridge.sink, build_advisor(cfg.ai))
    worker.start()

    win = MainWindow(cfg, worker, bridge, startup_checks=True)
    guard.show_requested.connect(win.show_and_raise)
    guard.quit_requested.connect(win.request_quit)
    win.tray = TrayIcon(win)
    autostart.refresh(cfg.notify.start_with_windows)
    if not (cfg.notify.start_minimized or args.minimized):
        win.show()

    code = app.exec()
    worker.stop()
    guard.release()
    if mock is not None:
        mock.stop()
    save_config(cfg)
    return code


def _replace_other_version(guard) -> bool:
    """Another version is running. Offer to close it; True when this launch may continue."""
    from PySide6.QtWidgets import QMessageBox

    from edi_assistant import __version__

    from .single_instance import UNKNOWN_VERSION
    from .strings import S

    other = guard.running_version
    if other == UNKNOWN_VERSION:   # old build: cannot be closed remotely, it has already shown itself
        QMessageBox.warning(None, S.APP_TITLE, S.INSTANCE_OLD_RUNNING.format(version=__version__))
        return False
    if QMessageBox.question(None, S.APP_TITLE, S.INSTANCE_OTHER_VERSION.format(
            running=other, version=__version__)) != QMessageBox.StandardButton.Yes:
        guard.raise_running()
        return False
    if guard.replace_running():
        return True
    QMessageBox.warning(None, S.APP_TITLE, S.INSTANCE_QUIT_TIMEOUT.format(running=other))
    return False
