"""Healer (fake advisor), budget, snapshot redaction."""
from __future__ import annotations

import logging
from datetime import date

import pytest

from edi_assistant.automation.dom_snapshot import PageSnapshot, capture
from edi_assistant.automation.healing import Healer
from edi_assistant.automation.selectors import SelectorResolver
from edi_assistant.core.ai_interface import (Explanation, LocatorProposal, ReadFieldsResult)
from edi_assistant.core.errors import AiError, ElementNotFoundError


class FakeAdvisor:
    name = "fake:model"
    supports_vision = True

    def __init__(self, candidates=None, raise_error=False):
        self.candidates = candidates or []
        self.raise_error = raise_error
        self.locator_reqs = []
        self.explain_reqs = []
        self.read_reqs = []

    def propose_locator(self, req):
        self.locator_reqs.append(req)
        if self.raise_error:
            raise AiError("boom", provider="fake", status=500)
        return LocatorProposal(candidates=self.candidates, confidence=0.9)

    def explain_error(self, req):
        self.explain_reqs.append(req)
        return Explanation("giải thích", "layout_changed", "làm gì đó")

    def read_fields(self, req):
        self.read_reqs.append(req)
        return ReadFieldsResult({"early_ship_date": "13-MAR-26", "late_ship_date": "09-MAR-26"}, 0.8)


def _healer(advisor, store, max_calls=8, vision=True):
    res = SelectorResolver(store, logging.getLogger("t"))
    return Healer(advisor, store, res, max_calls, vision, lambda e: None, logging.getLogger("t")), res


def _break(store, key):
    store._bundled[key]["candidates"] = [{"kind": "css", "css": "#totally-broken"}]


def test_heal_learns_candidate(session, selectors_store, tmp_path):
    session.goto("gateway/inbox.do")
    key = "inbox.search_button"
    _break(selectors_store, key)
    adv = FakeAdvisor([{"kind": "css", "css": "#nonexistent"}, {"kind": "css", "css": "form[name='filterinbox'] input[type=submit]"}])
    healer, res = _healer(adv, selectors_store)
    with pytest.raises(ElementNotFoundError) as ei:
        res.resolve(session.page, key, timeout_ms=300)
    snap = capture(session, tmp_path, "heal")
    loc = healer.heal_locator(session.page, key, {}, snap)
    assert loc is not None and healer.calls_used == 1
    req = adv.locator_reqs[0]
    assert req.key == key and req.description and req.screenshot_jpeg and "totally-broken" in req.tried[0]
    # learned candidate is first now and resolves
    cand = selectors_store.candidates(key)[0]
    assert cand.source == "ai" and "filterinbox" in cand.css
    assert res.resolve(session.page, key, timeout_ms=500)[1].source == "ai"
    assert selectors_store.learned_path.exists()


def test_heal_budget_and_no_advisor(session, selectors_store, tmp_path):
    session.goto("gateway/inbox.do")
    snap = capture(session, tmp_path, "b", with_image=False)
    good = [{"kind": "css", "css": "input[name='documentID']"}]
    healer, _ = _healer(FakeAdvisor(good), selectors_store, max_calls=1, vision=False)
    assert healer.heal_locator(session.page, "inbox.document_id_input", {}, snap) is not None
    assert healer.can_call() is False
    assert healer.heal_locator(session.page, "inbox.document_id_input", {}, snap) is None
    assert healer.explain("S1", "t", ValueError("x"), snap) is None
    none_healer, _ = _healer(None, selectors_store)
    assert none_healer.can_call() is False and none_healer.heal_locator(session.page, "k", {}, snap) is None


def test_heal_vision_off_sends_no_image_and_ai_error_swallowed(session, selectors_store, tmp_path):
    session.goto("gateway/inbox.do")
    snap = capture(session, tmp_path, "v")
    adv = FakeAdvisor([{"kind": "css", "css": "#zzz"}])
    healer, _ = _healer(adv, selectors_store, vision=False)
    assert healer.heal_locator(session.page, "inbox.search_button", {}, snap) is None   # candidate not visible
    assert adv.locator_reqs[0].screenshot_jpeg is None
    err_healer, _ = _healer(FakeAdvisor(raise_error=True), selectors_store)
    assert err_healer.heal_locator(session.page, "inbox.search_button", {}, snap) is None
    assert err_healer.calls_used == 1


def test_explain_and_read_dates(session, selectors_store, tmp_path):
    session.goto("gateway/inbox.do")
    snap = capture(session, tmp_path, "e")
    adv = FakeAdvisor()
    healer, _ = _healer(adv, selectors_store)
    ex = healer.explain("S1.inbox_search", "Tìm PO", RuntimeError("bad"), snap)
    assert ex is not None and ex.likely_cause == "layout_changed" and adv.explain_reqs[0].error_text == "bad"
    w = healer.read_dates(snap)
    assert w is not None and (w.early, w.late) == (date(2026, 3, 9), date(2026, 3, 13))   # swapped into order
    assert adv.read_reqs[0].fields == ["early_ship_date", "late_ship_date"]
    no_vis, _ = _healer(adv, selectors_store, vision=False)
    assert no_vis.read_dates(snap) is None


def test_snapshot_redaction_and_files(session, tmp_path):
    session.page.set_content("""<h1>T</h1><input type=password name=pw value="supersecret"><p>mail bob@example.com here</p>
        <button id=b1>Go</button><input type=text name=q value="hello">""")
    snap = capture(session, tmp_path, "tag/with:odd chars")
    assert isinstance(snap, PageSnapshot)
    assert "supersecret" not in snap.dom and "bob@example.com" not in snap.dom + snap.aria
    assert '<button id="b1"' in snap.dom and 'name="q"' in snap.dom
    assert snap.screenshot_jpeg[:2] == b"\xff\xd8"
    from pathlib import Path
    assert Path(snap.screenshot_path).exists() and "shots" in snap.screenshot_path


def test_heal_rejects_guarded_elements(session, selectors_store, tmp_path):
    """An AI proposal that resolves to Submit ASN / Cancel / Clear / Validate / a password box is never learned."""
    session.page.set_content("""<form>
        <input type=button name=btnSubmitASN value="Submit ASN"><input type=button id=cancelShipment value="Cancel">
        <input type=button name=btnCancel value="Clear Values"><input type=button name=validateShipment value="Validate">
        <input type=password id=pw><input type=button id=realsave value="Save"></form>""")
    snap = capture(session, tmp_path, "g", with_image=False)
    bad = [{"kind": "css", "css": "[name=btnSubmitASN]"}, {"kind": "css", "css": "#cancelShipment"},
           {"kind": "css", "css": "[name=btnCancel]"}]
    healer, _ = _healer(FakeAdvisor(bad), selectors_store)
    assert healer.heal_locator(session.page, "ship.save_button", {}, snap) is None
    assert all(c.source == "bundled" for c in selectors_store.candidates("ship.save_button"))
    healer, _ = _healer(FakeAdvisor([{"kind": "css", "css": "[name=validateShipment]"}, {"kind": "css", "css": "#pw"}]),
                        selectors_store)
    assert healer.heal_locator(session.page, "ship.shipping_date", {}, snap) is None
    assert all(c.source == "bundled" for c in selectors_store.candidates("ship.shipping_date"))
    # a harmless proposal is still accepted (the guard is specific, not a blanket refusal)
    healer, _ = _healer(FakeAdvisor([{"kind": "css", "css": "#realsave"}]), selectors_store)
    assert healer.heal_locator(session.page, "ship.save_button", {}, snap) is not None
