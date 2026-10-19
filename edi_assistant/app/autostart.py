"""Start with Windows via HKCU Run key. No-op on other platforms."""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "EDIAssistant"


def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    return f'"{sys.executable}" -m edi_assistant --minimized'


def set_start_with_windows(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enabled:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass


def is_start_with_windows() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE_NAME)
            return True
    except OSError:
        return False


def refresh(enabled: bool) -> None:
    """Re-write the entry on every start so it follows the current exe path (portable folder moves)."""
    try:
        if enabled:
            set_start_with_windows(True)
    except Exception:  # noqa: BLE001 - policy may refuse the write; never block startup
        pass


def apply(enabled: bool) -> str | None:
    """set_start_with_windows that never raises: returns an error text if the registry write was refused."""
    try:
        set_start_with_windows(enabled)
        return None
    except Exception as ex:  # noqa: BLE001 - OSError/PermissionError under group policy
        return str(ex) or type(ex).__name__
