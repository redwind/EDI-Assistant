#!/usr/bin/env python3
"""Write ASN / Web Shipment IDs into the 'ASN #' column of a COPY of a PO-tracker workbook.

Usage:
  write_asn.py FILE.xlsx --asn 582067802=900001 --asn 582067804=900002 [--sheet NAME] [--out PATH] [--overwrite]

Each KEY is the 9-digit PO line id (Master PO # + 2-digit Line #). The ORIGINAL file is never modified: the result goes to
<stem>_ASN_<YYYYMMDD-HHMMSS>.xlsx next to it (or --out). The target is the column whose header is exactly 'ASN #';
'Submit ASN # (w/ Date)' is never touched. A cell that already holds a different ASN is left alone unless --overwrite.
Workbook is loaded without data_only (formulas survive); drawings/images may be dropped by openpyxl.
Prints JSON {"output", "written": [...], "not_found": [...], "kept_existing": [...]}. Exit 1 when something was not written.
"""
import argparse
import datetime as dt
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openpyxl  # noqa: E402

import parse_packing_list as pp  # noqa: E402


def default_out(src, now=None):
    now = now or dt.datetime.now()
    stem, _ = os.path.splitext(os.path.basename(src))
    return os.path.join(os.path.dirname(os.path.abspath(src)), "%s_ASN_%s.xlsx" % (stem, now.strftime("%Y%m%d-%H%M%S")))


def find_sheet(wb, sheet=None):
    sheets = [wb[sheet]] if sheet else wb.worksheets
    for ws in sheets:
        hr, cols = pp.detect_tracker_header(ws)
        if hr is not None and "asn" in cols:
            return ws, hr, cols
    return None, None, None


def write_asn(src, asn_map, sheet=None, out=None, overwrite=False):
    res = {"output": None, "written": [], "not_found": [], "kept_existing": [], "errors": []}
    out = out or default_out(src)
    if os.path.abspath(out) == os.path.abspath(src):
        res["errors"].append("Refusing to write over the original file")
        return res
    wb = openpyxl.load_workbook(src)  # formulas kept
    ws, hr, cols = find_sheet(wb, sheet)
    if ws is None:
        res["errors"].append("No PO-tracker sheet with an 'ASN #' column found")
        return res
    merged = pp.merged_index(ws)
    asn_col = cols["asn"]
    by_id = {}
    for r in range(hr + 1, ws.max_row + 1):
        if all(ws.cell(r, c).value in (None, "") for c in (cols["po"], cols["line"], cols["quantity"], cols["pack"])):
            break
        kind, master, suffix = pp.parse_po(pp.merged_value(ws, r, cols["po"], merged))
        line = ws.cell(r, cols["line"]).value
        if kind == "master" and pp.to_number(line) is not None:
            by_id[master + str(int(pp.to_number(line))).zfill(2)] = r
        elif kind == "doc":
            by_id[master + suffix] = r
    for doc, asn in asn_map.items():
        r = by_id.get(doc)
        if r is None:
            res["not_found"].append(doc)
            continue
        cell = ws.cell(r, asn_col)
        old = pp.asn_text(cell.value)
        if old and old != str(asn) and not overwrite:
            res["kept_existing"].append({"document_id": doc, "cell": cell.coordinate, "existing": old, "new": str(asn)})
            continue
        cell.value = int(asn) if str(asn).isdigit() else str(asn)
        res["written"].append({"document_id": doc, "cell": cell.coordinate, "value": cell.value})
    if res["written"]:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        wb.save(out)
        res["output"] = out
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx")
    ap.add_argument("--asn", action="append", default=[], metavar="DOC=ASN", required=True)
    ap.add_argument("--sheet")
    ap.add_argument("--out")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    m = {}
    for item in a.asn:
        k, _, v = item.partition("=")
        if not k.strip() or not v.strip():
            sys.exit("bad --asn %r (expected DOC=ASN)" % item)
        m[k.strip()] = v.strip()
    res = write_asn(a.xlsx, m, a.sheet, a.out, a.overwrite)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 1 if (res["errors"] or res["not_found"] or res["kept_existing"] or not res["written"]) else 0


if __name__ == "__main__":
    sys.exit(main())
