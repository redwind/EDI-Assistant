"""Captures of the real EDI site live in tests/automation/fixtures/real/ (git-ignored: business data stays on the
developer machine). Tests that need them are skipped where the files are absent."""
from __future__ import annotations

from pathlib import Path

import pytest

REAL = Path(__file__).parent / "fixtures" / "real"


def real_file(name: str) -> Path:
    p = REAL / name
    if not p.exists():
        pytest.skip(f"real-site capture {name} not present (kept out of git)")
    return p
