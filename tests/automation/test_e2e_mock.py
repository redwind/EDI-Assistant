"""Full flow against the mock EDI Gateway (headless chromium)."""
from __future__ import annotations

import csv
import threading
import urllib.parse
import urllib.request

import pytest

from edi_assistant.automation.flow import FlowRunner, make_context
from edi_assistant.core.events import LogEvent, NeedsUser, UserResponse

from wpb_helpers import TODAY, make_config, make_line, make_plan

pytestmark = pytest.mark.e2e


class Harness:
    """Scripted ask_user + event capture around FlowRunner."""

    def __init__(self, server, make_session, store, plan, script=None, on_ask=None, **cfg_over):
        self.cfg = make_config(server)
        for k, v in cfg_over.items():
            section, name = k.split("__")
            setattr(getattr(self.cfg, section), name, v)
        self.events: list = []
        self.asked: list[NeedsUser] = []
        self.unexpected: list[str] = []
        self.script = {"finished_review": "continue", "dry_run_stop": "continue", **(script or {})}
        self.on_ask = on_ask
        self.session = make_session(self.cfg, self.events)
        self.plan = plan
        self.ctx = make_context(self.session, self.cfg, plan, __import__("edi_assistant.core.paths", fromlist=["x"]).run_dir(plan.run_id),
                                self.events.append, self._ask, store, abort_event=threading.Event())
        self.ctx.today = lambda: TODAY

    def _ask(self, ev: NeedsUser) -> UserResponse:
        self.asked.append(ev)
        if self.on_ask:
            self.on_ask(ev)
        action = self.script.get(ev.kind)
        if action is None:
            self.unexpected.append(ev.kind)
            action = "abort"
        return UserResponse(ev.request_id, action)

    def run(self):
        return FlowRunner(self.ctx).run(self.plan)

    def logs(self) -> list[str]:
        return [e.message for e in self.events if isinstance(e, LogEvent)]


def _sh(server):
    assert len(server.state.shipments) == 1
    return next(iter(server.state.shipments.values()))


def _assert_standard(server, harness, result, pos=("580367401", "580367301")):
    st = server.state
    assert harness.unexpected == []
    assert result.status == "done", result.error
    assert st.submit_called is False and st.submit_attempts == 0
    sh = _sh(server)
    h = sh.header
    assert h["OptShippingType"] == "3"
    assert h["txtShippingDate"] == "03/11/2026"
    assert h["OptTransMethod"] == "O"
    assert h["OptSCACCode"] == "MAEU"
    assert h["txtcarrier"] == "MAERSK"
    assert h["txtBillLading"] == "Unknown" and h["txtPRONumber"] == "Unknown"
    assert h["txtFromName"] == "SUMEC TEXTILE COMPANY LIMITED"
    assert h["txtFromAddress1"] == "1 TEST ROAD" and h["txtFromAddress2"] == "BLDG 2"
    assert h["txtFromCity"] == "NANJING" and h["txtFromState"] == "JIANGSU" and h["txtFromZip"] == "210000"
    assert h["txtFromCountry"] == "CN"
    assert set(sh.pos) == set(pos)
    for po in pos:
        assert sh.pos[po]["complete_partial"] == "Partial"
        assert sh.cartons[po]["saved"] is True
        assert sh.cartons[po]["packaging_code"] == "PCC"
        assert sh.weights[po]["weight"] == "1020.00" and sh.weights[po]["um"] == "KG"
    out = result.shipments[0]
    assert out.web_shipment_id.isdigit() and out.web_shipment_id == str(sh.shipment_id)
    assert out.status == "done"
    return sh


def test_full_flow(mock_server, make_session, selectors_store):
    plan = make_plan([make_line("580367401"), make_line("580367301", excel_row=6)])
    hx = Harness(mock_server, make_session, selectors_store, plan)
    result = hx.run()
    sh = _assert_standard(mock_server, hx, result)
    for po in ("580367401", "580367301"):
        assert sh.cartons[po]["qty_per_carton"] == "6"
        assert sh.cartons[po]["cartons_per_site"] == "85"
    assert any("via dom" in m for m in hx.logs())
    # results.csv has one row per line
    with open(result.results_csv, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2 and all(r["web_shipment_id"] == str(sh.shipment_id) for r in rows)
    assert mock_server.session_blocked == [] if hasattr(mock_server, "session_blocked") else True
    assert hx.session.blocked == []


def test_dates_in_pdf(mock_server_pdf, make_session, selectors_store):
    plan = make_plan([make_line("580367401"), make_line("580367301", excel_row=6)])
    hx = Harness(mock_server_pdf, make_session, selectors_store, plan)
    result = hx.run()
    _assert_standard(mock_server_pdf, hx, result)
    assert any("via pdf" in m for m in hx.logs())


def test_prepack_po(mock_server, make_session, selectors_store):
    plan = make_plan([make_line("668254501", packages="167", quantity="1002", gross="500.50")])
    hx = Harness(mock_server, make_session, selectors_store, plan)
    result = hx.run()
    assert hx.unexpected == [] and result.status == "done", result.error
    sh = _sh(mock_server)
    c = sh.cartons["668254501"]
    assert (c["qty_per_carton"], c["cartons_per_site"]) == ("1", "167")
    assert sh.weights["668254501"]["weight"] == "500.50"
    assert mock_server.state.submit_called is False


def test_login_required(mock_server_login, make_session, selectors_store):
    plan = make_plan([make_line("580367401")])

    def do_login(ev: NeedsUser):
        if ev.kind == "login_required":   # the user logs in (not the tool): POST outside the automated browser
            data = urllib.parse.urlencode({"userid": "u", "password": "secret"}).encode()
            urllib.request.urlopen(urllib.request.Request(mock_server_login.url + "login.do", data=data)).read()

    hx = Harness(mock_server_login, make_session, selectors_store, plan, script={"login_required": "continue"},
                 on_ask=do_login)
    result = hx.run()
    assert hx.unexpected == [] and result.status == "done", result.error
    assert [e.kind for e in hx.asked if e.kind == "login_required"] == ["login_required"]
    assert mock_server_login.state.profile_selected and mock_server_login.state.submit_called is False
    assert _sh(mock_server_login).pos["580367401"]["complete_partial"] == "Partial"


def test_dry_run(mock_server, make_session, selectors_store):
    plan = make_plan([make_line("580367401")], dry_run=True)
    hx = Harness(mock_server, make_session, selectors_store, plan)
    result = hx.run()
    assert hx.unexpected == [] and result.status == "dry_run", result.error
    assert mock_server.state.shipments == {}
    assert result.shipments[0].status == "dry_run"
    assert mock_server.state.submit_called is False
    assert [e.kind for e in hx.asked] == ["dry_run_stop"]


def test_replaced_only_po_skipped(mock_server, make_session, selectors_store):
    plan = make_plan([make_line("580367402")])
    hx = Harness(mock_server, make_session, selectors_store, plan, script={"step_failed": "skip"})
    result = hx.run()
    assert hx.unexpected == []
    failed = [e for e in hx.asked if e.kind == "step_failed"]
    assert len(failed) == 1 and "REPLACED" in failed[0].message_vi
    assert result.status == "failed"
    assert result.shipments[0].lines[0].status == "skipped"
    assert mock_server.state.shipments == {}


def test_replaced_skipped_other_po_continues(mock_server, make_session, selectors_store):
    mock_server.state.add_order("999999901", status="REPLACED", versions=1)
    plan = make_plan([make_line("999999901"), make_line("580367401", excel_row=6)])
    hx = Harness(mock_server, make_session, selectors_store, plan, script={"step_failed": "skip"})
    result = hx.run()
    assert hx.unexpected == [] and result.status == "done", result.error
    sh = _sh(mock_server)
    assert set(sh.pos) == {"580367401"}
    assert mock_server.state.submit_called is False


def test_submit_never_reached(mock_server, make_session, selectors_store):
    """Even a direct navigation to asn.do is refused and the mock stays untouched."""
    from edi_assistant.core.errors import ForbiddenActionError
    plan = make_plan([make_line("580367401")])
    hx = Harness(mock_server, make_session, selectors_store, plan)
    with pytest.raises(ForbiddenActionError):
        hx.session.goto("gateway/asn.do?shipment_id=1")
    assert mock_server.state.submit_attempts == 0


def test_weights_more_than_ten_lines_use_all_page(mock_server, make_session, selectors_store):
    """S9 alone: 12 lines -> 'orderperpage = All' is selected first, then every weight is saved."""
    from edi_assistant.automation.flow import steps as S
    from edi_assistant.mock_edi.state import MockShipment

    st = mock_server.state
    pos = [f"7000{i:03d}01" for i in range(12)]
    sh = MockShipment(shipment_id=900001)
    for i, po in enumerate(pos):
        st.add_order(po)
        sh.pos[po] = {"po_header_id": 2000 + i, "complete_partial": "Partial", "pack_code": "CTN25", "status": "Available"}
        sh.cartons[po] = {"cart_def_id": i, "items_added": True, "sites_added": True, "packaging_code": "PCC",
                          "qty_per_carton": "6", "cartons_per_site": "85", "saved": True, "error": ""}
        sh.weights[po] = {"weight": "", "um": "KG", "site_wgt_id": 3000 + i}
    st.shipments[sh.shipment_id] = sh
    lines = [make_line(po, excel_row=5 + i) for i, po in enumerate(pos)]
    for ln in lines:
        ln.status = "carton_done"
    plan = make_plan(lines)
    hx = Harness(mock_server, make_session, selectors_store, plan)
    plan.shipments[0].web_shipment_id = "900001"
    hx.ctx.current_shipment = plan.shipments[0]
    hx.session.goto("gateway/selected_pos.do?shipment_id=900001")
    assert hx.ctx.actions.exists("pos.view_detail_button")
    step = S.S9EnterWeights()
    step.act(hx.ctx)
    assert step.check(hx.ctx)
    assert all(sh.weights[po]["weight"] == "1020.00" for po in pos)
    assert mock_server.state.submit_called is False


def test_dry_run_skipped_header_step_never_persists(mock_server, make_session, selectors_store):
    """G4: when S6 fails in dry-run and the user skips it, nothing after the header form may run
    (S7's 'Selected Purchase Orders >>' would save the header)."""
    from edi_assistant.core.events import StepStarted
    selectors_store._bundled["ship.pro_number"]["candidates"] = [{"kind": "css", "css": "#definitely-missing"}]
    plan = make_plan([make_line("580367401")], dry_run=True)
    hx = Harness(mock_server, make_session, selectors_store, plan, script={"step_failed": "skip"})
    result = hx.run()
    assert hx.unexpected == []
    assert [e.kind for e in hx.asked] == ["step_failed"]
    assert result.status == "dry_run" and result.shipments[0].status == "dry_run"
    started = [e.step_id for e in hx.events if isinstance(e, StepStarted)]
    assert "S7.add_purchase_orders" not in started and started[-1] == "S6.fill_header_save"
    assert mock_server.state.shipments == {} and not any("save_header" in l for l in mock_server.state.log)
    assert mock_server.state.submit_called is False
