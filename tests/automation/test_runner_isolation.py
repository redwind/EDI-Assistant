"""Per-shipment failure isolation of the runner."""
from __future__ import annotations

import pytest

from edi_assistant.automation.flow import steps as S
from edi_assistant.core.errors import ForbiddenActionError
from edi_assistant.mock_edi import MockOptions, MockServer

from test_e2e_tracker import TrackerHarness
from wpb_helpers import make_plan, make_tracker_line

pytestmark = pytest.mark.e2e


def _three_shipment_plan():
    lines = [make_tracker_line("5820678", 1, 1428, excel_row=2), make_tracker_line("5820680", 1, 1650, excel_row=4),
             make_tracker_line("5820682", 1, 1518, excel_row=6)]
    plan = make_plan([lines[0]])
    from copy import copy
    base = plan.shipments[0]
    plan.shipments = []
    for i, ln in enumerate(lines, 1):
        sh = copy(base)
        sh.index, sh.lines, sh.master_pos, sh.label = i, [ln], [ln.po_line.master_po], f"Shipment {i}"
        sh.po_windows, sh.flags = {}, []
        plan.shipments.append(sh)
    plan.grouping, plan.profile, plan.qty_strict = "per_master_po", "po_tracker", True
    return plan


@pytest.fixture
def tracker_server():
    srv = MockServer(MockOptions(port=0, require_login=False, seed_tracker=True))
    srv.start()
    yield srv
    srv.stop()


def _boom_on_2(monkeypatch):
    real = S.S6FillHeaderSave.act

    def act(self, ctx):
        if ctx.current_shipment.index == 2:
            raise RuntimeError("boom")
        return real(self, ctx)
    monkeypatch.setattr(S.S6FillHeaderSave, "act", act)


def test_failed_shipment_does_not_stop_others(tracker_server, make_session, selectors_store, monkeypatch):
    _boom_on_2(monkeypatch)
    hx = TrackerHarness(tracker_server, make_session, selectors_store, _three_shipment_plan(),
                        script={"shipment_failed": "continue"})
    res = hx.run()
    assert [s.status for s in res.shipments] == ["done", "failed", "done"]
    assert any(f.code == "shipment_failed" for f in res.shipments[1].flags)
    assert res.status == "partial"
    asks = [e for e in hx.asked if e.kind == "shipment_failed"]
    assert len(asks) == 1 and asks[0].options == ["continue", "abort"]
    assert tracker_server.state.submit_called is False


def test_abort_after_failure(tracker_server, make_session, selectors_store, monkeypatch):
    _boom_on_2(monkeypatch)
    hx = TrackerHarness(tracker_server, make_session, selectors_store, _three_shipment_plan(),
                        script={"shipment_failed": "abort"})
    res = hx.run()
    assert res.status == "aborted"
    assert [s.status for s in res.shipments] == ["done", "failed", "aborted"]


def test_forbidden_action_stops_whole_run(tracker_server, make_session, selectors_store, monkeypatch):
    real = S.S6FillHeaderSave.act

    def act(self, ctx):
        if ctx.current_shipment.index == 1:
            raise ForbiddenActionError("blocked", message_vi="blocked")
        return real(self, ctx)
    monkeypatch.setattr(S.S6FillHeaderSave, "act", act)
    plan = _three_shipment_plan()
    hx = TrackerHarness(tracker_server, make_session, selectors_store, plan)
    res = hx.run()
    assert res.status == "failed"
    assert plan.shipments[1].status == "pending" and plan.shipments[2].status == "pending"
    assert [e.kind for e in hx.asked if e.kind == "shipment_failed"] == []
    assert tracker_server.state.shipments == {} or len(tracker_server.state.shipments) <= 1
