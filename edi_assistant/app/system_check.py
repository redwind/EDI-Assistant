"""System check: PASS/WARN/FAIL report about what this (possibly locked-down) PC allows. Qt-free; runs off the GUI thread."""
from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from edi_assistant import __version__
from edi_assistant.core import browser_detect as bd
from edi_assistant.core import paths
from edi_assistant.core.config import AppConfig

from .strings import S

log = logging.getLogger(__name__)
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
PORTAL_URL = "https://edi.coat.com/vms-gateway/login.do"


@dataclass(slots=True)
class CheckResult:
    status: str
    name: str
    detail: str = ""

    def line(self) -> str:
        return f"[{self.status}] {self.name}" + (f": {self.detail}" if self.detail else "")


# ------------------------------------------------------------------ probes (each returns (status, detail))
def probe_data_dir(cfg: AppConfig) -> tuple[str, str]:
    try:
        d = paths.user_data_dir()
        t = d / ".write_test"
        t.write_text("x", encoding="utf-8")
        t.unlink()
    except OSError as ex:
        return FAIL, f"{ex}"
    kind = "portable" if paths.is_portable() and d.parent == paths.exe_dir() else "user profile"
    return PASS, f"{d} ({kind})"


def probe_bundled(cfg: AppConfig) -> tuple[str, str]:
    if bd.bundled_chromium_available():
        return PASS, str(paths.bundled_browsers_dir())
    if bd.chromium_available():
        return PASS, f"downloaded Chromium in {paths.playwright_browsers_dir()}"
    return WARN, S.CHK_NOT_FOUND


def probe_edge(cfg: AppConfig) -> tuple[str, str]:
    if bd.edge_available():
        return PASS, S.CHK_OK_FOUND
    return WARN, S.CHK_NOT_FOUND


def probe_browser_launch(cfg: AppConfig, headless: bool) -> tuple[str, str]:
    """Launch the browser the app would use (same plan as the real session) and close it again."""
    plan = bd.launch_plan(cfg.browser.channel, bundled=bd.bundled_chromium_available(), chromium=bd.chromium_available())
    prof = Path(tempfile.mkdtemp(prefix="edi-syscheck-"))
    errors: list[str] = []
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            for ch in plan:
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        str(prof), channel=ch, headless=headless, timeout=20000,
                        args=["--disable-blink-features=AutomationControlled"])
                except PlaywrightError as ex:
                    errors.append(f"{ch or 'chromium'}: {str(ex).strip().splitlines()[0] if str(ex).strip() else ex}")
                    continue
                try:
                    ctx.close()
                except Exception:  # noqa: BLE001
                    pass
                return PASS, f"launched {ch or 'chromium'}"
    except Exception as ex:  # noqa: BLE001 - driver missing, etc.
        errors.append(str(ex).strip().splitlines()[0] if str(ex).strip() else repr(ex))
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return FAIL, "; ".join(errors) + "  -> " + S.CHK_HINT_NO_BROWSER


def probe_portal(cfg: AppConfig) -> tuple[str, str]:
    try:
        import httpx
        with httpx.Client(timeout=8.0, trust_env=True, follow_redirects=True) as c:
            try:
                r = c.head(PORTAL_URL)
                if r.status_code in (405, 501):
                    r = c.get(PORTAL_URL)
            except httpx.HTTPStatusError:
                r = c.get(PORTAL_URL)
        if r.status_code < 500:
            return PASS, f"HTTP {r.status_code}"
        return WARN, f"HTTP {r.status_code}"
    except Exception as ex:  # noqa: BLE001 - proxy / DNS / TLS / timeout: all reported, none raised
        return FAIL, f"{type(ex).__name__}: {ex}  -> {S.CHK_HINT_PORTAL}"


def probe_autostart(cfg: AppConfig) -> tuple[str, str]:
    if sys.platform != "win32":
        return PASS, S.CHK_SKIPPED
    try:
        import winreg
        from .autostart import RUN_KEY
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, "EDIAssistantCheck", 0, winreg.REG_SZ, "x")
            winreg.DeleteValue(k, "EDIAssistantCheck")
        return PASS, "HKCU Run key is writable"
    except OSError as ex:
        return WARN, f"{ex} (optional feature; the app works without it)"


def probe_notifications(cfg: AppConfig) -> tuple[str, str]:
    try:
        from PySide6.QtWidgets import QSystemTrayIcon
        if QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages():
            return PASS, "tray + balloon available"
        return WARN, "system tray / balloon notifications unavailable (sound/log only)"
    except Exception as ex:  # noqa: BLE001
        return WARN, str(ex)


def default_probes(notify: tuple[str, str] | None = None) -> list[tuple[str, Callable[[AppConfig], tuple[str, str]]]]:
    """`notify` = a `probe_notifications()` result evaluated on the GUI thread (QSystemTrayIcon statics must not be
    called from the worker thread); when omitted the probe runs where the checks run."""
    return [
        ("CHK_DATA_DIR", probe_data_dir),
        ("CHK_BUNDLED", probe_bundled),
        ("CHK_EDGE", probe_edge),
        ("CHK_BROWSER_HEADLESS", lambda c: probe_browser_launch(c, True)),
        ("CHK_BROWSER_HEADED", lambda c: probe_browser_launch(c, False)),
        ("CHK_PORTAL", probe_portal),
        ("CHK_AUTOSTART", probe_autostart),
        ("CHK_NOTIFY", (lambda c: notify) if notify is not None else probe_notifications),
    ]


def run_checks(cfg: AppConfig, probes=None, progress: Callable[[CheckResult], None] | None = None) -> list[CheckResult]:
    """Run every probe; a probe that raises becomes FAIL (never propagates)."""
    out: list[CheckResult] = []
    for key, fn in (probes if probes is not None else default_probes()):
        name = getattr(S, key, key)
        try:
            status, detail = fn(cfg)
        except Exception as ex:  # noqa: BLE001
            status, detail = FAIL, f"{type(ex).__name__}: {ex}"
        r = CheckResult(status, name, detail)
        log.info("system check: %s", r.line())
        out.append(r)
        if progress:
            progress(r)
    return out


def summarize(results: list[CheckResult]) -> str:
    n = {s: sum(1 for r in results if r.status == s) for s in (PASS, WARN, FAIL)}
    return S.SYSCHECK_SUMMARY.format(n_pass=n[PASS], n_warn=n[WARN], n_fail=n[FAIL])


def format_report(results: list[CheckResult], cfg: AppConfig | None = None) -> str:
    lines = [S.SYSCHECK_REPORT_HEADER.format(version=__version__),
             f"OS: {sys.platform}; frozen: {bool(getattr(sys, 'frozen', False))}; exe dir: {paths.exe_dir()}"]
    if cfg is not None:
        lines.append(f"browser.channel: {cfg.browser.channel}")
    lines += [r.line() for r in results]
    lines.append(summarize(results))
    return "\n".join(lines)
