"""Selectors against the real 'Search Purchase Orders' page (trimmed capture, Nov 2026).

Regression: the page nests layout tables, so a row xpath must pick the innermost <tr>; otherwise the
first checkbox of the whole table (another PO) was ticked."""
from __future__ import annotations

import logging

from edi_assistant.automation.selectors import SelectorResolver

from realdata import real_file


def test_search_page_selectors(session, selectors_store):
    page = session.page
    page.set_content(real_file("search_po_real.html").read_text(encoding="utf-8"))
    r = SelectorResolver(selectors_store, logging.getLogger("t"))
    v = {"po": "672346001"}
    for key in ("pos.tab_selected", "pos.tab_search", "pos.search_po_input", "pos.search_button",
                "pos.add_selected_button", "pos.page_marker"):
        r.resolve(page, key, v, timeout_ms=300)
    assert r.resolve(page, "pos.search_po_input", v, 300)[0].get_attribute("name") == "PO_NO"
    row, _ = r.resolve(page, "pos.search_row", v, timeout_ms=300)
    assert row.locator("input[type='checkbox']").count() == 1
    assert row.locator("input[type='checkbox']").get_attribute("name") == "CB_31350729"   # PO 672346001, not row 1
