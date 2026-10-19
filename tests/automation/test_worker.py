"""AutomationWorker thread: command loop, ask_user round-trip, abort. No Qt involved."""
from __future__ import annotations

import queue
import threading
import time

import pytest

from edi_assistant.automation import commands as cmds
from edi_assistant.automation.commands import CloseBrowser, OpenBrowser, RunPlanCommand
from edi_assistant.automation.worker import AutomationWorker
from edi_assistant.core.events import BrowserState, LogEvent, NeedsUser, RunFinished, UserResponse

from wpb_helpers import make_config, make_line, make_plan

pytestmark = pytest.mark.e2e


class Bus:
    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.all: list = []
        self.threads: set[str] = set()

    def __call__(self, ev):
        self.threads.add(threading.current_thread().name)
        self.all.append(ev)
        self.q.put(ev)

    def wait_for(self, typ, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if isinstance(ev, typ):
                return ev
        raise AssertionError(f"timeout waiting for {typ.__name__}")


@pytest.fixture
def worker_factory(tmp_path, selectors_store):
    made = []

    def make(server):
        bus = Bus()
        w = AutomationWorker(make_config(server), bus, None, selectors=selectors_store, profile_dir=tmp_path / "wprofile")
        w.start()
        made.append(w)
        return w, bus

    yield make
    for w in made:
        w.stop(20)


def test_worker_runs_plan(mock_server, worker_factory):
    w, bus = worker_factory(mock_server)
    w.submit(OpenBrowser())
    st = bus.wait_for(BrowserState)
    assert st.is_open and "inbox.do" in st.url and w.is_browser_open
    w.submit(cmds.TestKey(key="inbox.search_button"))
    plan = make_plan([make_line("580367401")], run_id="20261018-111111-wrk1")
    w.submit(RunPlanCommand(plan=plan))
    fin = bus.wait_for(RunFinished)
    assert fin.result.status == "done", fin.result.error
    assert mock_server.state.submit_called is False
    assert fin.result.shipments[0].web_shipment_id.isdigit()
    assert any(isinstance(e, LogEvent) and "inbox.search_button: found via" in e.message for e in bus.all)
    assert bus.threads == {"edi-automation"}      # every event comes from the worker thread
    assert w.is_running is False
    w.submit(CloseBrowser())
    while bus.wait_for(BrowserState).is_open:    # skip stale states emitted earlier
        pass


def test_worker_ask_user_and_abort(mock_server_login, worker_factory):
    w, bus = worker_factory(mock_server_login)
    plan = make_plan([make_line("580367401")], run_id="20261018-111111-wrk2")
    w.submit(RunPlanCommand(plan=plan))
    ask = bus.wait_for(NeedsUser)
    assert ask.kind == "login_required" and ask.options == ["continue", "abort"]
    assert w.is_running
    w.request_abort()
    fin = bus.wait_for(RunFinished)
    assert fin.result.status == "aborted"
    assert mock_server_login.state.shipments == {}
    assert w.is_browser_open          # browser is left open as-is


def test_worker_respond_unknown_id_ignored(mock_server, worker_factory):
    w, _ = worker_factory(mock_server)
    w.respond(UserResponse("nope", "continue"))   # must not raise
