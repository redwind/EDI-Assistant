#!/usr/bin/env python3
"""Parse a factory packing-list Excel file into JSON for the burlington-asn skill.

Usage:
  parse_packing_list.py FILE.xlsx [--sheet NAME] [--mapping mapping.json]
                        [--save-mapping PATH|auto] [--no-saved-mapping]
                        [--profile auto|po_tracker|packing_list] [--include-with-asn]

Two input formats (output field "profile"):
  po_tracker    (primary) the MDDP PO-tracker workbook: Master PO # + Line # -> 9-digit id, Order Units, Pack,
                Gross Weight/Carton(kg), EDI PO Start/End Ship, ASN #. Auto-detected from the header row.
  packing_list  (secondary) factory packing list; columns found by synonyms / saved mapping.
Prints one JSON document to stdout. Only dependency: openpyxl.
Mapping JSON format: {"po": "A", "packages": "C", ..., "header_row": 4}
Saved mappings live in ~/.burlington-asn/mappings/<fingerprint>.json
(override the base dir with env BURLINGTON_ASN_HOME).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
try:
    import openpyxl
    from openpyxl.utils import column_index_from_string, get_column_letter
except ImportError:  # pragma: no cover
    sys.exit("openpyxl is required: pip install openpyxl")

FIELDS = ["po", "line", "description", "packages", "quantity",
          "gross_weight", "net_weight", "size"]
REQUIRED = ["po", "packages", "quantity", "gross_weight"]

# Synonyms are matched against a normalized header (lowercase, only a-z 0-9 CJK
# and Vietnamese letters kept). "exact" = whole-cell match, "contains" = substring.
SYN = {
    "gross_weight": {"contains": ["grossweight", "grossw", "gw", "毛重", "trọnglượnggộp", "trọnglượngcả", "tlgộp"],
                     "exact": ["gross"]},
    "net_weight": {"contains": ["netweight", "netw", "nw", "净重", "trọnglượngtịnh", "tltịnh"],
                   "exact": ["net"]},
    "po": {"contains": [],
           "exact": ["po", "pono", "ponumber", "po#", "purchaseorder", "purchaseorderno", "order", "orderno",
                     "ordernumber", "订单号", "订单", "订单编号", "đơnhàng", "sốpo", "sopo", "mãpo", "poid"]},
    "line": {"contains": [], "exact": ["line", "lineno", "linenumber", "poline", "行号", "dòng", "sốdòng", "suffix"]},
    "packages": {"contains": ["packages", "package", "ctns", "cartons", "carton", "包装", "箱数", "件数", "sốthùng", "sốkiện", "sốkiện"],
                 "exact": ["ctn", "pkgs", "pkg", "ctns", "箱"]},
    "quantity": {"contains": ["quantity", "qty", "数量", "sốlượng"], "exact": ["pcs", "pieces", "units"]},
    "size": {"contains": ["size", "meas", "dimension", "尺码", "尺寸", "kíchthước"], "exact": []},
    "description": {"contains": ["description", "style", "品名", "款号", "品号", "货号", "mặthàng", "tênhàng"],
                    "exact": ["item", "itemno", "desc"]},
}
# Order matters: a cell is assigned to the first field that matches.
FIELD_ORDER = ["gross_weight", "net_weight", "po", "line", "packages", "quantity", "size", "description"]


def home_dir():
    return os.environ.get("BURLINGTON_ASN_HOME") or os.path.join(os.path.expanduser("~"), ".burlington-asn")


def norm(text):
    return re.sub(r"[^a-z0-9#一-鿿À-ỹ]", "", str(text).lower())


def match_field(text):
    n = norm(text)
    if not n:
        return None
    for f in FIELD_ORDER:
        s = SYN[f]
        if n in s["exact"] or any(k in n for k in s["contains"]):
            return f
    return None


def to_number(v):
    """Extract a number from 85, '85', '510 PCS', '1,020     PCS', '2,040. KGS'."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def clean_num(x):
    if x is None:
        return None
    return int(x) if float(x).is_integer() else x


def cell_text(v):
    return "" if v is None else str(v).strip()


def row_hits(ws, r, max_col):
    """{field: (col_index, text)} for header-looking cells in row r (leftmost wins)."""
    hits = {}
    for c in range(1, max_col + 1):
        v = ws.cell(r, c).value
        if v is None or isinstance(v, (int, float)):
            continue
        f = match_field(v)
        if f and f not in hits:
            hits[f] = (c, cell_text(v))
    return hits


def detect_header(ws):
    max_col = ws.max_column
    best_r, best_hits, best_score = None, {}, 0
    for r in range(1, min(ws.max_row, 40) + 1):
        hits = row_hits(ws, r, max_col)
        score = len(hits) + (1 if "po" in hits else 0)
        if score > best_score:
            best_r, best_hits, best_score = r, hits, score
    if best_r is None or len(best_hits) < 3:
        return None, {}, best_score
    cols = dict(best_hits)
    used = {c for c, _ in cols.values()}
    # Fill missing fields from adjacent header rows (two-row headers).
    for nr in (best_r - 1, best_r + 1):
        if nr < 1 or nr > ws.max_row:
            continue
        for f, (c, t) in row_hits(ws, nr, max_col).items():
            if f not in cols and c not in used:
                cols[f] = (c, t)
                used.add(c)
    return best_r, cols, best_score


def fingerprint_of(ws, header_row):
    texts = [norm(ws.cell(header_row, c).value) for c in range(1, ws.max_column + 1)
             if ws.cell(header_row, c).value is not None]
    texts = [t for t in texts if t]
    raw = "|".join(texts)
    return raw, hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def parse_po(raw):
    """Return (kind, master, suffix) kind in {'doc','master',None,'total'}."""
    if raw is None:
        return None, None, None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    s = re.sub(r"\s", "", str(raw))
    s = re.sub(r"\.0+$", "", s)
    if not s:
        return None, None, None
    if "total" in s.lower() or "合计" in s or "总计" in s:
        return "total", None, None
    if re.fullmatch(r"\d{9}", s):
        return "doc", s[:7], s[7:]
    m = re.fullmatch(r"(\d{7})[-/_.](\d{1,2})", s)
    if m:
        return "doc", m.group(1), m.group(2).zfill(2)
    if re.fullmatch(r"\d{7}", s):
        return "master", s, None
    return "bad", s, None


COMPANY_RE = re.compile(r"(CO\.?,?\s*LTD|LTD|LIMITED|COMPANY|CORP|INC\b|GMBH|TNHH|JSC|有限公司|公司)", re.I)


def title_info(ws, header_row, last_data_row):
    head_texts = []
    for r in range(1, header_row):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip():
                head_texts.append(v)
    foot_texts = []
    for r in range(last_data_row + 1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip():
                foot_texts.append(v)
    head = "\n".join(head_texts)
    foot = "\n".join(foot_texts)
    both = head + "\n" + foot
    inv = None
    m = re.search(r"INV(?:OICE)?\.?\s*NO\.?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-/_.]*)", both, re.I)
    if m:
        inv = m.group(1).rstrip(".")
    date = None
    m = re.search(r"DATE\s*[:：]?\s*(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})", both, re.I)
    if m:
        date = m.group(1)
    name = None
    for src in (head, foot):
        for line in src.splitlines():
            line = line.strip()
            if line and re.search(r"[A-Za-z]", line) and COMPANY_RE.search(line) and not re.search(r"[一-鿿]", line):
                name = line
                break
        if name:
            break
    if not name:
        for line in head.splitlines():
            if line.strip():
                name = line.strip()
                break
    addr = None
    if name:
        for line in foot.splitlines() + [foot.replace("\n", " ")]:
            idx = line.find(name)
            if idx >= 0:
                rest = foot[foot.find(name) + len(name):]
                rest = " ".join(x.strip() for x in rest.splitlines() if x.strip())
                if rest:
                    addr = rest
                break
    return inv, date, name, addr


# ---------------------------------------------------------------------------------------------
# PO-tracker profile
# ---------------------------------------------------------------------------------------------
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
TRACKER_REQUIRED = ["po", "line", "quantity", "pack", "gw_per_carton", "start_ship", "end_ship"]


def tracker_field(text):
    """Field key for a tracker header cell (exact normalized match, so 'Submit ASN # (w/ Date)' is never 'asn')."""
    n = norm(text)
    if n in ("masterpo#", "masterpo", "masterpono", "masterponumber"):
        return "po"
    if n in ("line#", "line", "lineno", "linenumber"):
        return "line"
    if n in ("asn#", "asn", "asnno", "asnnumber"):
        return "asn"
    if n in ("model#", "model", "modelno"):
        return "model_no"
    if n in ("orderunits", "orderedunits", "orderqty"):
        return "quantity"
    if n == "pack":
        return "pack"
    if "grossweight" in n and "carton" in n:
        return "gw_per_carton"
    if n in ("edipostartship", "startship"):
        return "start_ship"
    if n in ("edipoendship", "endship"):
        return "end_ship"
    if n == "container":
        return "container"
    if "description" in n:
        return "description"
    return None


def detect_tracker_header(ws):
    """(header_row, {field: col_index}) when a PO-tracker header row exists in the first 40 rows, else (None, {})."""
    for r in range(1, min(ws.max_row, 40) + 1):
        cols = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if v is None or isinstance(v, (int, float)):
                continue
            f = tracker_field(v)
            if f and f not in cols:
                cols[f] = c
        if all(k in cols for k in TRACKER_REQUIRED):
            return r, cols
    return None, {}


def merged_value(ws, r, c, merged):
    """Cell value, inheriting the top-left value when (r, c) lies in a merged range."""
    v = ws.cell(r, c).value
    if v is None:
        rng = merged.get((r, c))
        if rng is not None:
            v = ws.cell(rng.min_row, rng.min_col).value
    return v


def merged_index(ws):
    idx = {}
    for rng in ws.merged_cells.ranges:
        for rr in range(rng.min_row, rng.max_row + 1):
            for cc in range(rng.min_col, rng.max_col + 1):
                idx[(rr, cc)] = rng
    return idx


def to_iso_date(v):
    """datetime/date or 'DD-MON-YY' / 'MM/DD/YYYY' / 'YYYY-MM-DD' text -> 'YYYY-MM-DD' (None if unreadable)."""
    import datetime as dt
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    parts = str(v).strip().replace("/", "-").split("-")
    try:
        if len(parts) == 3:
            a, b, c = parts
            if b.upper()[:3] in MONTHS:
                y = int(c) + (2000 if int(c) < 100 else 0)
                return dt.date(y, MONTHS.index(b.upper()[:3]) + 1, int(a)).isoformat()
            if len(a) == 4:
                return dt.date(int(a), int(b), int(c)).isoformat()
            y = int(c) + (2000 if int(c) < 100 else 0)
            return dt.date(y, int(a), int(b)).isoformat()
    except ValueError:
        return None
    return None


def asn_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def parse_tracker(ws, header_row, cols, include_with_asn=False):
    from openpyxl.utils import get_column_letter
    result = {"file": None, "sheet": ws.title, "profile": "po_tracker", "header_row": header_row,
              "detected_columns": {f: {"col": get_column_letter(c), "header_text": cell_text(ws.cell(header_row, c).value)}
                                   for f, c in cols.items()},
              "confidence": "high", "fingerprint": None, "fingerprint_raw": None, "mapping_source": "detected",
              "invoice_no": None, "invoice_date": None, "factory_name_guess": None, "factory_address_guess": None,
              "lines": [], "skipped_with_asn": [], "totals": {}, "totals_check": {"status": "not_applicable"},
              "blocking": [], "errors": [], "notes": []}
    raw_fp, fp = fingerprint_of(ws, header_row)
    result["fingerprint_raw"], result["fingerprint"] = raw_fp, fp
    if "asn" not in cols:
        result["notes"].append("No 'ASN #' column found: rows with an existing ASN cannot be detected and write_asn.py has no target column.")
    merged = merged_index(ws)
    last = ws.max_row
    ref = ws.auto_filter.ref if ws.auto_filter is not None else None
    if ref:
        try:
            from openpyxl.utils.cell import range_boundaries
            _, mn_r, _, mx_r = range_boundaries(ref)
            if mn_r == header_row and mx_r > header_row:
                last = min(last, mx_r)
        except Exception:
            pass
    key_cols = [cols[k] for k in ("po", "line", "quantity", "pack", "gw_per_carton") if k in cols]
    seen = set()
    for r in range(header_row + 1, last + 1):
        # the data block ends at the first row that is empty in all key columns (a secondary table may follow)
        if all(ws.cell(r, c).value in (None, "") for c in key_cols):
            break
        kind, master, suffix = parse_po(merged_value(ws, r, cols["po"], merged))
        line_raw = ws.cell(r, cols["line"]).value
        line_txt = cell_text(line_raw)
        warnings_ = []
        if kind == "doc":
            doc_id = master + suffix
        elif kind == "master" and to_number(line_raw) is not None:
            doc_id = master + str(int(to_number(line_raw))).zfill(2)
        else:
            result["errors"].append("Row %d: cannot build a PO line id from Master PO %r + Line %r - skipped" %
                                    (r, cell_text(merged_value(ws, r, cols["po"], merged)), line_txt))
            continue
        master = doc_id[:7]
        suffix = doc_id[7:]
        units = to_number(ws.cell(r, cols["quantity"]).value)
        pack = to_number(ws.cell(r, cols["pack"]).value)
        gw = to_number(ws.cell(r, cols["gw_per_carton"]).value)
        start = to_iso_date(ws.cell(r, cols["start_ship"]).value)
        end = to_iso_date(ws.cell(r, cols["end_ship"]).value)
        cartons = None
        if units is None or units <= 0:
            warnings_.append("MISSING_QUANTITY: Order Units unreadable")
        if pack is None or pack <= 0:
            warnings_.append("MISSING_PACK: Pack unreadable")
        if gw is None:
            warnings_.append("MISSING_GROSS_WEIGHT: Gross Weight/Carton unreadable")
        if units and pack and units > 0 and pack > 0:
            q = units / pack
            if abs(q - round(q)) < 1e-9:
                cartons = int(round(q))
            else:
                warnings_.append("NON_INTEGER_CARTONS: %s / %s = %.4f - ask the user" % (clean_num(units), clean_num(pack), q))
        if not start or not end:
            warnings_.append("MISSING_SHIP_DATES: EDI PO Start/End Ship unreadable")
        elif start > end:
            warnings_.append("SHIP_WINDOW_REVERSED: start after end - swapped")
            start, end = end, start
        if doc_id in seen:
            warnings_.append("DUPLICATE_DOCUMENT_ID: %s appears more than once in the file" % doc_id)
        seen.add(doc_id)
        existing = asn_text(ws.cell(r, cols["asn"]).value) if "asn" in cols else ""
        line = {"excel_row": r, "po_raw": cell_text(merged_value(ws, r, cols["po"], merged)), "master_po": master,
                "line_suffix": suffix, "line_no_text": line_txt, "document_id": doc_id,
                "description": cell_text(ws.cell(r, cols["description"]).value) if "description" in cols else "",
                "model_no": cell_text(ws.cell(r, cols["model_no"]).value) if "model_no" in cols else "",
                "container": cell_text(merged_value(ws, r, cols["container"], merged)) if "container" in cols else "",
                "order_units": clean_num(units), "quantity": clean_num(units), "pack": clean_num(pack),
                "units_per_carton": clean_num(pack), "cartons": cartons,
                "gross_weight_per_carton": round(gw, 2) if gw is not None else None,
                "gross_weight": round(gw, 2) if gw is not None else None, "weight_basis": "per_carton_as_is",
                "start_ship": start, "end_ship": end, "existing_asn": existing, "warnings": warnings_}
        if existing and not include_with_asn:
            result["skipped_with_asn"].append(line)
            continue
        result["lines"].append(line)
        for w in warnings_:
            if w.split(":")[0] in ("MISSING_QUANTITY", "MISSING_PACK", "MISSING_GROSS_WEIGHT", "MISSING_SHIP_DATES",
                                   "NON_INTEGER_CARTONS", "DUPLICATE_DOCUMENT_ID"):
                result["blocking"].append("%s (row %d): %s" % (doc_id, r, w))
    if not result["lines"]:
        result["errors"].append("No PO lines to process (all rows already have an ASN? use --include-with-asn to force).")
    result["totals"] = {"lines": len(result["lines"]), "shipments": len({l["master_po"] for l in result["lines"]}),
                        "cartons": clean_num(sum(l["cartons"] or 0 for l in result["lines"]))}
    return result


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def parse(path, sheet=None, mapping=None, use_saved=True, saved_dir=None, profile="auto", include_with_asn=False):
    wb = openpyxl.load_workbook(path, data_only=True)
    if profile in ("auto", "po_tracker") and not mapping:
        sheets = [wb[sheet]] if sheet and sheet in wb.sheetnames else wb.worksheets
        for s_ in sheets:
            hr, tcols = detect_tracker_header(s_)
            if hr is not None:
                res = parse_tracker(s_, hr, tcols, include_with_asn)
                res["file"] = os.path.basename(path)
                return res
        if profile == "po_tracker":
            return {"file": os.path.basename(path), "profile": "po_tracker", "lines": [], "blocking": [],
                    "errors": ["No PO-tracker header row found (need Master PO #, Line #, Order Units, Pack, "
                               "Gross Weight/Carton, EDI PO Start Ship, EDI PO End Ship)."]}
    result = {"file": os.path.basename(path), "profile": "packing_list", "sheet": None, "header_row": None,
              "detected_columns": {}, "confidence": None, "fingerprint": None,
              "fingerprint_raw": None, "mapping_source": "detected",
              "invoice_no": None, "invoice_date": None, "factory_name_guess": None,
              "factory_address_guess": None, "lines": [], "totals": {},
              "totals_check": {}, "blocking": [], "errors": []}
    # choose sheet
    if sheet:
        if sheet not in wb.sheetnames:
            result["errors"].append("Sheet %r not found; sheets: %s" % (sheet, wb.sheetnames))
            return result
        ws = wb[sheet]
        header_row, cols, _ = detect_header(ws)
    else:
        best = None
        for s in wb.worksheets:
            hr, cl, sc = detect_header(s)
            if hr is not None and (best is None or sc > best[3]):
                best = (s, hr, cl, sc)
        if best is None:
            ws = wb.worksheets[0]
            header_row, cols = None, {}
        else:
            ws, header_row, cols = best[0], best[1], best[2]
    result["sheet"] = ws.title

    if mapping:
        header_row = int(mapping.get("header_row", header_row or 1))
        cols = {}
        for f in FIELDS:
            if mapping.get(f):
                ci = column_index_from_string(mapping[f])
                cols[f] = (ci, cell_text(ws.cell(header_row, ci).value))
        result["mapping_source"] = "explicit"
    if header_row is None:
        result["errors"].append("No header row detected (need at least 3 recognizable column headers). "
                                "Show the first rows to the user and build a mapping (see references/excel_mapping.md).")
        return result

    raw_fp, fp = fingerprint_of(ws, header_row)
    result["fingerprint_raw"], result["fingerprint"] = raw_fp, fp
    if not mapping and use_saved:
        sp = os.path.join(saved_dir or os.path.join(home_dir(), "mappings"), fp + ".json")
        if os.path.exists(sp):
            try:
                m = load_json(sp)
                header_row = int(m.get("header_row", header_row))
                cols = {}
                for f in FIELDS:
                    if m.get(f):
                        ci = column_index_from_string(m[f])
                        cols[f] = (ci, cell_text(ws.cell(header_row, ci).value))
                result["mapping_source"] = "saved:" + sp
            except Exception as e:  # corrupt mapping: fall back to detection
                result["errors"].append("Could not load saved mapping %s: %s" % (sp, e))
    result["header_row"] = header_row
    result["detected_columns"] = {f: {"col": get_column_letter(c), "header_text": t} for f, (c, t) in cols.items()}
    missing = [f for f in REQUIRED if f not in cols]
    result["confidence"] = "high" if not missing else "low"
    if missing:
        result["errors"].append("Missing required column(s): %s. Ask the user to confirm columns "
                                "(references/excel_mapping.md)." % ", ".join(missing))
        return result

    ci = {f: c for f, (c, _) in cols.items()}
    lines, totals_row = [], None
    seen_suffix, seen_docs = {}, set()
    last_data_row = header_row
    for r in range(header_row + 1, ws.max_row + 1):
        po_cell = ws.cell(r, ci["po"]).value
        kind, master, suffix = parse_po(po_cell)
        cartons = to_number(ws.cell(r, ci["packages"]).value)
        qty = to_number(ws.cell(r, ci["quantity"]).value)
        if kind in (None, "total") :
            if cartons is not None and qty is not None:
                totals_row = {"excel_row": r, "cartons": cartons, "quantity": qty,
                              "gross_weight": to_number(ws.cell(r, ci["gross_weight"]).value)}
                last_data_row = max(last_data_row, r)
            continue
        if kind == "bad":
            result["errors"].append("Row %d: cannot interpret PO value %r (expected 7 or 9 digits) - skipped" % (r, str(po_cell)))
            continue
        last_data_row = r
        warnings_ = []
        if kind == "master":
            if "line" in ci and to_number(ws.cell(r, ci["line"]).value) is not None:
                suffix = str(int(to_number(ws.cell(r, ci["line"]).value))).zfill(2)
            else:
                seen_suffix[master] = seen_suffix.get(master, 0) + 1
                suffix = str(seen_suffix[master]).zfill(2)
                warnings_.append("LINE_SUFFIX_ASSIGNED: 7-digit PO, suffix %s assigned by order of appearance - verify on EDI" % suffix)
        doc_id = master + suffix
        if doc_id in seen_docs:
            warnings_.append("DUPLICATE_DOCUMENT_ID: %s appears more than once in the file" % doc_id)
        seen_docs.add(doc_id)
        gw = to_number(ws.cell(r, ci["gross_weight"]).value)
        nw = to_number(ws.cell(r, ci["net_weight"]).value) if "net_weight" in ci else None
        upc = None
        if cartons is None or cartons <= 0:
            warnings_.append("MISSING_CARTONS: Packages cell unreadable")
        if qty is None:
            warnings_.append("MISSING_QUANTITY: Quantity cell unreadable")
        if gw is None:
            warnings_.append("MISSING_GROSS_WEIGHT")
        if cartons and qty is not None and cartons > 0:
            q = qty / cartons
            if abs(q - round(q)) < 1e-9:
                upc = int(round(q))
            else:
                warnings_.append("NON_INTEGER_UNITS_PER_CARTON: %s / %s = %.4f - ask the user" % (clean_num(qty), clean_num(cartons), q))
        desc = cell_text(ws.cell(r, ci["description"]).value) if "description" in ci else ""
        size = cell_text(ws.cell(r, ci["size"]).value) if "size" in ci else ""
        line = {"excel_row": r, "po_raw": cell_text(po_cell), "master_po": master, "line_suffix": suffix,
                "document_id": doc_id, "description": desc, "cartons": clean_num(cartons),
                "quantity": clean_num(qty), "units_per_carton": upc,
                "gross_weight": round(gw, 2) if gw is not None else None,
                "net_weight": round(nw, 2) if nw is not None else None,
                "size": size, "warnings": warnings_}
        lines.append(line)
        for w in warnings_:
            if w.split(":")[0] in ("NON_INTEGER_UNITS_PER_CARTON", "MISSING_CARTONS", "MISSING_QUANTITY", "MISSING_GROSS_WEIGHT", "DUPLICATE_DOCUMENT_ID"):
                result["blocking"].append("%s (row %d): %s" % (doc_id, r, w))
    result["lines"] = lines
    if not lines:
        result["errors"].append("No PO lines found below the header row.")
    sums = {"cartons": clean_num(sum(l["cartons"] or 0 for l in lines)),
            "quantity": clean_num(sum(l["quantity"] or 0 for l in lines)),
            "gross_weight": round(sum(l["gross_weight"] or 0 for l in lines), 2)}
    result["totals"] = sums
    if totals_row:
        diffs = {}
        for k in ("cartons", "quantity", "gross_weight"):
            tv = totals_row.get(k)
            if tv is not None and abs(tv - sums[k]) > 0.005:
                diffs[k] = {"sum_of_lines": sums[k], "totals_row": clean_num(tv)}
        result["totals_check"] = {"status": "ok" if not diffs else "MISMATCH", "totals_row": {k: clean_num(v) if k != "excel_row" else v for k, v in totals_row.items()}, "differences": diffs}
        if diffs:
            result["blocking"].append("Totals row does not match sum of lines: %s" % json.dumps(diffs))
    else:
        result["totals_check"] = {"status": "no_totals_row"}
    inv, date, name, addr = title_info(ws, header_row, last_data_row)
    result["invoice_no"], result["invoice_date"] = inv, date
    result["factory_name_guess"], result["factory_address_guess"] = name, addr
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx")
    ap.add_argument("--sheet")
    ap.add_argument("--mapping", help="JSON mapping file {field: column_letter, header_row: n}")
    ap.add_argument("--save-mapping", help="write the effective mapping to PATH, or 'auto' for ~/.burlington-asn/mappings/<fingerprint>.json")
    ap.add_argument("--no-saved-mapping", action="store_true")
    ap.add_argument("--profile", choices=["auto", "po_tracker", "packing_list"], default="auto")
    ap.add_argument("--include-with-asn", action="store_true",
                    help="tracker: also process rows whose ASN # cell is already filled (default: skip them)")
    a = ap.parse_args(argv)
    mapping = load_json(a.mapping) if a.mapping else None
    res = parse(a.xlsx, a.sheet, mapping, use_saved=not a.no_saved_mapping, profile=a.profile,
                include_with_asn=a.include_with_asn)
    if a.save_mapping and res.get("header_row") and res.get("profile") == "packing_list":
        out = {f: v["col"] for f, v in res["detected_columns"].items()}
        out["header_row"] = res["header_row"]
        path = a.save_mapping
        if path == "auto":
            d = os.path.join(home_dir(), "mappings")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, res["fingerprint"] + ".json")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        res["saved_mapping_to"] = path
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
