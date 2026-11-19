"""EN/ZH/VI synonym dictionary and header-to-field matching."""
from __future__ import annotations

from edi_assistant.core.textnorm import normalize_header

SYNONYMS: dict[str, list[str]] = {
    "po": ["po", "po no", "po number", "po#", "purchase order", "purchase order no", "order no", "order number",
           "订单号", "采购订单", "po号", "订单", "số po", "mã po", "đơn hàng", "số đơn hàng"],
    "line": ["line", "line no", "line number", "ln", "line item", "item no", "行号", "行", "dòng", "số dòng"],
    "description": ["description", "desc", "item", "item description", "style", "style no", "article", "article no",
                    "product", "品名", "货号", "款号", "品名规格", "mô tả", "tên hàng", "mã hàng"],
    "packages": ["packages", "package", "pkgs", "ctn", "ctns", "carton", "cartons", "carton qty", "no of ctn",
                 "no of cartons", "qty of ctn", "件数", "箱数", "包装", "箱", "số thùng", "thùng", "số kiện", "kiện"],
    "quantity": ["quantity", "qty", "pcs", "pieces", "total qty", "total quantity", "qty pcs", "数量", "总数量",
                 "số lượng", "sl", "tổng số lượng"],
    "gross_weight": ["gw", "g w", "gw kgs", "gw kg", "gross weight", "gross weight kgs", "gross wt", "毛重", "毛重kgs",
                     "trọng lượng cả bì", "tổng trọng lượng", "trọng lượng gross"],
    "net_weight": ["nw", "n w", "nw kgs", "nw kg", "net weight", "net weight kgs", "net wt", "净重",
                   "trọng lượng tịnh", "trọng lượng net"],
    "size": ["size", "sizes", "measurement", "meas", "measurements", "dimension", "dimensions", "cbm", "carton size",
             "尺码", "尺寸", "规格", "体积", "kích thước", "kích cỡ", "thể tích"],
}

SYNONYMS["po"] = SYNONYMS["po"] + ["master po", "master po no", "master po number", "burlington po", "customer po"]
SYNONYMS["quantity"] = SYNONYMS["quantity"] + ["order units", "ordered units", "order qty", "ordered qty", "units ordered"]
SYNONYMS.update({
    "asn": ["asn", "asn no", "asn number", "asn id", "web shipment id", "số asn", "mã asn"],
    "model_no": ["model", "model no", "model number", "vendor style", "sku", "sku no", "型号", "mã model"],
    "start_ship": ["edi po start ship", "start ship", "start ship date", "early ship date", "early ship",
                   "ship window start", "ngày bắt đầu giao"],
    "end_ship": ["edi po end ship", "end ship", "end ship date", "late ship date", "late ship", "ship window end",
                 "ngày kết thúc giao"],
    "pack": ["pack", "pack qty", "pack size", "inner pack", "qty per carton", "units per carton", "pcs per carton",
             "pcs ctn", "装箱数", "sl mỗi thùng"],
    "gw_per_carton": ["gross weight carton kg", "gross weight carton", "gw carton", "gw per carton",
                      "gross weight per carton", "carton gross weight", "gw ctn", "毛重 每箱", "trọng lượng mỗi thùng"],
    "container": ["container", "container no", "container number", "cntr", "柜号", "số container"],
    "edi_units": ["edi units", "edi qty", "edi quantity", "po units", "buyer units"],
    "factory": ["factory", "factory name", "vendor factory", "manufacturer", "supplier", "工厂", "nhà máy",
                "tên nhà máy"],
})
# A header containing any of these tokens can never map to that field (score forced to 0).
NEGATIVE_TOKENS: dict[str, tuple[str, ...]] = {
    "asn": ("submit",),
    "po": ("transfer", "start", "end", "shyft"),
    "packages": ("weight", "gross"),
    "quantity": ("edi",),
    "factory": ("address", "code", "date", "x", "ready", "inspection", "price", "cost"),
}

_NORM = {k: [normalize_header(s) for s in v] for k, v in SYNONYMS.items()}


def field_scores(header_text: str) -> dict[str, float]:
    """Best synonym score per field for one header text."""
    h = normalize_header(header_text)
    out = {k: 0.0 for k in SYNONYMS}
    if not h:
        return out
    htoks = set(h.split())
    for key, syns in _NORM.items():
        best = 0.0
        if htoks & set(NEGATIVE_TOKENS.get(key, ())):
            continue
        for s in syns:
            if not s:
                continue
            if h == s:
                sc = 1.0
            elif set(s.split()) <= htoks:
                sc = 0.85
            elif len(s) >= 3 and (" " not in s or len(s) >= 5) and (s in h or (len(h) >= 3 and h in s)):
                sc = 0.7
            else:
                sc = 0.0
            best = max(best, sc)
        out[key] = best
    return out


def match_field(header_text: str) -> tuple[str | None, float]:
    scores = field_scores(header_text)
    key = max(scores, key=lambda k: scores[k])   # dict order breaks ties
    sc = scores[key]
    return (key, sc) if sc >= 0.7 else (None, sc)


def is_headerish(header_text: str) -> bool:
    return match_field(header_text)[1] >= 0.7
