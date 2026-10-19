"""PySide6 desktop app (WP-C)."""
from pathlib import Path


def resource(name: str) -> Path:
    """Path of a bundled resource file (works in dev and in the PyInstaller build)."""
    return Path(__file__).resolve().parent / "resources" / name
