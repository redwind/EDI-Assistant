"""S4: flow.past_date_policy is the single switch for a past midpoint (clamp_today default | ask)."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from edi_assistant.automation.flow import steps as S
from edi_assistant.core.config import AppConfig
from edi_assistant.core.events import UserResponse
from edi_assistant.core.models import DateWindow, FactoryAddress, ShipmentPlan

TODAY = date(2026, 10, 18)


def _ctx(policy: str, typed: str | None = None):
    cfg = AppConfig()
    cfg.flow.past_date_policy = policy
    sh = ShipmentPlan(index=1, label="x", lines=[], factory=FactoryAddress("f", "n", "a"), master_pos=["5803674"],
                      po_windows={"5803674": DateWindow(date(2026, 3, 9), date(2026, 3, 13))})
    asked = []

    def ask(kind, msg, *, options=None, input_fields=None, step_id="", **_):
        asked.append((kind, [f.key for f in input_fields or []]))
        return UserResponse("r", "continue", {"shipping_date": typed} if typed is not None else {})

    return SimpleNamespace(current_shipment=sh, today=lambda: TODAY, config=cfg, ask=ask, asked=asked)


def test_default_policy_clamps_to_today_without_prompt():
    assert AppConfig().flow.past_date_policy == "clamp_today"
    ctx = _ctx("clamp_today")
    S.S4ComputeShipDate().act(ctx)
    assert ctx.current_shipment.shipping_date == TODAY and ctx.asked == []
    assert [f.code for f in ctx.current_shipment.flags] == ["date_in_past"]


def test_ask_policy_prompts_and_accepts_typed_date():
    ctx = _ctx("ask", typed="10/25/2026")
    S.S4ComputeShipDate().act(ctx)
    assert ctx.asked == [("date_in_past", ["shipping_date"])]
    assert ctx.current_shipment.shipping_date == date(2026, 10, 25)
    ctx = _ctx("ask", typed="")          # empty / unparsable -> keep today
    S.S4ComputeShipDate().act(ctx)
    assert ctx.current_shipment.shipping_date == TODAY


def test_future_midpoint_never_prompts():
    ctx = _ctx("ask")
    ctx.current_shipment.po_windows = {"5803674": DateWindow(date(2026, 12, 1), date(2026, 12, 11))}
    S.S4ComputeShipDate().act(ctx)
    assert ctx.current_shipment.shipping_date == date(2026, 12, 6) and ctx.asked == []
