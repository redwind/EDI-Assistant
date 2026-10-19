from decimal import Decimal

from edi_assistant.data import detect_header, extract_rows, load_grid, suggest_mapping, list_sheets


def test_sample_pipeline(sample_path):
    assert list_sheets(sample_path) == ["page 1"]
    grid = load_grid(sample_path)
    det = detect_header(grid)
    assert det.header_rows == [3, 4]
    assert det.data_start_row == 5
    assert len(det.columns) == 7
    pk = next(c for c in det.columns if c.letter == "C")
    assert pk.span_cols == 2 and pk.joined == "包装 / Packages"
    mapping, scores = suggest_mapping(det)
    for k in ("po", "description", "packages", "quantity", "gross_weight", "net_weight", "size"):
        assert mapping.columns[k] is not None and scores[k] >= 0.85, k
    assert mapping.columns["line"] is None
    rx = extract_rows(grid, det, mapping)
    assert [l.po_line_id for l in rx.lines] == ["580367401", "580367301"]
    l0, l1 = rx.lines
    assert l0.packages == 85 and l0.quantity == 510 and l0.gross_weight == Decimal("1020.00")
    assert l1.packages == 85 and l1.gross_weight == 1020
    assert sorted(r for r, _ in rx.skipped) == [7, 8]
    assert rx.company_text == "SUMEC TEXTILE COMPANY LIMITED"
    assert any(f.code == "line_assigned" for f in l0.flags)
