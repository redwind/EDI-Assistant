"""Locked-down portable: browser channel resolution, system check runner, autostart failure, bundled path."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from edi_assistant.app import autostart, system_check as sc
from edi_assistant.automation.session import BrowserSession
from edi_assistant.core import browser_detect as bd
from edi_assistant.core import paths
from edi_assistant.core.config import AppConfig, BrowserConfig, SiteConfig
from edi_assistant.core.errors import BrowserLaunchError


# ---------------------------------------------------------------- channel resolution
def test_launch_plan_variants():
    assert bd.launch_plan("auto", bundled=True, chromium=True) == [None, "msedge"]
    assert bd.launch_plan("auto", bundled=False, chromium=False) == ["msedge"]
    assert bd.launch_plan("auto", bundled=False, chromium=True) == ["msedge", None]
    assert bd.launch_plan("msedge", bundled=False, chromium=False) == ["msedge"]
    assert bd.launch_plan("chromium", bundled=True, chromium=True) == [None]
    assert bd.launch_plan("chrome", bundled=False, chromium=True) == ["chrome", None]


def test_failure_kind():
    assert bd.launch_failure_kind("Chromium distribution 'msedge' is not found at C:\\x") == "missing"
    assert bd.launch_failure_kind("Target page, context or browser has been closed") == "policy"
    assert bd.launch_failure_kind("weird") == "other"


class _FakeChromium:
    def __init__(self, fail_channels, msg):
        self.fail, self.msg, self.calls = fail_channels, msg, []

    def launch_persistent_context(self, channel=None, **kw):
        self.calls.append(channel)
        if channel in self.fail:
            raise PlaywrightError(self.msg)
        raise _Stop()


class _Stop(Exception):
    """Launch 'succeeded' - stop before the rest of open()."""


def _open_with(monkeypatch, tmp_path, channel, fail, msg, bundled, chromium, edge=True, chrome=False):
    fake = _FakeChromium(fail, msg)
    monkeypatch.setattr(bd, "edge_available", lambda: edge)
    monkeypatch.setattr(bd, "chrome_available", lambda: chrome)
    monkeypatch.setattr("edi_assistant.automation.session.sync_playwright",
                        lambda: SimpleNamespace(start=lambda: SimpleNamespace(chromium=fake, stop=lambda: None)))
    monkeypatch.setattr(bd, "bundled_chromium_available", lambda: bundled)
    monkeypatch.setattr(bd, "chromium_available", lambda: chromium)
    import logging
    s = BrowserSession(BrowserConfig(channel=channel), SiteConfig(), tmp_path, None, logging.getLogger("t"))
    return s, fake


def test_auto_prefers_bundled(monkeypatch, tmp_path):
    s, fake = _open_with(monkeypatch, tmp_path, "auto", set(), "x", True, True)
    with pytest.raises(_Stop):
        s.open()
    assert fake.calls == [None]


def test_auto_edge_policy_falls_back_to_chromium(monkeypatch, tmp_path):
    s, fake = _open_with(monkeypatch, tmp_path, "auto", {"msedge"}, "Target page, context or browser has been closed",
                         False, True)
    with pytest.raises(_Stop):
        s.open()
    assert fake.calls == ["msedge", None]


def test_auto_edge_blocked_no_chromium_gives_clear_message(monkeypatch, tmp_path):
    s, fake = _open_with(monkeypatch, tmp_path, "auto", {"msedge"},
                         "Browser has been closed: remote debugging pipe", False, False)
    with pytest.raises(BrowserLaunchError) as ei:
        s.open()
    assert fake.calls == ["msedge"]          # never downloads / tries anything else
    assert "RemoteDebuggingAllowed" in ei.value.message_vi and "full" in ei.value.message_vi


def test_auto_edge_missing_message(monkeypatch, tmp_path):
    s, _ = _open_with(monkeypatch, tmp_path, "msedge", {"msedge"}, "Chromium distribution 'msedge' is not found",
                      False, False)
    with pytest.raises(BrowserLaunchError) as ei:
        s.open()
    assert "full" in ei.value.message_vi


def test_bundled_path_env(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert paths.use_bundled_browsers() is False and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ
    (tmp_path / "browsers" / "chromium-1234" / "chrome-win").mkdir(parents=True)
    (tmp_path / "browsers" / "chromium-1234" / "chrome-win" / "chrome.exe").write_text("x")
    try:
        assert paths.use_bundled_browsers() is True
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "browsers")
        assert bd.bundled_chromium_available() is True
    finally:
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)


# ---------------------------------------------------------------- system check
def test_system_check_runner_with_mock_probes():
    def boom(cfg):
        raise RuntimeError("kaput")
    probes = [("CHK_DATA_DIR", lambda c: (sc.PASS, "ok")), ("CHK_EDGE", lambda c: (sc.WARN, "no")),
              ("CHK_PORTAL", boom)]
    seen = []
    res = sc.run_checks(AppConfig(), probes, progress=seen.append)
    assert [r.status for r in res] == [sc.PASS, sc.WARN, sc.FAIL] and len(seen) == 3
    rep = sc.format_report(res, AppConfig())
    assert "[FAIL]" in rep and "kaput" in rep and "1 passed, 1 warning(s), 1 failed" in rep


def test_probe_portal_failure_is_reported(monkeypatch):
    import httpx

    class C:
        def __init__(self, **kw):
            assert kw.get("trust_env") is True
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def head(self, url): raise httpx.ConnectError("proxy down")
    monkeypatch.setattr(httpx, "Client", C)
    st, detail = sc.probe_portal(AppConfig())
    assert st == sc.FAIL and "proxy down" in detail


def test_probe_data_dir_ok():
    st, detail = sc.probe_data_dir(AppConfig())
    assert st == sc.PASS


def test_system_check_dialog_runs_in_background(qtbot):
    from edi_assistant.app.dialogs.system_check_dialog import SystemCheckDialog
    probes = [("CHK_DATA_DIR", lambda c: (sc.PASS, "ok")), ("CHK_EDGE", lambda c: (sc.WARN, "missing"))]
    dlg = SystemCheckDialog(AppConfig(), probes=probes)
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.finished_ok, timeout=5000)
    assert dlg.btn_copy.isEnabled() and "[WARN]" in dlg.report_text()
    dlg.copy_report()
    from PySide6.QtGui import QGuiApplication
    assert "[PASS]" in QGuiApplication.clipboard().text()
    dlg.accept()


# ---------------------------------------------------------------- autostart failure
def test_autostart_apply_never_raises(monkeypatch):
    def deny(enabled):
        raise PermissionError("blocked by policy")
    monkeypatch.setattr(autostart, "set_start_with_windows", deny)
    assert "blocked" in autostart.apply(True)
    autostart.refresh(True)   # must not raise either
    monkeypatch.setattr(autostart, "set_start_with_windows", lambda e: None)
    assert autostart.apply(True) is None


def test_main_window_untick_autostart_on_failure(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from edi_assistant.app.main_window import MainWindow
    from edi_assistant.app.worker_bridge import WorkerBridge
    from tests.app.conftest import FakeWorker
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    monkeypatch.setattr(autostart, "apply", lambda e: "denied")
    cfg = AppConfig()
    cfg.notify.start_with_windows = True
    win = MainWindow(cfg, FakeWorker(), WorkerBridge())
    qtbot.addWidget(win)
    win._apply_autostart()
    assert cfg.notify.start_with_windows is False and len(warned) == 1


def test_default_probes_use_precomputed_notify_result():
    probes = dict(sc.default_probes(notify=(sc.WARN, "gui-thread result")))
    assert probes["CHK_NOTIFY"](AppConfig()) == (sc.WARN, "gui-thread result")


def test_closing_dialog_midrun_does_not_block_or_destroy_thread(qtbot):
    import threading
    import time
    from edi_assistant.app.dialogs import system_check_dialog as scd
    gate = threading.Event()
    probes = [("CHK_DATA_DIR", lambda c: (gate.wait(5), (sc.PASS, "ok"))[1])]
    dlg = scd.SystemCheckDialog(AppConfig(), probes=probes)
    qtbot.addWidget(dlg)
    t0 = time.monotonic()
    dlg.done(0)
    assert time.monotonic() - t0 < 1.0 and scd._LIVE
    gate.set()
    scd.wait_for_background(5000)
    qtbot.waitUntil(lambda: not scd._LIVE, timeout=5000)


def test_launch_plan_uses_chrome_when_edge_missing():
    assert bd.launch_plan("auto", bundled=False, chromium=False, edge=False, chrome=True) == ["chrome"]
    assert bd.launch_plan("auto", bundled=False, chromium=True, edge=False, chrome=True) == ["chrome", None]
    assert bd.launch_plan("auto", bundled=False, chromium=False, edge=True, chrome=True) == ["msedge", "chrome"]
    assert bd.launch_plan("auto", bundled=False, chromium=True, edge=False, chrome=False) == [None]
    assert bd.launch_plan("auto", bundled=False, chromium=False, edge=False, chrome=False) == ["msedge"]


def test_auto_mac_without_edge_uses_chrome(monkeypatch, tmp_path):
    s, fake = _open_with(monkeypatch, tmp_path, "auto", set(), "x", False, False, edge=False, chrome=True)
    with pytest.raises(_Stop):
        s.open()
    assert fake.calls == ["chrome"]
