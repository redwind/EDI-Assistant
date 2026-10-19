"""Safety guards: forbidden clicks and asn.do route block."""
from __future__ import annotations

import logging
import threading

import pytest
from playwright.sync_api import Error as PlaywrightError

from edi_assistant.automation.actions import SafeActions
from edi_assistant.automation.selectors import SelectorResolver
from edi_assistant.core.errors import DataMismatchError, ForbiddenActionError, UserAbortError
from edi_assistant.core.config import FlowConfig

HTML = """
<input type=button name=btnSubmitASN value="Submit ASN" onclick="document.title='CLICKED-SUBMIT'">
<input type=button id=cancelShipment value="Cancel" onclick="document.title='CLICKED-CANCEL'">
<input type=button name=btnCancel value="Clear Values" onclick="document.title='CLICKED-CLEAR'">
<input type=button name=validateShipment value="Validate" onclick="document.title='CLICKED-VALIDATE'">
<input type=button id=sneaky value="Send" onclick="location.href='asn.do?shipment_id=1'">
<button id=sub2>Please Submit</button>
<a id=rm href="#" onclick="document.title='CLICKED-REMOVE'">Remove</a>
<input type=button id=ok value="Save" onclick="document.title='CLICKED-SAVE'">
<select id=sel><option value="a">Alpha</option><option value="b">MAEU-MAERSK</option><option value="c">Charlie</option></select>
<input id=txt>
"""


@pytest.fixture
def acts(session):
    session.page.set_content(HTML)
    from edi_assistant.core import paths
    from edi_assistant.automation.selectors import SelectorStore
    st = SelectorStore(paths.bundled_selectors_path(), paths.learned_selectors_path())
    st.load()
    flow = FlowConfig()
    ev = threading.Event()
    return SafeActions(session, SelectorResolver(st, logging.getLogger("t")), ev, lambda e: None,
                       logging.getLogger("t"), flow), session, ev


@pytest.mark.parametrize("sel", ["[name=btnSubmitASN]", "#cancelShipment", "[name=btnCancel]", "[name=validateShipment]",
                                 "#sneaky", "#sub2", "#rm"])
def test_forbidden_clicks_refused(acts, sel):
    a, session, _ = acts
    loc = session.page.locator(sel)
    with pytest.raises(ForbiddenActionError):
        a.click_locator(loc)
    assert not session.page.title().startswith("CLICKED")


def test_validate_allowed_when_configured(acts):
    a, session, _ = acts
    a.flow_cfg.click_validate = True
    a.click_locator(session.page.locator("[name=validateShipment]"))
    assert session.page.title() == "CLICKED-VALIDATE"


def test_normal_click_and_fill_and_select(acts):
    a, session, _ = acts
    a.click_locator(session.page.locator("#ok"))
    assert session.page.title() == "CLICKED-SAVE"
    a.fill_locator(session.page.locator("#txt"), "hi")
    assert a.value_of(session.page.locator("#txt")) == "hi"
    sel = session.page.locator("#sel")
    assert a.select_locator(sel, value="zzz", label="charlie") == "Charlie"          # exact label (case-insensitive)
    assert a.select_locator(sel, label_prefix="MAEU") == "MAEU-MAERSK"
    assert a.select_locator(sel, label_contains="alph") == "Alpha"
    assert a.select_locator(sel, value="b", label="Alpha") == "MAEU-MAERSK"          # value wins
    with pytest.raises(DataMismatchError) as ei:
        a.select_locator(sel, label="nothing")
    assert "Alpha" in ei.value.ctx["options"]


def test_abort_checked_before_action(acts):
    a, session, ev = acts
    ev.set()
    with pytest.raises(UserAbortError):
        a.click_locator(session.page.locator("#ok"))
    assert session.page.title() != "CLICKED-SAVE"


def test_route_block_aborts_asn(mock_server, session):
    session.goto("gateway/inbox.do")
    r = session.page.evaluate("() => fetch('/vms-gateway/gateway/asn.do?shipment_id=2').then(() => 'ok', () => 'blocked')")
    assert r == "blocked"
    with pytest.raises(PlaywrightError):
        session.page.goto(mock_server.url + "gateway/asn.do?shipment_id=1")
    assert mock_server.state.submit_called is False and mock_server.state.submit_attempts == 0
    assert len(session.blocked) == 2 and all("asn.do" in u for u in session.blocked)


def test_goto_refuses_asn(mock_server, session):
    with pytest.raises(ForbiddenActionError):
        session.goto("gateway/asn.do?shipment_id=1")


def test_fill_refuses_password_field(acts):
    """G9: even a learned/AI locator that lands on a password box is never typed into."""
    a, session, _ = acts
    session.page.set_content('<input type=password id=pw><input type=text id=u>')
    with pytest.raises(ForbiddenActionError):
        a.fill_locator(session.page.locator("#pw"), "secret")
    assert a.value_of(session.page.locator("#pw")) == ""
    a.fill_locator(session.page.locator("#u"), "ok")
    assert a.value_of(session.page.locator("#u")) == "ok"


def test_forbidden_reason_shared_helper(acts):
    from edi_assistant.automation.actions import forbidden_reason
    _, session, _ = acts
    assert forbidden_reason(session.page.locator("[name=btnSubmitASN]"))
    assert forbidden_reason(session.page.locator("[name=validateShipment]"))
    assert forbidden_reason(session.page.locator("[name=validateShipment]"), click_validate=True) == ""
    assert forbidden_reason(session.page.locator("#ok")) == ""


def test_click_reports_navigation(acts):
    """§12: click(...expect_navigation=True) tells the caller whether the page actually reloaded; Save steps
    treat 'no reload' as a failure instead of trusting a read-back of the values they just typed."""
    a, session, _ = acts
    target = session.site.effective_base_url() + "gateway/inbox.do"
    session.page.set_content(f"<input type=button id=stay value='Save' onclick=\"document.title='STAYED'\">"
                             f"<input type=button id=go value='Save' onclick=\"location.href='{target}'\">")
    assert a.click_locator(session.page.locator("#stay"), expect_navigation=True, nav_timeout_ms=400) is False
    assert session.page.title() == "STAYED"
    assert a.click_locator(session.page.locator("#go"), expect_navigation=True) is True
    assert "inbox.do" in session.page.url
    assert a.click_locator(session.page.locator("input[value=Search]")) is False   # no navigation expected -> False
