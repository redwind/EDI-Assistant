from decimal import Decimal as Dc

from edi_assistant.core.models import POLine
from edi_assistant.core.quantities import check_ordered, compute_carton_plan, weight_for_line


def test_carton():
    p = compute_carton_plan(Dc(1002), Dc(167), 6)
    assert (p.qty_per_carton, p.cartons_per_site, p.flags) == (1, 167, [])
    p = compute_carton_plan(Dc(1002), Dc(167), None)
    assert (p.qty_per_carton, p.cartons_per_site) == (6, 167)
    p = compute_carton_plan(Dc(500), Dc(85), None)
    assert p.flags[0].code == "non_integer_units" and p.flags[0].severity == "error" and p.qty_per_carton == 0
    p = compute_carton_plan(Dc(510), Dc(85), 4)
    assert p.flags[0].code == "non_integer_prepack"
    assert compute_carton_plan(Dc(510), Dc(0), None).cartons_per_site == 0
    assert compute_carton_plan(Dc(510), Dc("85.5"), None).flags[0].code == "non_integer_units"
    p = compute_carton_plan(Dc(510), Dc(85), 6)
    assert p.qty_per_carton == 1 and p.cartons_per_site == 85


def test_check_ordered():
    assert check_ordered(Dc(1), None, "", None) == []
    assert check_ordered(Dc(1002), Dc(167), "AS", 6) == []
    assert check_ordered(Dc(1002), Dc(1002), "EA", None) == []
    assert check_ordered(Dc(1100), Dc(1002), "EA", None)[0].code == "qty_over_ordered"
    assert check_ordered(Dc(900), Dc(167), "AS", 6)[0].code == "qty_under_ordered"


def test_weight():
    ln = POLine("5803674", 1, 5, packages=Dc(85), quantity=Dc(510), gross_weight=Dc("1020"))
    assert weight_for_line(ln, "total_gw") == Dc("1020.00")
    assert weight_for_line(ln, "per_carton_gw") == Dc("12.00")
    ln.packages = Dc(0)
    assert weight_for_line(ln, "per_carton_gw") == Dc("1020.00")
    ln.packages, ln.gross_weight = Dc(3), Dc(10)
    assert weight_for_line(ln, "per_carton_gw") == Dc("3.33")


def test_decide_carton_rules():
    from edi_assistant.core.quantities import carton_matches_web, decide_carton
    D = Dc
    p = decide_carton(D(1428), D(238), D(1428), "EA", None)
    assert (p.qty_per_carton, p.cartons_per_site, p.web_rule) == (6, 238, "units")
    p = decide_carton(D(1428), D(238), D(238), "EA", None)
    assert (p.qty_per_carton, p.cartons_per_site, p.web_rule) == (1, 238, "packs")
    assert any(f.code == "web_counts_packs" for f in p.flags) and carton_matches_web(p, D(238))
    p = decide_carton(D(948), D(158), D(158), "AS", 6)
    assert (p.qty_per_carton, p.cartons_per_site, p.web_rule) == (1, 158, "prepack")
    p = decide_carton(D(1428), D(238), D(1400), "EA", None)
    codes = {f.code for f in p.flags}
    assert p.web_rule == "mismatch" and {"qty_over_ordered", "qty_mismatch_web"} <= codes
    assert not carton_matches_web(p, D(1400))
    p = decide_carton(D(1428), D(238), None, "", None)
    assert p.web_rule == "unknown" and not carton_matches_web(p, None)
    p = decide_carton(D(1002), D(167), D(167), "AS", 6)
    assert (p.qty_per_carton, p.cartons_per_site, p.web_rule) == (1, 167, "prepack")
    p = decide_carton(D(1000), D(3), D(1000), "EA", None)       # non-integer math keeps the error path
    assert p.web_rule == "mismatch" and any(f.code == "non_integer_units" for f in p.flags)


def test_weight_per_carton_as_is():
    from edi_assistant.core.models import POLine
    from edi_assistant.core.quantities import weight_for_line
    ln = POLine("5820678", 1, 2, packages=Dc(238), quantity=Dc(1428), gross_weight=Dc("12"))
    assert str(weight_for_line(ln, "per_carton_as_is")) == "12.00"
