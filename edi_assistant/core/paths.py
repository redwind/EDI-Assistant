"""User-data directory resolution (portable / %APPDATA% / XDG)."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def exe_dir() -> Path:
    """Directory of the running executable (frozen) or the repo root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def is_portable() -> bool:
    """True if <exe_dir>/portable.flag exists OR <exe_dir>/data/ is a directory."""
    d = exe_dir()
    return (d / "portable.flag").exists() or (d / "data").is_dir()


def _mk(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_data_dir() -> Path:
    override = os.environ.get("EDI_ASSISTANT_DATA_DIR")
    if override:
        return _mk(Path(override))
    if is_portable():
        try:
            return _mk(exe_dir() / "data")
        except OSError as ex:   # read-only location (spec §9): fall back to the roaming dir
            logging.getLogger(__name__).warning("portable data dir not writable (%s); using user profile", ex)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return _mk(base / "EDI Assistant")


def local_data_dir() -> Path:
    if os.environ.get("EDI_ASSISTANT_DATA_DIR") or is_portable():
        return user_data_dir()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return _mk(base / "EDI Assistant")
    return user_data_dir()


def config_path() -> Path:
    return user_data_dir() / "config.yaml"


def templates_dir() -> Path:
    return _mk(user_data_dir() / "templates")


def factories_path() -> Path:
    return user_data_dir() / "factories.json"


def learned_selectors_path() -> Path:
    return user_data_dir() / "selectors.learned.yaml"


def logs_dir() -> Path:
    return _mk(user_data_dir() / "logs")


def runs_dir() -> Path:
    return _mk(user_data_dir() / "runs")


def run_dir(run_id: str) -> Path:
    return _mk(runs_dir() / run_id)


def browser_profile_dir() -> Path:
    return _mk(local_data_dir() / "browser_profile")


def playwright_browsers_dir() -> Path:
    return _mk(local_data_dir() / "ms-playwright")


def bundled_selectors_path() -> Path:
    """Bundled selectors.yaml inside the automation package (works frozen)."""
    from importlib.resources import files

    return Path(str(files("edi_assistant.automation").joinpath("selectors.yaml")))


def bundled_browsers_dir() -> Path | None:
    """`<exe_dir>/browsers` (the "full" portable zip) if it exists; never created."""
    d = exe_dir() / "browsers"
    return d if d.is_dir() else None


def use_bundled_browsers() -> bool:
    """Point PLAYWRIGHT_BROWSERS_PATH at the bundled folder when present. Call before playwright is imported."""
    d = bundled_browsers_dir()
    if d is None:
        return False
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(d)
    return True
