#!/usr/bin/env python3
"""Compute the shipment plan (ship date + per-line carton plan) from parsed packing-list JSON.

PO-tracker input (parsed["profile"] == "po_tracker"): lines carry start_ship/end_ship from the Excel, so --dates is
OPTIONAL (Excel wins; --dates only adds a WEB_DATES_DIFFER warning), grouping defaults to one shipment per master PO,
qty_per_carton = Pack, cartons_per_site = Order Units / Pack, weight = Gross Weight/Carton as-is (NOT a total), and
--ordered DOC=Q applies the A/B rule: web Qty Ordered == Order Units -> Pack per carton; == Order Units / Pack -> 1 per
carton (prepack); anything else is BLOCKING. Invariant checked: qty_per_carton x cartons_per_site == Qty Ordered.

Usage:
  plan_shipment.py parsed.json --dates '580367401=09-MAR-26,13-MAR-26;580367301=09-MAR-26,15-MAR-26'
  plan_shipment.py parsed.json --dates-json dates.json [--per-master] [--prepack 580367401=2]
                   [--ordered 580367401=600] [--format json|table]

dates.json: {"580367401": ["09-MAR-26", "13-MAR-26"], ...}  (early, late ship date from the PO page)
--prepack DOC=N : the PO item shows a prepack sub-item of N units -> qty/carton = units_per_carton / N
--ordered DOC=Q : Qty Ordered read from the web. Packing list: warns when the Excel quantity exceeds it;
                  tracker: applies the A/B rule above and BLOCKS on a mismatch.
--today YYYY-MM-DD : override today's date (tests). A computed ship date that is already in the past is replaced
                  by today (binding rule) and reported as SHIP_DATE_IN_PAST in issues.
Dates accepted: DD-MON-YY (09-MAR-26), MM/DD/YYYY, YYYY-MM-DD. Output ship date: MM/DD/YYYY.
Exit code 1 when blocking issues exist (stop and ask the user).
"""
import argparse
import datetime as dt
import json
import sys

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def parse_date(s):
    s = s.strip()
    parts = s.replace("/", "-").split("-")
    if len(parts) == 3:
        a, b, c = parts
        if b.upper()[:3] in MONTHS:
            y = int(c)
            y += 2000 if y < 100 else 0
            return dt.date(y, MONTHS.index(b.upper()[:3]) + 1, int(a))
        if len(a) == 4:
            return dt.date(int(a), int(b), int(c))
        y = int(c)
        y += 2000 if y < 100 else 0
        return dt.date(y, int(a), int(b))  # MM/DD/YYYY
    raise ValueError("Unrecognized date: %r" % s)


def fmt_us(d):
    return d.strftime("%m/%d/%Y")


def intersect(windows):
    """windows: list of (early, late) dates -> (start, end) or None if empty."""
    start = max(w[0] for w in windows)
    end = min(w[1] for w in windows)
    return (start, end) if start <= end else None


def midpoint(start, end):
    """Midpoint of [start, end]; floor for odd day spans (Mar 9 & 13 -> Mar 11)."""
    return start + dt.timedelta(days=(end - start).days // 2)


def parse_kv(s, sep=";"):
    out = {}
    for part in filter(None, (p.strip() for p in (s or "").split(sep))):
        k, _, v = part.partition("=")
        out[k.strip()] = v.strip()
    return out


def _tracker_item(l, ordered, issues, blocking):
    did = l["document_id"]
    units, pack, cartons = l.get("order_units"), l.get("pack"), l.get("cartons")
    item = {"document_id": did, "master_po": l["master_po"], "description": l.get("description"),
            "model_no": l.get("model_no"), "container": l.get("container"),
            "cartons_per_site": cartons, "units_per_carton": pack, "qty_per_carton": None, "web_rule": "",
            "weight_kg": None, "start_ship": l.get("start_ship"), "end_ship": l.get("end_ship"),
            "warnings": list(l.get("warnings", []))}
    gw = l.get("gross_weight_per_carton")
    if gw is not None:
        item["weight_kg"] = "%.2f" % gw
    if not cartons or not pack:
        blocking.append("%s: Order Units / Pack is not an integer or missing - ask the user" % did)
        return item
    web = ordered.get(did)
    if web is None:
        item["qty_per_carton"] = pack
        item["web_rule"] = "unverified"
        item["warnings"].append("ORDERED_NOT_VERIFIED: web Qty Ordered not given - check it on the carton page (== %s or %s)"
                                % (units, cartons))
        return item
    try:
        w = float(web)
    except ValueError:
        blocking.append("%s: unreadable Qty Ordered %r" % (did, web))
        return item
    if w == float(units):
        item["qty_per_carton"], item["web_rule"] = pack, "units"
    elif w == float(cartons):
        item["qty_per_carton"], item["web_rule"] = 1, "packs"
        item["warnings"].append("PREPACK: web Qty Ordered == Order Units / Pack -> Qty Per Carton 1")
    else:
        item["web_rule"] = "mismatch"
        blocking.append("%s: web Qty Ordered %s is neither Order Units %s nor Order Units/Pack %s - stop and ask the user"
                        % (did, web, units, cartons))
        return item
    if item["qty_per_carton"] * cartons != w:  # invariant before Save
        blocking.append("%s: qty per carton x cartons != Qty Ordered %s" % (did, web))
    return item


def plan(parsed, dates, prepack=None, ordered=None, per_master=False, today=None):
    prepack, ordered = prepack or {}, ordered or {}
    today = today or dt.date.today()
    tracker = parsed.get("profile") == "po_tracker"
    if tracker:
        per_master = True
    issues, blocking = [], []
    lines = []
    for l in parsed["lines"]:
        if tracker:
            lines.append(_tracker_item(l, ordered, issues, blocking))
            continue
        did = l["document_id"]
        item = {"document_id": did, "master_po": l["master_po"], "description": l.get("description"),
                "cartons_per_site": l["cartons"], "units_per_carton": l["units_per_carton"],
                "qty_per_carton": None, "weight_kg": None, "warnings": list(l.get("warnings", []))}
        upc = l["units_per_carton"]
        if upc is None:
            blocking.append("%s: units per carton is not an integer / missing - ask the user" % did)
        else:
            n = prepack.get(did)
            if n:
                if upc % int(n) == 0:
                    item["qty_per_carton"] = upc // int(n)
                    item["prepack_units"] = int(n)
                else:
                    blocking.append("%s: units_per_carton %s not divisible by prepack %s - ask the user" % (did, upc, n))
            else:
                item["qty_per_carton"] = upc
        if l.get("gross_weight") is not None:
            item["weight_kg"] = "%.2f" % l["gross_weight"]
        if did in ordered and l["quantity"] is not None:
            try:
                if float(l["quantity"]) > float(ordered[did]):
                    w = "%s: Excel quantity %s > Qty Ordered %s on web - warn the user" % (did, l["quantity"], ordered[did])
                    issues.append(w)
                    item["warnings"].append(w)
            except ValueError:
                pass
        lines.append(item)
    for b in parsed.get("blocking", []):
        blocking.append("parser: " + b)

    groups = {}
    for it in lines:
        groups.setdefault(it["master_po"] if per_master else "ALL", []).append(it)
    shipments, missing = [], []
    for key, items in groups.items():
        wins, miss = [], []
        for it in items:
            d = dates.get(it["document_id"])
            if it.get("start_ship") and it.get("end_ship"):
                ex = (parse_date(it["start_ship"]), parse_date(it["end_ship"]))
                if ex[0] > ex[1]:
                    ex = (ex[1], ex[0])
                wins.append(ex)
                if d and (parse_date(d[0]), parse_date(d[1])) != ex:
                    msg = "WEB_DATES_DIFFER: %s Excel %s..%s vs PO page %s..%s - Excel is used, tell the user" % (
                        it["document_id"], fmt_us(ex[0]), fmt_us(ex[1]), d[0], d[1])
                    it["warnings"].append(msg)
                    issues.append(msg)
            elif not d:
                miss.append(it["document_id"])
            else:
                wins.append((parse_date(d[0]), parse_date(d[1])))
        entry = {"group": key, "lines": items, "ship_date": None, "window": None}
        if miss:
            missing += miss
        else:
            inter = intersect(wins)
            if inter is None:
                blocking.append("Group %s: ship-date windows of the POs do not intersect (%s) - ask the user" %
                                (key, "; ".join("%s..%s" % (fmt_us(a), fmt_us(b)) for a, b in wins)))
            else:
                entry["window"] = [fmt_us(inter[0]), fmt_us(inter[1])]
                sd = midpoint(*inter)
                if sd < today:   # binding rule: a ship date in the past becomes today (never silently)
                    msg = "SHIP_DATE_IN_PAST: group %s midpoint %s is in the past; today %s is used - tell the user" % (
                        key, fmt_us(sd), fmt_us(today))
                    issues.append(msg)
                    entry["ship_date_original"] = fmt_us(sd)
                    sd = today
                entry["ship_date"] = fmt_us(sd)
        shipments.append(entry)
    if missing:
        blocking.append("Missing early/late ship dates for: %s" % ", ".join(missing))
    return {"shipments": shipments, "issues": issues, "blocking": blocking,
            "factory_name_guess": parsed.get("factory_name_guess")}


def as_table(p):
    out = []
    for s in p["shipments"]:
        out.append("Shipment [%s]  ship date: %s  (window %s)" % (s["group"], s["ship_date"], s["window"]))
        out.append("| PO line | Container | Model | Ship window | Cartons | Qty/carton | Weight (KG) |")
        out.append("|---|---|---|---|---|---|---|")
        for l in s["lines"]:
            win = "%s..%s" % (l["start_ship"], l["end_ship"]) if l.get("start_ship") else ""
            out.append("| %s | %s | %s | %s | %s | %s | %s |" % (l["document_id"], l.get("container", ""), l.get("model_no", ""),
                                                                win, l["cartons_per_site"], l["qty_per_carton"], l["weight_kg"]))
        out.append("")
    for k in ("issues", "blocking"):
        for m in p[k]:
            out.append("%s: %s" % (k.upper(), m))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parsed")
    ap.add_argument("--dates")
    ap.add_argument("--dates-json")
    ap.add_argument("--per-master", action="store_true", help="one shipment per master PO (always on for po_tracker)")
    ap.add_argument("--prepack", help="DOC=N;DOC=N")
    ap.add_argument("--ordered", help="DOC=Q;DOC=Q")
    ap.add_argument("--format", choices=["json", "table"], default="json")
    ap.add_argument("--today", help="override today's date, YYYY-MM-DD (tests)")
    a = ap.parse_args(argv)
    with open(a.parsed, encoding="utf-8") as f:
        parsed = json.load(f)
    dates = {}
    if a.dates_json:
        with open(a.dates_json, encoding="utf-8") as f:
            dates.update(json.load(f))
    for k, v in parse_kv(a.dates).items():
        e, _, l = v.partition(",")
        dates[k] = [e.strip(), l.strip()]
    p = plan(parsed, dates, parse_kv(a.prepack), parse_kv(a.ordered), a.per_master,
             today=parse_date(a.today) if a.today else None)
    p["profile"] = parsed.get("profile", "packing_list")
    print(as_table(p) if a.format == "table" else json.dumps(p, indent=2, ensure_ascii=False))
    return 1 if p["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
