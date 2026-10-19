from decimal import Decimal

from edi_assistant.data.values import (format_weight, parse_decimal, parse_int_exact, parse_line_cell,
                                       parse_po_cell, to_text)


def test_parse_decimal():
    assert parse_decimal("1,020     PCS") == 1020
    assert parse_decimal("510 PCS") == 510
    assert parse_decimal("1020.00") == Decimal("1020.00")
    assert parse_decimal(85) == 85 and parse_decimal(1020.5) == Decimal("1020.5")
    assert parse_decimal(None) is None and parse_decimal("") is None and parse_decimal("CTN") is None


def test_parse_int_exact():
    assert parse_int_exact("85") == 85
    assert parse_int_exact("85.5") is None
    assert parse_int_exact("1020.00") == 1020


def test_parse_po_cell():
    assert parse_po_cell(5803674) == ("5803674", None)
    assert parse_po_cell(5803674.0) == ("5803674", None)
    assert parse_po_cell("5803674.0") == ("5803674", None)
    assert parse_po_cell("580367401") == ("5803674", 1)
    assert parse_po_cell("5803674-02") == ("5803674", 2)
    assert parse_po_cell("5803674 / 3") == ("5803674", 3)
    assert parse_po_cell(None) is None and parse_po_cell("") is None and parse_po_cell("170") is None


def test_misc():
    assert parse_line_cell("3") == 3 and parse_line_cell(0) is None and parse_line_cell(100) is None
    assert format_weight(Decimal("1020")) == "1020.00"
    assert format_weight(Decimal("1.005")) == "1.01"
    assert to_text(85.0) == "85" and to_text(None) == "" and to_text(" a ") == "a"
