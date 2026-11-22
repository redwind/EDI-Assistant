"""Full multi-shipment run of the real PO tracker against the mock EDI Gateway (headless chromium)."""
from __future__ import annotations

import csv
import time

import pytest

from edi_assistant.automation.flow import FlowRunner
from edi_assistant.core.events import ShipmentCreated, UserResponse

from test_e2e_mock import Harness
from wpb_helpers import TODAY_TRACKER, make_tracker_plan

pytestmark = pytest.mark.e2e


class TrackerHarness(Harness):
    """Harness with the tracker clock and optional scripted values per ask kind."""

    def __init__(self, *a, values=None, **kw):
        super().__init__(*a, **kw)
        self.ctx.today = lambda: TODAY_TRACKER
        self.values = values or {}

    def _ask(self, ev):
        resp = super()._ask(ev)
        return UserResponse(resp.request_id, resp.action, dict(self.values.get(ev.kind, {})))


def _shipment_of(server, master):
    for sh in server.state.shipments.values():
        if any(po.startswith(master) for po in sh.pos):
            return sh
    raise AssertionError(master)


def test_tracker_full_run(mock_server_tracker, make_session, selectors_store):
    srv = mock_server_tracker
    plan = make_tracker_plan(srv)
    hx = TrackerHarness(srv, make_session, selectors_store, plan)
    t0 = time.monotonic()
    result = hx.run()
    assert time.monotonic() - t0 < 240
    st = srv.state
    assert hx.unexpected == [] and result.status == "done", result.error
    assert st.submit_called is False and st.submit_attempts == 0
    assert len(st.shipments) == 6
    assert len({s.web_shipment_id for s in result.shipments}) == 6 and all(s.web_shipment_id.isdigit() for s in result.shipments)
    expected = {"5820678": ["582067802"], "5820680": ["582068001", "582068002"], "5820682": ["582068201"],
                "5820677": ["582067701", "582067702"], "5820679": ["582067901"], "5820684": ["582068401"]}
    for master, pos in expected.items():
        sh = _shipment_of(srv, master)
        assert sorted(sh.pos) == sorted(pos)
        want = "11/11/2026" if master == "5820677" else "12/02/2026"
        assert sh.header["txtShippingDate"] == want
        for po in pos:
            assert sh.pos[po]["complete_partial"] == "Partial"
    c = lambda po: next(s for s in st.shipments.values() if po in s.pos).cartons[po]       # noqa: E731
    w = lambda po: next(s for s in st.shipments.values() if po in s.pos).weights[po]       # noqa: E731
    assert (c("582067802")["qty_per_carton"], c("582067802")["cartons_per_site"]) == ("6", "160")
    assert (c("582067701")["qty_per_carton"], c("582067701")["cartons_per_site"]) == ("6", "398")
    assert (c("582068401")["qty_per_carton"], c("582068401")["cartons_per_site"]) == ("1", "158")
    assert c("582068401")["packaging_code"] == "PCC"
    assert (w("582067802")["weight"], w("582067701")["weight"], w("582068401")["weight"]) == ("10.00", "12.00", "6.00")
    assert all(w(po)["um"] == "KG" for s in expected.values() for po in s)
    with open(result.results_csv, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 8
    assert not any("dates_mismatch_web" in r["flags"] for r in rows)
    created = [e for e in hx.events if isinstance(e, ShipmentCreated)]
    assert [e.shipment_index for e in created] == [1, 2, 3, 4, 5, 6]
    final = [e for e in hx.asked if e.kind == "finished_review"]
    assert len(final) == 1                                   # ONE summary pause after all shipments
    assert all(sh.web_shipment_id in final[0].message_vi for sh in result.shipments)
    assert all(master in final[0].message_vi for master in expected)


def test_review_between_shipments_opt_in(mock_server_tracker, make_session, selectors_store):
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan,
                        flow__review_between_shipments=True)
    result = hx.run()
    assert result.status == "done" and hx.unexpected == []
    assert [e.kind for e in hx.asked].count("finished_review") == 5     # per shipment except the last, no final


def test_pacing_between_shipments(mock_server_tracker, make_session, selectors_store, monkeypatch):
    # networkidle settle (>=500 ms quiet window per page load, ~136 loads) is real-site behaviour; the mock needs none
    monkeypatch.setattr("edi_assistant.automation.session.IDLE_CAP_MS", 1)
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan,
                        pace__enabled=True, pace__action_delay_ms=[1, 3], pace__nav_delay_ms=[1, 3],
                        pace__type_delay_ms=[1, 2], pace__between_shipments_s=[1, 1],
                        pace__max_shipments_per_hour=0)
    result = hx.run()
    assert result.status == "done", result.error
    assert hx.ctx.pacer.slept_ms >= 5000          # 6 shipments -> 5 inter-shipment pauses of 1 s


def test_web_dates_mismatch_is_flagged_not_blocking(mock_server_tracker, make_session, selectors_store):
    o = mock_server_tracker.state.orders["582068201"]
    o.early, o.late = "01-DEC-26", "05-DEC-26"
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan)
    hx.ctx.config.flow.direct_http = False   # the web-date cross-check belongs to the browser steps (direct mode uses the tracker dates)
    result = hx.run()
    assert result.status == "done" and hx.unexpected == [], result.error
    sh = next(s for s in result.shipments if s.master_pos == ["5820682"])
    assert sh.status == "done" and any(f.code == "dates_mismatch_web" for f in sh.flags)
    assert _shipment_of(mock_server_tracker, "5820682").header["txtShippingDate"] == "12/02/2026"


def test_rule_b_web_counts_packs(mock_server_tracker, make_session, selectors_store):
    o = mock_server_tracker.state.orders["582067901"]
    o.qty_ordered, o.ordered_in_packs = 158, True
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan)
    result = hx.run()
    assert result.status == "done" and hx.unexpected == [], result.error
    sh = _shipment_of(mock_server_tracker, "5820679")
    assert (sh.cartons["582067901"]["qty_per_carton"], sh.cartons["582067901"]["cartons_per_site"]) == ("1", "158")
    line = next(pl for s in result.shipments for pl in s.lines if pl.po_line.po_line_id == "582067901")
    assert any(f.code == "web_counts_packs" for f in line.carton.flags)


def test_mismatch_pause_continue_with_values(mock_server_tracker, make_session, selectors_store):
    mock_server_tracker.state.orders["582067802"].qty_ordered = 1400
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan,
                        script={"qty_mismatch": "continue"},
                        values={"qty_mismatch": {"qty_per_carton": "6", "cartons_per_site": "160"}})
    result = hx.run()
    assert result.status == "done" and hx.unexpected == [], result.error
    asks = [e for e in hx.asked if e.kind == "qty_mismatch"]
    assert len(asks) == 1 and [f.key for f in asks[0].input_fields] == ["qty_per_carton", "cartons_per_site"]
    sh = _shipment_of(mock_server_tracker, "5820678")
    assert (sh.cartons["582067802"]["qty_per_carton"], sh.cartons["582067802"]["cartons_per_site"]) == ("6", "160")
    line = next(pl for s in result.shipments for pl in s.lines if pl.po_line.po_line_id == "582067802")
    assert any(f.code == "qty_mismatch_web" for f in line.carton.flags)


def test_mismatch_pause_skip(mock_server_tracker, make_session, selectors_store):
    mock_server_tracker.state.orders["582067802"].qty_ordered = 1400
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan, script={"qty_mismatch": "skip"})
    result = hx.run()
    assert hx.unexpected == [], hx.unexpected
    sh_out = next(s for s in result.shipments if s.master_pos == ["5820678"])
    assert sh_out.status == "done" and sh_out.lines[0].status == "skipped"
    sh = _shipment_of(mock_server_tracker, "5820678")
    assert "582067802" not in sh.weights or sh.weights["582067802"]["weight"] == ""
    assert sh.cartons["582067802"]["saved"] is False


def test_rejected_carton_save_is_never_success(mock_server_tracker, make_session, selectors_store):
    """§12: the server rejects the carton Save (re-rendering the typed values). The step must fail/pause, the
    line must not become carton_done, and nothing may be saved for it."""
    mock_server_tracker.state.orders["582067802"].qty_ordered = 1400
    plan = make_tracker_plan(mock_server_tracker)
    hx = TrackerHarness(mock_server_tracker, make_session, selectors_store, plan,
                        script={"qty_mismatch": "continue", "step_failed": "skip"},
                        values={"qty_mismatch": {"qty_per_carton": "10", "cartons_per_site": "160"}})   # 1600 > 1400
    result = hx.run()
    assert hx.unexpected == [], hx.unexpected
    failed = [e for e in hx.asked if e.kind == "step_failed"]
    assert len(failed) == 1 and "exceeds" in failed[0].message_vi and failed[0].step_id.startswith("S8.create_carton")
    sh = _shipment_of(mock_server_tracker, "5820678")
    assert sh.cartons["582067802"]["saved"] is False
    line = next(pl for s in result.shipments for pl in s.lines if pl.po_line.po_line_id == "582067802")
    assert line.status == "skipped"
    assert "582067802" not in sh.weights or sh.weights["582067802"]["weight"] == ""
    assert mock_server_tracker.state.submit_called is False


def test_multi_shipment_dry_run_hard_stop(mock_server_tracker, make_session, selectors_store):
    """§12: in a multi-shipment dry run NO shipment proceeds past the header form (G4 holds for every shipment)."""
    srv = mock_server_tracker
    plan = make_tracker_plan(srv)
    plan.dry_run = True
    hx = TrackerHarness(srv, make_session, selectors_store, plan)
    result = hx.run()
    assert hx.unexpected == [] and result.status == "dry_run", result.error
    n = len(plan.shipments)
    assert n >= 2 and all(s.status == "dry_run" for s in result.shipments)
    assert [e.kind for e in hx.asked] == ["dry_run_stop"] * n          # one stop per shipment, no final review
    assert srv.state.shipments == {} and srv.state.submit_called is False
    assert not any(entry.startswith(("save_header", "carton", "weight", "SUBMIT")) for entry in srv.state.log)
    assert not any(isinstance(e, ShipmentCreated) for e in hx.events)
