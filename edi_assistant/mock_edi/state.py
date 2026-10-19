"""In-memory state of the mock EDI Gateway."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


# (po_line_id, qty_ordered, early, late, prepack) -- PO-tracker sample
TRACKER_SEED = [
    ("582067801", 1428, "30-NOV-26", "04-DEC-26", None), ("582067802", 960, "30-NOV-26", "04-DEC-26", None),
    ("582068001", 1650, "30-NOV-26", "04-DEC-26", None), ("582068002", 714, "30-NOV-26", "04-DEC-26", None),
    ("582068201", 1518, "30-NOV-26", "04-DEC-26", None), ("582067701", 2388, "09-NOV-26", "13-NOV-26", None),
    ("582067702", 330, "09-NOV-26", "13-NOV-26", None), ("582067901", 948, "30-NOV-26", "04-DEC-26", None),
    ("582068401", 158, "30-NOV-26", "04-DEC-26", 6),
]


@dataclass
class MockOrder:
    po_line_id: str                    # "580367401"
    order_id: int                      # internal id used in view_order.do?order_id=
    status: str                        # "ACKNOWLEDGED" | "SUBMITTED" | "REPLACED"
    early: str = "09-MAR-26"
    late: str = "13-MAR-26"
    qty_ordered: int = 510             # in AS when prepack, else units
    prepack: int | None = None         # 6 -> item row UM "AS", sub-row "6 EA"
    site_no: str = "512"
    site_addr: tuple[str, str, str, str] = ("570 EAST MILL STREET", "SAN BERNARDINO", "CA", "92408")
    versions: int = 2                  # inbox rows: versions-1 REPLACED (stricken) + 1 active
    read: bool = False
    ordered_in_packs: bool = False     # carton page shows qty_ordered == cartons, UM "EA", no prepack sub-row

    @property
    def master_po(self) -> str:
        return self.po_line_id[:7]

    @property
    def line_no(self) -> int:
        return int(self.po_line_id[7:])

    @property
    def item_label(self) -> str:
        return f"PO{self.master_po}LN{self.line_no}"


@dataclass
class MockShipment:
    shipment_id: int
    header: dict[str, str] = field(default_factory=dict)     # raw posted form fields
    pos: dict[str, dict] = field(default_factory=dict)       # po_line_id -> po_header_id/complete_partial/pack_code/status
    cartons: dict[str, dict] = field(default_factory=dict)   # po_line_id -> cart_def_id/items_added/sites_added/...
    weights: dict[str, dict] = field(default_factory=dict)   # po_line_id -> weight/um/site_wgt_id


@dataclass
class MockState:
    logged_in: bool = False
    profile_selected: bool = False
    orders: dict[str, MockOrder] = field(default_factory=dict)
    shipments: dict[int, MockShipment] = field(default_factory=dict)
    next_shipment_id: int = 792872
    next_po_header_id: int = 1001
    next_cart_def_id: int = 4263755
    next_site_wgt_id: int = 501
    next_order_id: int = 9001
    submit_called: bool = False
    submit_attempts: int = 0
    request_count: int = 0
    log: list[str] = field(default_factory=list)   # one line per state-changing request

    def add_order(self, po_line_id: str, status: str = "ACKNOWLEDGED", **kw) -> MockOrder:
        o = MockOrder(po_line_id=po_line_id, order_id=self.next_order_id, status=status, **kw)
        self.next_order_id += 1
        self.orders[po_line_id] = o
        return o

    def seed_default(self) -> None:
        self.add_order("580367401")
        self.add_order("580367301", status="SUBMITTED")
        self.add_order("580367402", status="REPLACED", versions=1)   # replaced-only
        self.add_order("668254501", qty_ordered=167, prepack=6)

    def seed_tracker(self) -> None:
        for i, (po, qty, early, late, prepack) in enumerate(TRACKER_SEED):
            self.add_order(po, status="ACKNOWLEDGED" if i % 2 == 0 else "SUBMITTED", qty_ordered=qty,
                           early=early, late=late, prepack=prepack, versions=1)

    def snapshot(self) -> dict:
        return {
            "logged_in": self.logged_in,
            "profile_selected": self.profile_selected,
            "submit_called": self.submit_called,
            "submit_attempts": self.submit_attempts,
            "orders": {k: asdict(v) for k, v in self.orders.items()},
            "shipments": {str(k): asdict(v) for k, v in self.shipments.items()},
            "log": list(self.log),
        }

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]
