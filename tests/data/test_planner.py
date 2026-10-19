from decimal import Decimal as Dc

import pytest

from edi_assistant.core.errors import PlanError
from edi_assistant.core.models import FactoryAddress, POLine
from edi_assistant.data import PlanOptions, ResultsWriter, build_plan, plan_summary_rows

F = FactoryAddress(id="f", name="X", address1="a")


def L(po, line, row, pk=85, q=510, gw=1020):
    return POLine(po, line, row, packages=Dc(pk), quantity=Dc(q), gross_weight=Dc(gw))


def test_grouping_and_weights():
    lines = [L("5803674", 1, 5), L("5803673", 1, 6), L("5803674", 2, 7)]
    p = build_plan(lines, F, PlanOptions("per_file", False, "total_gw"), "f.xlsx", "s", "fp", "RID")
    assert len(p.shipments) == 1 and p.shipments[0].master_pos == ["5803674", "5803673"]
    assert p.shipments[0].label == "Shipment 1 (5803674, 5803673)" and p.run_id == "RID"
    p = build_plan(lines, F, PlanOptions("per_master_po", True, "per_carton_gw"), "f.xlsx", "s", "fp")
    assert [s.master_pos for s in p.shipments] == [["5803674"], ["5803673"]]
    assert [len(s.lines) for s in p.shipments] == [2, 1]
    assert p.shipments[0].lines[0].weight_text == "12.00" and p.dry_run
    rows = plan_summary_rows(p)
    assert rows[0]["po_line_id"] == "580367401" and rows[0]["units_per_carton"] == "6"
    assert len(p.run_id) == len("20261018-101010-abcd")


def test_errors():
    with pytest.raises(PlanError):
        build_plan([], F, PlanOptions("per_file", False, "total_gw"), "f", "s", "fp")
    with pytest.raises(PlanError) as ei:
        build_plan([L("5803674", 1, 5), L("5803674", 1, 6)], F, PlanOptions("per_file", False, "total_gw"),
                   "f", "s", "fp")
    assert "Duplicate" in ei.value.message_vi


def test_results_csv():
    p = build_plan([L("5803674", 1, 5)], F, PlanOptions("per_file", False, "total_gw"), "f.xlsx", "s", "fp")
    p.shipments[0].web_shipment_id = "123"
    w = ResultsWriter(p.run_id)
    path = w.write(p)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("run_id,excel_file,shipment_index") and len(lines) == 2
    assert "580367401" in lines[1] and "1020.00" in lines[1]
