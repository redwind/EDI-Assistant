"""Fixtures for WP-B tests: mock server, browser session, selector store."""
from __future__ import annotations

import logging
import threading

import pytest

from edi_assistant.automation.selectors import SelectorStore
from edi_assistant.automation.session import BrowserSession
from edi_assistant.core import paths
from edi_assistant.core.config import AppConfig
from edi_assistant.mock_edi import MockOptions, MockServer
from wpb_helpers import make_config


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("EDI_ASSISTANT_DATA_DIR", str(d))
    return d


def _server(**kw):
    srv = MockServer(MockOptions(port=0, **kw))
    srv.start()
    return srv


@pytest.fixture
def mock_server():
    srv = _server(require_login=False)
    yield srv
    srv.stop()


@pytest.fixture
def mock_server_tracker():
    srv = _server(require_login=False, seed_tracker=True)
    yield srv
    srv.stop()


@pytest.fixture
def mock_server_login():
    srv = _server(require_login=True)
    yield srv
    srv.stop()


@pytest.fixture
def mock_server_pdf():
    srv = _server(require_login=False, dates_in_pdf=True)
    yield srv
    srv.stop()


@pytest.fixture
def selectors_store(tmp_path):
    st = SelectorStore(paths.bundled_selectors_path(), tmp_path / "selectors.learned.yaml")
    st.load()
    return st


@pytest.fixture
def app_config(mock_server):
    return make_config(mock_server)


@pytest.fixture
def make_session(tmp_path):
    sessions = []

    def factory(cfg: AppConfig, events=None) -> BrowserSession:
        sink = (events.append if events is not None else (lambda e: None))
        s = BrowserSession(cfg.browser, cfg.site, tmp_path / f"profile{len(sessions)}", sink, logging.getLogger("test"))
        s.open()
        sessions.append(s)
        return s

    yield factory
    for s in sessions:
        s.close()


@pytest.fixture
def session(mock_server, make_session):
    return make_session(make_config(mock_server))
