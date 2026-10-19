"""Browser detection and launch-channel resolution (pure logic, no Qt / Playwright imports)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import paths

_EXE_NAMES = {"chrome", "chrome.exe", "chromium", "headless_shell", "headless_shell.exe",
              "chrome-headless-shell", "chrome-headless-shell.exe"}
_EXE_GLOBS = ("chrome-win/chrome.exe", "chrome-win64/chrome.exe", "chrome-linux/chrome", "chrome-linux64/chrome",
              "chrome-headless-shell-*/chrome-headless-shell*", "chrome-mac*/*/Contents/MacOS/*")

CHANNELS = ("auto", "msedge", "chromium")


def _has_exe(d: Path) -> bool:
    for pat in _EXE_GLOBS:   # bounded patterns: no recursive walk of the whole cache on the GUI thread
        if any(p.is_file() for p in d.glob(pat)):
            return True
    return any(p.is_file() and p.name.lower() in _EXE_NAMES for p in d.glob("*"))


def _root_has_chromium(root: Path) -> bool:
    return root.is_dir() and any(d.is_dir() and _has_exe(d) for d in root.glob("chromium*-*"))


def bundled_chromium_available() -> bool:
    """Chromium shipped inside the portable folder (`browsers\\`, the "full" zip)."""
    d = paths.bundled_browsers_dir()
    return d is not None and _root_has_chromium(d)


def chromium_available() -> bool:
    """Bundled or previously downloaded Playwright Chromium."""
    if bundled_chromium_available():
        return True
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env and env != "0" and _root_has_chromium(Path(env)):
        return True
    return _root_has_chromium(paths.playwright_browsers_dir())


def edge_available() -> bool:
    if sys.platform == "win32":
        cands = []
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        if any(c.is_file() for c in cands):
            return True
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"):
                return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return Path("/Applications/Microsoft Edge.app").exists()
    return False


def launch_plan(channel: str, *, bundled: bool, chromium: bool) -> list[str | None]:
    """Ordered launch attempts. Each item is a Playwright `channel` value; None means bundled/downloaded Chromium.

    auto     : bundled Chromium if present, else Edge (then downloaded Chromium if available).
    msedge   : Edge, then Chromium if available.
    chromium : Chromium only.
    other    : passed through (e.g. "chrome"), then Chromium if available.
    """
    ch = (channel or "auto").strip().lower()
    if ch in ("chromium", ""):
        return [None]
    if ch == "auto":
        if bundled:
            return [None, "msedge"]
        return ["msedge"] + ([None] if chromium else [])
    return [ch] + ([None] if chromium else [])


_POLICY_HINTS = ("remote debugging", "remote-debugging", "remotedebugging", "devtools", "policy", "pipe",
                 "browser has been closed", "process did not exit", "spawn", "eperm", "eacces",
                 "access is denied", "timeout")
_MISSING_HINTS = ("executable doesn't exist", "is not found", "not found at", "distribution", "enoent",
                  "cannot find", "no such file", "install")


def launch_failure_kind(err: object) -> str:
    """Classify a launch error text: 'missing' | 'policy' | 'other'."""
    t = str(err).lower()
    if any(h in t for h in _MISSING_HINTS):
        return "missing"
    if any(h in t for h in _POLICY_HINTS):
        return "policy"
    return "other"


LOCKED_DOWN_MESSAGE = (
    "Could not start Microsoft Edge for automation. Your company's IT policy probably blocks it "
    "(for example the Edge policy RemoteDebuggingAllowed = disabled), or Edge is not installed. "
    "Use the 'full' portable zip (EDI-Assistant-portable-full-<version>.zip), which includes its own Chromium, "
    "or ask IT to allow remote debugging for Edge. Help > System check shows details.")
