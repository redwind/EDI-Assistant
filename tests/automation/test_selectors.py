"""Selector YAML validity, store merge order and resolver fallback."""
from __future__ import annotations

import logging

import pytest
import yaml

from edi_assistant.automation.selectors import (SelectorCandidate, SelectorResolver, SelectorStore, extract_row_key)
from edi_assistant.core import paths
from edi_assistant.core.errors import ElementNotFoundError

EXPECTED_KEYS = [
    "login.password_input", "login.profile_vendor_link", "login.edi_gateway_button", "nav.inbox_tab",
    "nav.shipments_tab", "inbox.document_id_input", "inbox.search_button", "inbox.results_table",
    "inbox.result_row", "inbox.result_row_active", "inbox.result_link", "inbox.row_status_cell",
    "po.page_marker", "po.create_new_shipment_link", "po.pdf_embed", "po.return_to_list_link", "ship.form",
    "ship.web_shipment_id", "ship.asn_shipment_id", "ship.radio_with_cartons", "ship.shipping_type",
    "ship.shipping_date", "ship.transportation_method", "ship.scac_code", "ship.carrier",
    "ship.bill_of_lading", "ship.pro_number", "ship.from_site_no", "ship.from_name", "ship.from_address1",
    "ship.from_address2", "ship.from_city", "ship.from_state", "ship.from_zip", "ship.from_country",
    "ship.from_country_more_link", "ship.to_site_no", "ship.to_address1", "ship.save_button",
    "ship.selected_pos_button", "ship.submit_asn_button", "ship.error_text", "pos.form", "pos.tab_selected",
    "pos.tab_search", "pos.search_po_input", "pos.search_button", "pos.search_row",
    "pos.search_row_checkbox", "pos.add_selected_button", "pos.selected_row", "pos.row_status_text",
    "pos.row_complete_partial_select", "pos.row_packaging_select", "pos.row_save_button",
    "pos.row_create_carton_button", "pos.view_detail_button", "pos.back_to_header_button",
    "pos.validate_button", "pos.page_marker", "carton.page_marker", "carton.carton_name_input",
    "carton.packaging_code_select", "carton.tab_items_search", "carton.tab_items_selected",
    "carton.items_section", "carton.items_search_row", "carton.items_add_selected", "carton.item_po_row",
    "carton.item_qty_per_carton_input", "carton.item_qty_ordered_cell", "carton.item_um_cell",
    "carton.item_prepack_row", "carton.tab_sites_search", "carton.sites_search_row",
    "carton.sites_add_selected", "carton.site_row", "carton.site_cartons_per_site_input",
    "carton.save_button", "carton.back_to_po_button", "weight.form", "weight.orderperpage_select",
    "weight.row", "weight.row_weight_input", "weight.row_um_select", "weight.save_button",
    "weight.back_button",

]


def test_yaml_validates_and_has_exact_keys(selectors_store):
    assert selectors_store.validate() == []
    assert [k.key for k in selectors_store.keys()] == EXPECTED_KEYS
    raw = yaml.safe_load(paths.bundled_selectors_path().read_text(encoding="utf-8"))
    assert set(raw["keys"]) == set(EXPECTED_KEYS)
    assert all(k.candidates for k in selectors_store.keys())


def test_unverified_flags(selectors_store):
    assert selectors_store.get("inbox.document_id_input").verified is True
    assert selectors_store.get("carton.save_button").verified is False
    assert selectors_store.get("po.create_new_shipment_link").verified is False


def test_validate_detects_bad_placeholder(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("version: 1\nkeys:\n  a.b: {page: x, verified: true, description: d, candidates: [{kind: css, css: '#{nope}'}, {kind: zzz, css: x}]}\n")
    st = SelectorStore(f, tmp_path / "l.yaml")
    st.load()
    errs = st.validate()
    assert any("nope" in e for e in errs) and any("unknown kind" in e for e in errs)


def test_merge_order_learned_first(selectors_store):
    key = "inbox.search_button"
    bundled = [c.describe() for c in selectors_store.candidates(key)]
    c1 = SelectorCandidate(kind="css", css="#first")
    c2 = SelectorCandidate(kind="css", css="#second")
    selectors_store.add_learned(key, c1, "learned")
    selectors_store.add_learned(key, c2, "learned")
    got = [c.describe() for c in selectors_store.candidates(key)]
    assert got[:2] == ["css=#second", "css=#first"] and got[2:] == bundled
    assert selectors_store.candidates(key)[0].source == "learned"
    selectors_store.mark_verified("carton.save_button")
    assert selectors_store.get("carton.save_button").verified is True
    # persisted file reloads identically; bundled is not modified
    st2 = SelectorStore(selectors_store.bundled_path, selectors_store.learned_path)
    st2.load()
    assert [c.describe() for c in st2.candidates(key)] == got
    assert st2.get("carton.save_button").verified is True
    selectors_store.remove_learned(key, "css=#second")
    assert selectors_store.candidates(key)[0].describe() == "css=#first"


def test_dedupe_by_describe(selectors_store):
    key = "ship.save_button"
    dup = selectors_store.candidates(key)[0]
    selectors_store.add_learned(key, SelectorCandidate.from_dict(dup.to_dict()), "learned")
    descs = [c.describe() for c in selectors_store.candidates(key)]
    assert len(descs) == len(set(descs))


@pytest.fixture
def static_page(session):
    p = session.page
    p.set_content("""
      <form name=f><input id=a name=a value=1><input name=a2 value=2></form>
      <table><tr id=r1><td><a>111</a></td><td><select name="complete_shipment_77"><option>Complete</option></select></td></tr>
             <tr><td><a>222</a></td><td><select name="complete_shipment_88"><option>Complete</option></select></td></tr></table>
      <button>Go</button><button style="display:none">Hidden</button><label for=x>Name Label</label><input id=x>
    """)
    return p


def _store_with(tmp_path, cands):
    f = tmp_path / "s.yaml"
    f.write_text(yaml.safe_dump({"version": 1, "keys": {"k.one": {"page": "x", "verified": True, "description": "d",
                                                                    "candidates": cands}}}))
    st = SelectorStore(f, tmp_path / "l.yaml")
    st.load()
    return st


def test_resolver_fallback_order(static_page, tmp_path):
    st = _store_with(tmp_path, [{"kind": "css", "css": "#does-not-exist"}, {"kind": "role", "role": "button", "name": "Go"},
                                {"kind": "css", "css": "#a"}])
    res = SelectorResolver(st, logging.getLogger("t"))
    loc, cand = res.resolve(static_page, "k.one", timeout_ms=1500)
    assert cand.describe() == "role=button[name='Go']"
    # learned candidate wins
    st.add_learned("k.one", SelectorCandidate(kind="css", css="#a"), "learned")
    loc, cand = res.resolve(static_page, "k.one", timeout_ms=1500)
    assert cand.source == "learned" and loc.get_attribute("name") == "a"


def test_resolver_not_found_lists_tried(static_page, tmp_path):
    st = _store_with(tmp_path, [{"kind": "css", "css": "#nope1"}, {"kind": "text", "text": "nothing here"}])
    res = SelectorResolver(st, logging.getLogger("t"))
    with pytest.raises(ElementNotFoundError) as ei:
        res.resolve(static_page, "k.one", timeout_ms=600)
    assert ei.value.ctx["key"] == "k.one" and len(ei.value.ctx["tried"]) == 2
    assert res.exists(static_page, "k.one", timeout_ms=300) is False


def test_resolver_label_nth_vars_and_hidden(static_page, tmp_path):
    st = _store_with(tmp_path, [{"kind": "label", "text": "Name Label"}])
    res = SelectorResolver(st, logging.getLogger("t"))
    assert res.resolve(static_page, "k.one")[0].get_attribute("id") == "x"
    st2 = _store_with(tmp_path, [{"kind": "xpath", "xpath": "//tr[.//a[normalize-space()='{po}']]"}])
    res2 = SelectorResolver(st2, logging.getLogger("t"))
    loc, _ = res2.resolve(static_page, "k.one", {"po": "222"})
    assert "222" in loc.inner_text()
    # missing var -> candidate skipped -> not found
    with pytest.raises(ElementNotFoundError):
        res2.resolve(static_page, "k.one", {}, timeout_ms=300)
    st3 = _store_with(tmp_path, [{"kind": "css", "css": "button", "nth": -1}])
    res3 = SelectorResolver(st3, logging.getLogger("t"))
    with pytest.raises(ElementNotFoundError):   # last button is hidden -> require_visible fails
        res3.resolve(static_page, "k.one", timeout_ms=300)
    assert res3.resolve(static_page, "k.one", require_visible=False)[0].inner_text() == "Hidden"


def test_extract_row_key(static_page):
    row = static_page.locator("tr#r1")
    assert extract_row_key(row, "pos") == "77"
    with pytest.raises(ElementNotFoundError):
        extract_row_key(row, "weight")


class _FakeLocator:
    """count() raises PlaywrightError for the first `unstable_sweeps` calls (page navigating), then finds 1 element."""

    def __init__(self, state):
        self.state = state

    def count(self):
        self.state["calls"] += 1
        if self.state["calls"] <= self.state["unstable_sweeps"]:
            from playwright.sync_api import Error as PlaywrightError
            raise PlaywrightError("Execution context was destroyed, most likely because of a navigation")
        return 1 if self.state["present"] else 0

    @property
    def first(self):
        return self

    def is_visible(self):
        return True


class _FakePage:
    def __init__(self, state):
        self.state = state
        self.waited_ms = 0

    def locator(self, css):
        return _FakeLocator(self.state)

    def wait_for_timeout(self, ms):
        import time
        self.waited_ms += ms
        time.sleep(ms / 1000)   # real wait: the resolver's deadline is wall-clock


def test_probe_keeps_polling_while_page_unstable(tmp_path):
    """§12: a probe (timeout <= PROBE_MS) may conclude 'absent' only from a CLEAN sweep. A sweep disturbed by a
    navigation keeps polling until the deadline, so a post-Save error check never reads 'page in flux' as 'no error'."""
    st = _store_with(tmp_path, [{"kind": "css", "css": ".error"}])
    res = SelectorResolver(st, logging.getLogger("t"))
    # element present, but the first sweep hits a navigation error -> must still be found within the budget
    state = {"calls": 0, "unstable_sweeps": 1, "present": True}
    page = _FakePage(state)
    loc, _ = res.resolve(page, "k.one", timeout_ms=300)
    assert loc is not None and state["calls"] == 2 and page.waited_ms > 0
    # clean miss: exactly one sweep, no sleeping (the perf fix of §10 is preserved)
    state = {"calls": 0, "unstable_sweeps": 0, "present": False}
    page = _FakePage(state)
    with pytest.raises(ElementNotFoundError):
        res.resolve(page, "k.one", timeout_ms=300)
    assert state["calls"] == 1 and page.waited_ms == 0
    # permanently unstable: gives up at the deadline (bounded), never hangs
    state = {"calls": 0, "unstable_sweeps": 10_000, "present": True}
    page = _FakePage(state)
    with pytest.raises(ElementNotFoundError):
        res.resolve(page, "k.one", timeout_ms=200)
    assert state["calls"] >= 2
