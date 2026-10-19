from pathlib import Path

import pytest

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "5803674 & 5803673 PKL.xlsx"


@pytest.fixture
def sample_path() -> Path:
    return SAMPLE


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "userdata"
    monkeypatch.setenv("EDI_ASSISTANT_DATA_DIR", str(d))
    return d


TRACKER = Path(__file__).resolve().parents[2] / "docs" / "Copy of 6102 - Q4 Pet Beds Current - MDDP-PO tracker-1009 - 副本.xlsx"


@pytest.fixture
def tracker_path() -> Path:
    if not TRACKER.exists():
        pytest.skip("PO tracker sample is missing")
    return TRACKER
