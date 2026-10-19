"""Carton math and ordered-quantity cross-check."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import CartonPlan, Flag, POLine


def _is_int(d: Decimal) -> bool:
    return d == d.to_integral_value()


def compute_carton_plan(quantity: Decimal, packages: Decimal, prepack_units: int | None) -> CartonPlan:
    flags: list[Flag] = []
    if packages <= 0 or not _is_int(packages):
        flags.append(Flag("non_integer_units", f"Invalid carton count {packages}", "error"))
        return CartonPlan(Decimal(0), 0, 0, prepack_units, flags)
    units = quantity / packages
    qpc = 0
    if not _is_int(units):
        flags.append(Flag("non_integer_units",
                          f"Quantity {quantity} is not divisible by carton count {packages}", "error"))
    elif prepack_units:
        per = units / prepack_units
        if not _is_int(per):
            flags.append(Flag("non_integer_prepack",
                              f"Quantity per carton {units} is not divisible by prepack {prepack_units}", "error"))
        else:
            qpc = int(per)
    else:
        qpc = int(units)
    return CartonPlan(units, qpc, int(packages), prepack_units, flags)


def check_ordered(excel_qty: Decimal, web_ordered: Decimal | None, web_um: str,
                  prepack_units: int | None) -> list[Flag]:
    if web_ordered is None:
        return []
    ordered = web_ordered * prepack_units if prepack_units else web_ordered
    if excel_qty > ordered:
        return [Flag("qty_over_ordered", f"Excel quantity {excel_qty} is greater than quantity ordered {ordered} {web_um}".strip())]
    if excel_qty < ordered:
        return [Flag("qty_under_ordered", f"Excel quantity {excel_qty} is less than quantity ordered {ordered} {web_um}".strip(), "info")]
    return []


def weight_for_line(line: POLine, mode: str) -> Decimal:
    w = line.gross_weight
    if mode == "per_carton_as_is":
        return w.quantize(Decimal("0.01"), ROUND_HALF_UP)
    if mode == "per_carton_gw" and line.packages > 0:
        w = w / line.packages
    return w.quantize(Decimal("0.01"), ROUND_HALF_UP)


def decide_carton(quantity: Decimal, packages: Decimal, web_ordered: Decimal | None, web_um: str,
                  prepack_units: int | None) -> CartonPlan:
    """Runtime reconciliation of Excel numbers with the web 'Qty Ordered' (pure; called by S8)."""
    base = compute_carton_plan(quantity, packages, prepack_units)
    if any(f.severity == "error" for f in base.flags):
        base.web_rule = "mismatch"
        return base
    if web_ordered is None:
        base.web_rule = "unknown"
        base.flags.append(Flag("web_qty_unknown", "Could not read Qty Ordered on the carton page"))
        return base
    units_on_web = web_ordered * (prepack_units or 1)
    if units_on_web == quantity:
        base.web_rule = "prepack" if prepack_units else "units"
        return base
    if web_ordered == packages:
        base.qty_per_carton = 1
        base.cartons_per_site = int(packages)
        base.prepack_units = prepack_units or int(base.units_per_carton)
        base.web_rule = "packs"
        base.flags.append(Flag("web_counts_packs",
                               f"Qty Ordered {web_ordered} {web_um} equals the carton count; Qty Per Carton set to 1",
                               "info"))
        return base
    base.web_rule = "mismatch"
    base.flags += check_ordered(quantity, web_ordered, web_um, prepack_units)
    base.flags.append(Flag("qty_mismatch_web",
                           f"Qty Per Carton {base.qty_per_carton} x Cartons {base.cartons_per_site} "
                           f"!= Qty Ordered {web_ordered} {web_um}", "error"))
    return base


def carton_matches_web(plan: CartonPlan, web_ordered: Decimal | None) -> bool:
    """qpc x cps == web Qty Ordered (in the web's own unit). None -> False."""
    if web_ordered is None:
        return False
    return Decimal(plan.qty_per_carton * plan.cartons_per_site) == web_ordered
