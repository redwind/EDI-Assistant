"""§12: the post-Save gate (`_after_save`) never lets a rejected or non-reloading Save pass as success."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from edi_assistant.automation.flow.steps import _after_save, _visible_text
from edi_assistant.automation.selectors import SelectorResolver
from edi_assistant.core.errors import PostconditionFailed


@pytest.fixture
def ctx(session, selectors_store):
    return SimpleNamespace(page=session.page, resolver=SelectorResolver(selectors_store, logging.getLogger("t")))


def test_error_text_found_behind_empty_first_match(ctx):
    """A hidden/empty first '.error' container must not mask the real message further down the page."""
    ctx.page.set_content("<div class='error'></div><span class='error' style='display:none'>old</span>"
                         "<table><tr><td class='errorMessage'>Quantity exceeds ordered</td></tr></table>")
    assert _visible_text(ctx, "ship.error_text") == "Quantity exceeds ordered"
    with pytest.raises(PostconditionFailed) as ei:
        _after_save(ctx, True, "carton", "S8")
    assert "exceeds" in str(ei.value) and ei.value.ctx.get("step_id") == "S8"


def test_red_marker_without_words_is_not_an_error(ctx):
    ctx.page.set_content("<form><font color='red'>*</font> Name <input name=n></form>")
    assert _visible_text(ctx, "ship.error_text") == ""
    _after_save(ctx, True, "header", "S6")   # passes


def test_no_reload_after_save_fails(ctx):
    ctx.page.set_content("<form><input name=qty value='6'></form>")
    with pytest.raises(PostconditionFailed) as ei:
        _after_save(ctx, False, "weights", "S9")
    assert "did not reload" in str(ei.value)


# ---------------------------------------------------------------- §13
def test_unicode_error_text_counts_as_words(ctx):
    ctx.page.set_content("<span class='error'>Số lượng vượt quá</span>")
    assert "vượt" in _visible_text(ctx, "ship.error_text")
    ctx.page.set_content("<span class='error'>12 * 3 -</span>")
    assert _visible_text(ctx, "ship.error_text") == ""


def _s6_ctx(ctx, monkeypatch, *, submit_present, ids_ok=True):
    from edi_assistant.automation.flow import steps
    warns = []
    ctx.current_shipment = SimpleNamespace(web_shipment_id="123456")
    ctx.actions = SimpleNamespace(exists=lambda *a, **k: submit_present)
    ctx.warn = warns.append
    monkeypatch.setattr(steps, "_capture_ids", lambda c: ids_ok)
    return steps.S6FillHeaderSave(), warns


def test_s6_check_tolerates_red_text_on_saved_shipment_page(ctx, monkeypatch):
    ctx.page.set_content("<font color='red'>Fields marked are required</font>")
    step, warns = _s6_ctx(ctx, monkeypatch, submit_present=True)
    assert step.check(ctx) is True
    assert warns and "required" in warns[0]


def test_s6_check_still_fails_without_saved_state(ctx, monkeypatch):
    ctx.page.set_content("<font color='red'>Fields marked are required</font>")
    step, _ = _s6_ctx(ctx, monkeypatch, submit_present=False)
    with pytest.raises(PostconditionFailed):
        step.check(ctx)
    step, _ = _s6_ctx(ctx, monkeypatch, submit_present=True, ids_ok=False)
    with pytest.raises(PostconditionFailed):
        step.check(ctx)



def test_no_reload_quotes_site_popups(monkeypatch):
    """A Save blocked by a JS alert/confirm must say what the site asked, not only 'did not reload'."""
    from edi_assistant.automation.dialogs import DialogPolicy
    from edi_assistant.automation.flow import steps
    monkeypatch.setattr(steps, "_settle", lambda c: None)
    monkeypatch.setattr(steps, "_visible_text", lambda c, k, v=None: "")
    pol = DialogPolicy(logging.getLogger("t"), lambda e: None)
    d = lambda typ, msg: SimpleNamespace(type=typ, message=msg)   # noqa: E731
    pol._record(d("alert", "old one"), True)
    c = SimpleNamespace(dialogs=pol)
    mark = steps._dialog_mark(c)
    pol._record(d("alert", "Shipping Date\n is invalid"), True)
    pol._record(d("confirm", "Continue anyway?"), False)
    with pytest.raises(PostconditionFailed) as ei:
        steps._after_save(c, False, "header", "S6", mark)
    m = ei.value.message_vi
    assert '"Shipping Date is invalid"' in m and '"Continue anyway?" (answered Cancel)' in m and "old one" not in m
    with pytest.raises(PostconditionFailed) as ei:
        steps._after_save(c, False, "header", "S6", steps._dialog_mark(c))
    assert "check the page in the browser" in ei.value.message_vi
