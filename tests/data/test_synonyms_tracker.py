import pytest

from edi_assistant.data.synonyms import field_scores


@pytest.mark.parametrize("header,field,score", [
    ("Master PO #", "po", 1.0), ("Shyft PO #", "po", 0.0), ("Line #", "line", 1.0), ("ASN #", "asn", 1.0),
    ("Submit ASN # (w/ Date)", "asn", 0.0), ("Submit ASN # (w/ Date)", "net_weight", 0.0),
    ("Model #", "model_no", 1.0), ("Styles Description ", "description", 0.85),
    ("Order Units", "quantity", 1.0), ("EDI PO Start Ship", "start_ship", 1.0),
    ("EDI PO End Ship", "end_ship", 1.0), ("Pack", "pack", 1.0), ("Pack", "packages", 0.7),
    ("Gross Weight/Carton(kg)", "gw_per_carton", 1.0), ("Gross Weight/Carton(kg)", "gross_weight", 0.85),
    ("Gross Weight/Carton(kg)", "packages", 0.0), ("Container", "container", 1.0),
    ("EDI Units", "quantity", 0.0), ("Transfer PO (w/ Dates)", "po", 0.0),
])
def test_scores(header, field, score):
    assert field_scores(header)[field] == score
