import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

SAMPLE = None


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("EDI_ASSISTANT_DATA_DIR", str(d))
    return d


@pytest.fixture
def sample_xlsx():
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "docs" / "5803674 & 5803673 PKL.xlsx"
    if not p.exists():
        pytest.skip("sample Excel missing")
    return p


class FakeWorker:
    """Stand-in for AutomationWorker."""

    def __init__(self):
        self.commands, self.responses, self.configs, self.advisors = [], [], [], []
        self.is_running = False
        self.is_browser_open = False
        self.aborted = False

    def submit(self, cmd):
        self.commands.append(cmd)

    def respond(self, resp):
        self.responses.append(resp)

    def request_abort(self):
        self.aborted = True

    def update_config(self, cfg):
        self.configs.append(cfg)

    def set_advisor(self, adv):
        self.advisors.append(adv)

    def start(self):
        pass

    def stop(self, timeout_s=10):
        pass


@pytest.fixture
def fake_worker():
    return FakeWorker()



@pytest.fixture
def tracker_xlsx():
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "docs" / "Copy of 6102 - Q4 Pet Beds Current - MDDP-PO tracker-1009 - 副本.xlsx"
    if not p.exists():
        pytest.skip("tracker Excel missing")
    return p
