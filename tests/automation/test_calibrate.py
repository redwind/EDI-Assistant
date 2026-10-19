"""Calibrate mode: picker.js candidates, pick binding, highlight."""
from __future__ import annotations

import logging

import pytest

from edi_assistant.automation.calibrate import Calibrator, picker_source
from edi_assistant.automation.selectors import SelectorResolver
from edi_assistant.core.events import CalibrationResult

HTML = """
<form><label for=ship>Shipping Date</label><input id=ship name=txtShip>
<input name=dup><input name=dup>
<input type=button value="Create Carton" onclick="document.title='clicked'">
<a href="#x" id=3>Open order</a>
<table><tr><td>Plain</td><td><input type=text></td></tr></table></form>
"""


@pytest.fixture
def page(session):
    p = session.page
    p.set_content(HTML)
    p.evaluate(picker_source())
    return p


def cands(page, selector):
    return page.eval_on_selector(selector, "el => window.__ediCandidates(el)")


def test_candidates_id_name_priority(page):
    c = cands(page, "#ship")
    assert c[0] == {"kind": "css", "css": "#ship"}
    assert c[1] == {"kind": "css", "css": 'input[name="txtShip"]'}
    assert c[-1]["kind"] == "css" and ":nth-child(" in c[-1]["css"]
    assert any(x["kind"] == "xpath" and "Shipping Date" in x["xpath"] for x in c)
    assert any(x["kind"] == "role" and x["role"] == "textbox" and x["name"] == "Shipping Date" for x in c)


def test_candidates_button_link_and_numeric_id(page):
    c = cands(page, "input[type=button]")
    assert {"kind": "role", "role": "button", "name": "Create Carton", "exact": True} in c
    assert {"kind": "css", "css": 'input[value="Create Carton"]'} in c
    c = cands(page, "a")
    assert not any(x.get("css") == "#3" for x in c)           # numeric-only id skipped
    assert {"kind": "role", "role": "link", "name": "Open order", "exact": True} in c
    c = cands(page, "input[name=dup]")
    assert not any('name="dup"' in x.get("css", "") for x in c)   # non-unique name skipped


def test_picked_candidate_resolves_to_same_element(page):
    for sel in ("#ship", "input[type=button]", "td input"):
        for cand in cands(page, sel):
            if cand["kind"] in ("css", "xpath"):
                loc = page.locator(cand["css"] if cand["kind"] == "css" else "xpath=" + cand["xpath"])
                assert loc.count() >= 1


def test_pick_flow_saves_learned(session, selectors_store, page):
    events = []
    cal = Calibrator(session, selectors_store, SelectorResolver(selectors_store, logging.getLogger("t")),
                     events.append, logging.getLogger("t"))
    cal.pick("ship.shipping_date")
    assert page.locator("div", has_text="Click the element for: ship.shipping_date").count() >= 1
    page.click("#ship")
    page.wait_for_timeout(300)
    res = [e for e in events if isinstance(e, CalibrationResult)]
    assert len(res) == 1 and res[0].saved and res[0].candidate["css"] == "#ship"
    assert selectors_store.candidates("ship.shipping_date")[0].css == "#ship"
    assert selectors_store.get("ship.shipping_date").verified is True
    # picker removed itself: next click is a normal click
    page.click("input[type=button]")
    assert page.title() == "clicked"


def test_cancel_pick_and_highlight(session, selectors_store, page):
    events = []
    cal = Calibrator(session, selectors_store, SelectorResolver(selectors_store, logging.getLogger("t")),
                     events.append, logging.getLogger("t"))
    cal.pick("ship.shipping_date")
    cal.cancel_pick()
    res = [e for e in events if isinstance(e, CalibrationResult)]
    assert res[-1].saved is False and res[-1].candidate is None
    session.page.set_content("<input id=txtShippingDate>")
    assert cal.highlight("ship.shipping_date", {}) is True
    assert "255, 59, 48" in session.page.eval_on_selector("#txtShippingDate", "e => getComputedStyle(e).outlineColor")
    assert cal.highlight("ship.web_shipment_id", {}) is False


def test_pick_refuses_guarded_element(session, selectors_store):
    """Picking Submit ASN (or a password box) for any key is refused and nothing is learned."""
    p = session.page
    p.set_content('<input type=button name=btnSubmitASN value="Submit ASN"><input type=password id=pw>')
    p.evaluate(picker_source())
    events = []
    cal = Calibrator(session, selectors_store, SelectorResolver(selectors_store, logging.getLogger("t")),
                     events.append, logging.getLogger("t"))
    for sel in ("[name=btnSubmitASN]", "#pw"):
        cal.pick("ship.save_button")
        p.click(sel)
        p.wait_for_timeout(300)
    res = [e for e in events if isinstance(e, CalibrationResult)]
    assert len(res) == 2 and all(r.saved is False and r.candidate is None for r in res)
    assert all(c.source == "bundled" for c in selectors_store.candidates("ship.save_button"))
    assert selectors_store.get("ship.save_button").verified is True   # bundled flag untouched


def test_pick_tolerates_already_registered_binding(session):
    from playwright.sync_api import Error as PlaywrightError
    page = session.page
    calls = []

    class Wrapped:
        def __init__(self, p): self.p = p
    cal = Calibrator(session, None, None, lambda ev: None, logging.getLogger("t"))
    orig = page.expose_binding
    page.expose_binding = lambda name, fn: (calls.append(name), (_ for _ in ()).throw(
        PlaywrightError("Function \"__ediPicked\" has been already registered")))[1]
    try:
        cal.pick("some.key")   # must not raise
        cal.cancel_pick()
    finally:
        page.expose_binding = orig
    assert calls == ["__ediPicked"] and page in cal._exposed
