"""System check dialog: runs the checks on a background thread, shows PASS/WARN/FAIL, copy report for IT."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from edi_assistant.core.config import AppConfig

from .. import system_check as sc
from ..strings import S


_LIVE: list[tuple[QThread, QObject]] = []   # worker threads that must outlive a closed dialog (never destroyed while running)


def wait_for_background(timeout_ms: int = 30000) -> None:
    """Call on application exit: let still-running probe threads finish so Qt never aborts on a running QThread."""
    for th, _r in list(_LIVE):
        try:
            if th.isRunning():
                th.quit()
                th.wait(timeout_ms)
        except RuntimeError:
            pass


class _Runner(QObject):
    result = Signal(object)
    done = Signal()

    def __init__(self, cfg: AppConfig, probes):
        super().__init__()
        self.cfg, self.probes = cfg, probes

    def run(self) -> None:
        try:
            sc.run_checks(self.cfg, self.probes, progress=self.result.emit)
        finally:
            self.done.emit()


class SystemCheckDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None, probes=None):
        super().__init__(parent)
        self.cfg = cfg
        if probes is None:   # GUI-thread-only Qt statics are evaluated here, before the worker starts
            probes = sc.default_probes(notify=sc.probe_notifications(cfg))
        self.results: list[sc.CheckResult] = []
        self.finished_ok = False
        self.setWindowTitle(S.SYSCHECK_TITLE)
        self.resize(760, 420)
        lay = QVBoxLayout(self)
        self.status = QLabel(S.SYSCHECK_RUNNING)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        lay.addWidget(self.status)
        lay.addWidget(self.view, 1)
        h = QHBoxLayout()
        self.btn_copy = QPushButton(S.SYSCHECK_COPY)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self.copy_report)
        btn_close = QPushButton(S.SYSCHECK_CLOSE)
        btn_close.clicked.connect(self.accept)
        h.addStretch(1)
        h.addWidget(self.btn_copy)
        h.addWidget(btn_close)
        lay.addLayout(h)
        self._thread = QThread()   # no Qt parent: it may outlive this dialog (see done())
        self._runner = _Runner(cfg, probes)
        self._runner.moveToThread(self._thread)
        self._thread.started.connect(self._runner.run)
        self._runner.result.connect(self._on_result)
        self._runner.done.connect(self._on_done)
        self._runner.done.connect(self._thread.quit)
        entry = (self._thread, self._runner)
        _LIVE.append(entry)
        self._thread.finished.connect(lambda e=entry: _LIVE.remove(e) if e in _LIVE else None)
        self._thread.start()

    def _on_result(self, r) -> None:
        self.results.append(r)
        self.view.appendPlainText(r.line())

    def _on_done(self) -> None:
        self.finished_ok = True
        self.status.setText(sc.summarize(self.results))
        self.btn_copy.setEnabled(True)

    def report_text(self) -> str:
        return sc.format_report(self.results, self.cfg)

    def copy_report(self) -> None:
        QGuiApplication.clipboard().setText(self.report_text())
        self.status.setText(sc.summarize(self.results) + " - " + S.SYSCHECK_COPIED)

    def done(self, code: int) -> None:
        # never block the GUI thread: detach from the dialog and let the (module-owned) thread finish by itself
        if self._thread.isRunning():
            for sig, slot in ((self._runner.result, self._on_result), (self._runner.done, self._on_done)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        super().done(code)
