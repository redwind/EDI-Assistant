"""Human-pace mode: delays, typing verification, throttling, block detection."""
from __future__ import annotations

import logging
import random
import threading
import time
from types import SimpleNamespace

import pytest

from edi_assistant.automation import pace as pace_mod
from edi_assistant.automation.actions import SafeActions
from edi_assistant.automation.flow import steps as S
from edi_assistant.automation.pace import Pacer, as_range
from edi_assistant.automation.selectors import SelectorResolver, SelectorStore
from edi_assistant.core import paths
from edi_assistant.core.config import AppConfig, FlowConfig, PaceConfig, config_from_dict, config_to_dict
from edi_assistant.core.errors import PostconditionFailed, SiteBlockedError, UserAbortError
from edi_assistant.mock_edi import MockOptions, MockServer

from test_e2e_mock import Harness
from wpb_helpers import make_line, make_plan


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.waits: list[int] = []

    def now(self) -> float:
        return self.t

    def wait(self, ms: int) -> None:
        self.waits.append(ms)
        self.t += ms / 1000


def _pacer(cfg=None, **kw):
    clk = FakeClock()
    p = Pacer(cfg or PaceConfig(), kw.pop("abort", None), wait=clk.wait, clock=clk.now, rng=random.Random(1), **kw)
    return p, clk


# ------------------------------------------------------------------ config
def test_pace_defaults_and_backward_compat():
    c = AppConfig()
    assert c.pace.enabled is True
    assert c.pace.action_delay_ms == [400, 1200] and c.pace.nav_delay_ms == [1000, 2000]
    assert c.pace.type_delay_ms == [30, 80] and c.pace.max_shipments_per_hour == 0
    assert c.pace.between_shipments_s == [20, 60]
    assert c.ui.language == "en"
    old = config_from_dict({"version": 1, "browser": {"slow_mo_ms": 5}})   # config file written before pace existed
    assert old.pace == PaceConfig() and old.browser.slow_mo_ms == 5
    rt = config_from_dict(config_to_dict(AppConfig()))
    assert rt == AppConfig()


def test_as_range_coercion():
    assert as_range([5, 2], (1, 1)) == (2, 5)
    assert as_range([-3, 4], (1, 1)) == (0, 4)
    assert as_range(7, (1, 1)) == (7, 7)
    assert as_range("junk", (1, 2)) == (1, 2)
    assert as_range([], (1, 2)) == (1, 2)


# ------------------------------------------------------------------ delays
def test_action_and_navigation_delays_applied_within_range():
    cfg = PaceConfig(action_delay_ms=[400, 1200], nav_delay_ms=[1000, 2000])
    p, clk = _pacer(cfg)
    t0 = clk.now()
    p.sleep_action()
    assert 0.4 <= clk.now() - t0 <= 1.3
    t1 = clk.now()
    p.after_navigation()
    assert 1.0 <= clk.now() - t1 <= 2.3
    assert all(w <= pace_mod.SLICE_MS for w in clk.waits)   # sliced -> interruptible


def test_disabled_pacer_does_nothing():
    p, clk = _pacer(PaceConfig(enabled=False))
    p.sleep_action()
    p.after_navigation()
    p.before_shipment(3)
    assert clk.waits == [] and p.history == []


def test_sleep_interruptible_by_abort():
    ev = threading.Event()
    p, clk = _pacer(abort=ev)
    ev.set()
    with pytest.raises(UserAbortError):
        p.sleep_ms(5000)
    assert clk.waits == []
    ev.clear()
    calls = []

    def wait(ms):
        calls.append(ms)
        if len(calls) == 2:
            ev.set()

    p2 = Pacer(PaceConfig(), ev, wait=wait, clock=clk.now)
    with pytest.raises(UserAbortError):
        p2.sleep_ms(60_000)
    assert len(calls) == 2   # stopped within a slice of the abort, not after 60 s


def test_real_sleep_interrupted_by_abort_quickly(session):
    ev = threading.Event()
    p = Pacer(PaceConfig(), ev, wait=session.wait)
    threading.Timer(0.3, ev.set).start()
    t0 = time.monotonic()
    with pytest.raises(UserAbortError):
        p.sleep_ms(10_000)
    assert time.monotonic() - t0 < 2


# ------------------------------------------------------------------ throttling (fake clock)
def test_between_shipments_pause():
    p, clk = _pacer(PaceConfig(between_shipments_s=[20, 60]))
    p.before_shipment(0)
    assert clk.waits == []                 # no pause before the first shipment
    t0 = clk.now()
    p.before_shipment(1)
    assert 20 <= clk.now() - t0 <= 61


def test_max_shipments_per_hour():
    hist: list[float] = []
    p, clk = _pacer(PaceConfig(between_shipments_s=[0, 0], max_shipments_per_hour=2), history=hist)
    msgs = []
    p._log = msgs.append
    p.before_shipment(0)
    clk.t += 10
    p.before_shipment(1)
    assert len(hist) == 2 and not msgs
    t0 = clk.now()
    p.before_shipment(2)                   # third within the hour -> waits until the first one is > 1 h old
    assert clk.now() - t0 >= 3600 - 10
    assert any("hourly limit" in m for m in msgs)
    assert len(hist) == 2                  # oldest expired, new one recorded


def test_zero_max_per_hour_is_unlimited():
    p, clk = _pacer(PaceConfig(between_shipments_s=[0, 0], max_shipments_per_hour=0))
    for i in range(10):
        p.before_shipment(i)
    assert clk.waits == []


# ------------------------------------------------------------------ typing / select verification
HTML = """
<input id=txt>
<input id=nz onkeydown="if(event.key==='z') event.preventDefault()">
<input id=bad oninput="this.value=this.value.replace(/q/g,'')">
<select id=sel onchange="document.title='changed:'+this.value"><option value="a">Alpha</option><option value="b">Beta</option></select>
<button id=btn onclick="document.title='clicked'">Go</button>
"""


@pytest.fixture
def pacing(session):
    session.page.set_content(HTML)
    st = SelectorStore(paths.bundled_selectors_path(), paths.learned_selectors_path())
    st.load()
    ev = threading.Event()
    cfg = PaceConfig(action_delay_ms=[5, 10], nav_delay_ms=[5, 10], type_delay_ms=[1, 3])
    pacer = Pacer(cfg, ev, wait=session.wait)
    session.pacer = pacer
    acts = SafeActions(session, SelectorResolver(st, logging.getLogger("t")), ev, lambda e: None,
                       logging.getLogger("t"), FlowConfig())
    return acts, session, pacer


def test_typing_clears_first_and_verifies(pacing):
    acts, session, pacer = pacing
    loc = session.page.locator("#txt")
    loc.fill("old value")
    acts.fill_locator(loc, "12345678901234567890")   # longer than one typing chunk
    assert loc.input_value() == "12345678901234567890"
    assert pacer.slept_ms > 0


def test_typing_mismatch_retries_with_fill(pacing):
    acts, session, _ = pacing
    loc = session.page.locator("#nz")
    acts.fill_locator(loc, "azb")          # typing drops 'z' (keydown blocked) -> mismatch -> fill() fallback
    assert loc.input_value() == "azb"


def test_typing_unacceptable_value_raises(pacing):
    acts, session, _ = pacing
    with pytest.raises(PostconditionFailed):
        acts.fill_locator(session.page.locator("#bad"), "aqb")   # field itself rejects 'q', even with fill()


def test_select_readback_and_click_delay(pacing):
    acts, session, pacer = pacing
    assert acts.select_locator(session.page.locator("#sel"), value="b") == "Beta"
    assert session.page.title() == "changed:b"
    before = pacer.slept_ms
    acts.click_locator(session.page.locator("#btn"))
    assert pacer.slept_ms > before and session.page.title() == "clicked"


def test_pace_disabled_uses_plain_fill(session):
    session.page.set_content(HTML)
    st = SelectorStore(paths.bundled_selectors_path(), paths.learned_selectors_path())
    st.load()
    session.pacer = None
    acts = SafeActions(session, SelectorResolver(st, logging.getLogger("t")), threading.Event(), lambda e: None,
                       logging.getLogger("t"), FlowConfig())
    acts.fill_locator(session.page.locator("#nz"), "azb")
    assert session.page.locator("#nz").input_value() == "azb"


# ------------------------------------------------------------------ whole flow with pacing on / block detection
def _tiny_pace(**over):
    return dict(pace__enabled=True, pace__action_delay_ms=[1, 3], pace__nav_delay_ms=[1, 3],
                pace__type_delay_ms=[1, 2], pace__between_shipments_s=[0, 0], **over)


@pytest.mark.e2e
def test_full_flow_with_pace_enabled(mock_server, make_session, selectors_store):
    plan = make_plan([make_line("580367401")])
    h = Harness(mock_server, make_session, selectors_store, plan, **_tiny_pace())
    res = h.run()
    assert res.status == "done", res.error
    assert h.unexpected == [] and mock_server.state.submit_attempts == 0
    assert h.ctx.pacer.slept_ms > 0
    hdr = next(iter(mock_server.state.shipments.values())).header
    assert hdr["txtFromName"] == "SUMEC TEXTILE COMPANY LIMITED" and hdr["txtShippingDate"]


def _blocked_server(mode):
    srv = MockServer(MockOptions(port=0, require_login=False, block_after_n_requests=3, block_mode=mode))
    srv.start()
    return srv


@pytest.mark.e2e
@pytest.mark.parametrize("mode", ["429", "access_denied"])
def test_block_detection_stops_run_and_asks_user(mode, make_session, selectors_store):
    srv = _blocked_server(mode)
    try:
        plan = make_plan([make_line("580367401")])
        h = Harness(srv, make_session, selectors_store, plan, script={"site_blocked": "abort"})
        res = h.run()
        assert res.status == "aborted"
        blocked = [e for e in h.asked if e.kind == "site_blocked"]
        assert len(blocked) == 1                       # asked once, never auto-retried
        assert blocked[0].options == ["continue", "abort"]
        assert "blocking" in blocked[0].message_vi
        assert srv.state.submit_attempts == 0
        assert srv.state.shipments == {}               # nothing was created after the block
    finally:
        srv.stop()


@pytest.mark.e2e
def test_login_bounces_more_than_twice_is_a_block(mock_server, make_session, selectors_store, monkeypatch):
    plan = make_plan([make_line("580367401")])
    h = Harness(mock_server, make_session, selectors_store, plan, script={"site_blocked": "abort"})

    class Boom(S.Step):
        id = "X.boom"
        title_vi = "boom"

        def act(self, ctx):
            raise PostconditionFailed("nope", step_id=self.id)

        def check(self, ctx):
            return True

    monkeypatch.setattr(h.session, "is_login_page", lambda: True)
    monkeypatch.setattr(S.S0EnsureLoggedIn, "act", lambda self, ctx: None)
    from edi_assistant.automation.flow import FlowRunner
    with pytest.raises(UserAbortError):
        FlowRunner(h.ctx).run_step(Boom())
    assert h.ctx.login_bounces == 3
    assert [e.kind for e in h.asked] == ["site_blocked"]


def test_check_blocked_unit(session):
    session.page.set_content("<title>ok</title><body>hello</body>")
    session.check_blocked(scan_page=True)
    for text in ("Access Denied", "403 Forbidden", "Too Many Requests", "Please solve the CAPTCHA",
                 "unusual traffic from your network", "Verify you are human"):
        session.page.set_content(f"<title>x</title><body>{text}</body>")
        with pytest.raises(SiteBlockedError):
            session.check_blocked(scan_page=True)
    session.block_reason = "HTTP 429 from x"
    with pytest.raises(SiteBlockedError):
        session.check_blocked()
