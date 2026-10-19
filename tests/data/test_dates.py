from datetime import date

from edi_assistant.core.dates import (compute_shipping_date, format_mdy, intersect, midpoint,
                                      parse_date_token, parse_ship_dates)
from edi_assistant.core.models import DateWindow

D = date


def test_tokens():
    assert parse_date_token("09-MAR-26") == D(2026, 3, 9)
    assert parse_date_token("03/11/2026") == D(2026, 3, 11)
    assert parse_date_token("2026-03-11") == D(2026, 3, 11)
    assert parse_date_token("garbage") is None


def test_strategies():
    w = DateWindow(D(2026, 3, 9), D(2026, 3, 13))
    assert parse_ship_dates("Early Ship Date: 09-MAR-26 Late Ship Date - 13-MAR-26") == w          # A
    assert parse_ship_dates("Order Date Early Ship Date Late Ship Date 10-JAN-26 09-MAR-26 13-MAR-26") == w  # B
    assert parse_ship_dates("Early Ship Date Late Ship Date\n 09-MAR-26   13-MAR-26") == w          # B no order
    assert parse_ship_dates("Ship Date 09-MAR-26 to 13-MAR-26") == w                               # C
    assert parse_ship_dates("Early Ship Date: 13-MAR-26 Late Ship Date: 09-MAR-26") == w            # swap
    assert parse_ship_dates("nothing here") is None


def test_midpoint_intersect():
    assert midpoint(DateWindow(D(2026, 3, 9), D(2026, 3, 13))) == D(2026, 3, 11)
    assert midpoint(DateWindow(D(2026, 3, 9), D(2026, 3, 12))) == D(2026, 3, 10)
    assert midpoint(DateWindow(D(2026, 3, 9), D(2026, 3, 9))) == D(2026, 3, 9)
    a, b = DateWindow(D(2026, 3, 1), D(2026, 3, 10)), DateWindow(D(2026, 3, 5), D(2026, 3, 20))
    assert intersect([a, b]) == DateWindow(D(2026, 3, 5), D(2026, 3, 10))
    assert intersect([a, DateWindow(D(2026, 4, 1), D(2026, 4, 2))]) is None
    assert format_mdy(D(2026, 3, 11)) == "03/11/2026"


def test_compute():
    today = D(2026, 1, 1)
    r = compute_shipping_date([DateWindow(D(2026, 3, 9), D(2026, 3, 13))], today)
    assert r.shipping_date == D(2026, 3, 11) and not r.flags and r.window
    a, b = DateWindow(D(2026, 3, 1), D(2026, 3, 3)), DateWindow(D(2026, 4, 1), D(2026, 4, 3))
    r = compute_shipping_date([a, b], today)
    assert r.window is None and r.shipping_date == D(2026, 3, 2)
    assert [f.code for f in r.flags] == ["no_date_intersection"]
    r = compute_shipping_date([DateWindow(D(2026, 3, 1), D(2026, 3, 5))], D(2026, 3, 4))
    assert r.shipping_date == D(2026, 3, 4) and r.flags[0].code == "date_in_past"
    r = compute_shipping_date([DateWindow(D(2026, 3, 1), D(2026, 3, 5))], D(2026, 6, 4))
    assert r.shipping_date == D(2026, 6, 4) and r.flags[0].code == "date_in_past"   # whole window past -> today
