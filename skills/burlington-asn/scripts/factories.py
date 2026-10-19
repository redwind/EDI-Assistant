#!/usr/bin/env python3
"""Manage the saved factory (From address) list at ~/.burlington-asn/factories.json.

  factories.py list
  factories.py find "SUMEC TEXTILE COMPANY LIMITED"     # fuzzy match on name/aliases
  factories.py add --json '{"name":"...","address1":"...","address2":"","city":"...",
                            "state":"...","zip":"...","country":"CN","aliases":["..."]}'

Override the base directory with env BURLINGTON_ASN_HOME. Country is a select with only
US/CA/CN; other countries need the 'More..' link (user picks manually).
"""
import argparse
import json
import os
import re
import sys

KEYS = ["name", "address1", "address2", "city", "state", "zip", "country"]


def path():
    base = os.environ.get("BURLINGTON_ASN_HOME") or os.path.join(os.path.expanduser("~"), ".burlington-asn")
    return os.path.join(base, "factories.json")


def load():
    try:
        with open(path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, ValueError):
        return []


def save(items):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    with open(path(), "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


STOP = {"co", "ltd", "limited", "company", "corp", "inc", "the", "and", "llc", "jsc", "tnhh"}


def tokens(s):
    return {t for t in re.findall(r"[a-z0-9一-鿿]+", (s or "").lower()) if t not in STOP}


def score(query, item):
    q = tokens(query)
    best = 0.0
    for n in [item.get("name", "")] + list(item.get("aliases", [])):
        t = tokens(n)
        if not q or not t:
            continue
        if re.sub(r"\W", "", n.lower()) == re.sub(r"\W", "", query.lower()):
            return 1.0
        best = max(best, len(q & t) / float(len(q | t)))
    return best


def find(text, items=None, threshold=0.5):
    items = load() if items is None else items
    res = [(score(text, i), i) for i in items]
    res = [(s, i) for s, i in res if s >= threshold]
    return [dict(i, match_score=round(s, 2)) for s, i in sorted(res, key=lambda x: -x[0])]


def add(entry, items=None):
    items = load() if items is None else items
    missing = [k for k in ("name", "address1", "city", "country") if not entry.get(k)]
    if missing:
        raise ValueError("missing required keys: %s" % ", ".join(missing))
    clean = {k: entry.get(k, "") for k in KEYS}
    clean["aliases"] = entry.get("aliases", [])
    for i, it in enumerate(items):
        if it.get("name", "").lower() == clean["name"].lower():
            clean["aliases"] = sorted(set(it.get("aliases", [])) | set(clean["aliases"]))
            items[i] = clean
            break
    else:
        items.append(clean)
    return items


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    f = sub.add_parser("find")
    f.add_argument("text")
    ad = sub.add_parser("add")
    ad.add_argument("--json", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print(json.dumps({"file": path(), "factories": load()}, indent=2, ensure_ascii=False))
    elif a.cmd == "find":
        print(json.dumps({"file": path(), "matches": find(a.text)}, indent=2, ensure_ascii=False))
    else:
        try:
            items = add(json.loads(a.json))
        except ValueError as e:
            print("error: %s" % e, file=sys.stderr)
            return 2
        save(items)
        print(json.dumps({"saved_to": path(), "count": len(items)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
