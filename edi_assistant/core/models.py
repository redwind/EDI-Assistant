"""Domain dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

FIELD_KEYS: tuple[str, ...] = ("po", "line", "description", "packages", "quantity",
                               "gross_weight", "net_weight", "size",
                               # v2 (PO tracker)
                               "asn", "model_no", "start_ship", "end_ship", "pack", "gw_per_carton", "container")
REQUIRED_FIELDS: tuple[str, ...] = ("po", "packages", "quantity", "gross_weight")   # = packing_list requirements
PROFILES: tuple[str, ...] = ("packing_list", "po_tracker")
REQUIRED_BY_PROFILE: dict[str, tuple[str, ...]] = {
    "packing_list": REQUIRED_FIELDS,
    "po_tracker": ("po", "line", "quantity", "pack", "gw_per_carton", "start_ship", "end_ship"),
}
OPTIONAL_BY_PROFILE: dict[str, tuple[str, ...]] = {
    "packing_list": ("line", "description", "net_weight", "size"),
    "po_tracker": ("asn", "model_no", "description", "container"),
}


@dataclass(slots=True)
class Flag:
    code: str
    message_vi: str
    severity: str = "warning"   # "info" | "warning" | "error"


@dataclass(slots=True)
class POLine:
    master_po: str
    line: int
    excel_row: int
    description: str = ""
    packages: Decimal = Decimal(0)
    quantity: Decimal = Decimal(0)
    gross_weight: Decimal = Decimal(0)
    net_weight: Decimal | None = None
    size: str = ""
    raw: dict[str, object] = field(default_factory=dict)
    flags: list[Flag] = field(default_factory=list)
    # v2 additive (PO tracker)
    line_no_text: str = ""
    model_no: str = ""
    order_units: Decimal | None = None
    pack_qty: Decimal | None = None
    gw_per_carton: Decimal | None = None
    start_ship: date | None = None
    end_ship: date | None = None
    existing_asn: str = ""
    container: str = ""
    source_row: int = 0
    selected: bool = True

    @property
    def window(self) -> "DateWindow | None":
        if self.start_ship is None or self.end_ship is None:
            return None
        if self.start_ship <= self.end_ship:
            return DateWindow(self.start_ship, self.end_ship)
        return DateWindow(self.end_ship, self.start_ship)

    @property
    def po_line_id(self) -> str:
        return f"{self.master_po}{self.line:02d}"

    @property
    def item_label(self) -> str:
        return f"PO{self.master_po}LN{self.line}"


@dataclass(slots=True)
class FactoryAddress:
    id: str
    name: str
    address1: str
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "CHINA"
    site_no: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CartonPlan:
    units_per_carton: Decimal
    qty_per_carton: int
    cartons_per_site: int
    prepack_units: int | None
    flags: list[Flag]
    web_rule: str = ""   # "" | "units" | "packs" | "prepack" | "unknown" | "mismatch"


@dataclass(slots=True)
class DateWindow:
    early: date
    late: date


@dataclass(slots=True)
class ShipDateResult:
    shipping_date: date
    window: DateWindow | None
    flags: list[Flag]


@dataclass(slots=True)
class PlannedLine:
    po_line: POLine
    weight_kg: Decimal
    weight_text: str
    carton: CartonPlan | None = None
    web_qty_ordered: Decimal | None = None
    web_um: str = ""
    status: str = "pending"
    error: str = ""


@dataclass(slots=True)
class ShipmentPlan:
    index: int
    label: str
    lines: list[PlannedLine]
    factory: FactoryAddress
    master_pos: list[str]
    shipping_date: date | None = None
    date_result: ShipDateResult | None = None
    po_windows: dict[str, DateWindow] = field(default_factory=dict)
    to_site_no: str = ""
    web_shipment_id: str = ""
    asn_shipment_id: str = ""
    status: str = "pending"
    flags: list[Flag] = field(default_factory=list)
    # v2 additive
    container: str = ""
    dates_source: str = "web"            # "excel" | "web"
    planned_ship_date: date | None = None
    writeback_done: bool = False


@dataclass(slots=True)
class RunPlan:
    run_id: str
    source_file: str
    sheet_name: str
    template_fingerprint: str
    shipments: list[ShipmentPlan]
    grouping: str
    dry_run: bool
    created_at: str
    profile: str = "packing_list"        # v2
    qty_strict: bool = False             # v2: True for po_tracker


@dataclass(slots=True)
class RunResult:
    run_id: str
    status: str
    shipments: list[ShipmentPlan]
    results_csv: str
    started_at: str
    finished_at: str
    error: str = ""
    ai_calls_used: int = 0
