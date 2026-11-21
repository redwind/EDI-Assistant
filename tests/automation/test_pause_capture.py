"""Every pause for the user is logged and leaves a screenshot + page HTML in the run folder."""
from __future__ import annotations

import logging
from types import SimpleNamespace

from edi_assistant.automation import dom_snapshot
from edi_assistant.automation.flow.context import FlowContext
from edi_assistant.core.events import UserResponse


class _Page:
    url, content_html = "https://edi.example/x", "<html><body>Search Purchase Orders a@b.com</body></html>"

    def title(self):
        return "t"

    def locator(self, _):
        return SimpleNamespace(aria_snapshot=lambda: "aria")

    def evaluate(self, _):
        return "<dom>"

    def content(self):
        return self.content_html


def _ctx(tmp_path, caplog):
    sess = SimpleNamespace(page=_Page(), screenshot_jpeg=lambda p: (p.parent.mkdir(parents=True, exist_ok=True),
                                                                     p.write_bytes(b"jpg"), b"jpg")[2])
    seen = []
    ctx = FlowContext.__new__(FlowContext)
    ctx.session, ctx.run_dir, ctx.log = sess, tmp_path, logging.getLogger("t.flow")
    ctx.ask_user = lambda ev: (seen.append(ev), UserResponse(request_id=ev.request_id, action="continue"))[1]
    return ctx, seen


def test_ask_saves_screenshot_html_and_logs(tmp_path, caplog):
    ctx, seen = _ctx(tmp_path, caplog)
    with caplog.at_level(logging.WARNING, "t.flow"):
        ctx.ask("to_site_missing", "Pick the DC", options=["continue", "abort"], step_id="S6.fill_header_save")
    shots = sorted(p.name for p in (tmp_path / "shots").iterdir())
    assert [n.rsplit(".", 1)[1] for n in shots] == ["html", "jpg"]
    assert all("S6.fill_header_save" in n for n in shots)        # dotted step id kept whole
    html = next((tmp_path / "shots").glob("*.html")).read_text()
    assert "Search Purchase Orders" in html and "a@b.com" not in html
    assert seen[0].screenshot_path.endswith("S6.fill_header_save.jpg")
    assert "waiting for user [to_site_missing] at S6.fill_header_save: Pick the DC" in caplog.text


def test_ask_keeps_callers_screenshot(tmp_path, caplog, monkeypatch):
    ctx, seen = _ctx(tmp_path, caplog)
    calls = []
    monkeypatch.setattr("edi_assistant.automation.flow.context.capture", lambda *a, **k: calls.append(a))
    ctx.ask("step_failed", "boom", screenshot_path="given.jpg")
    assert not calls and seen[0].screenshot_path == "given.jpg"
    assert dom_snapshot.capture   # module import sanity


class _Dlg:
    def __init__(self, typ, msg):
        self.type, self.message, self.done = typ, msg, None

    def accept(self):
        self.done = "accept"

    def dismiss(self):
        self.done = "dismiss"


def test_popups_are_left_to_the_user_while_paused(tmp_path, caplog):
    """Pressing Save by hand during a pause raises the site's confirm: it must stay open for the user,
    not be cancelled by the tool (that is what made a manual Save 'do nothing')."""
    from edi_assistant.automation.dialogs import DialogPolicy
    ctx, _ = _ctx(tmp_path, caplog)
    ctx.dialogs = DialogPolicy(logging.getLogger("t"), lambda e: None)
    seen = []

    def user_clicks_save(ev):
        d = _Dlg("confirm", "Do you want to save the changes made on this page?")
        ctx.dialogs._handle(d)
        seen.append(d.done)
        return UserResponse(request_id=ev.request_id, action="continue")
    ctx.ask_user = user_clicks_save
    ctx.ask("step_failed", "fix it", step_id="S9.enter_weights")
    assert seen == [None] and ctx.dialogs.manual is False
    d = _Dlg("confirm", "Do you want to save the changes made on this page?")
    ctx.dialogs._handle(d)          # outside a pause the policy applies again (unexpected confirm -> dismissed)
    assert d.done == "dismiss"
