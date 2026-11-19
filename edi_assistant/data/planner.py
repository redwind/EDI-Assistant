"""POLine list -> RunPlan (grouping, weights)."""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime

from edi_assistant.core.dc_sites import DEFAULT_TO_SITES, site_for, state_of
from edi_assistant.core.dates import compute_shipping_date, format_mdy, intersect
from edi_assistant.core.errors import PlanError
from edi_assistant.core.models import FactoryAddress, Flag, PlannedLine, POLine, RunPlan, ShipmentPlan
from edi_assistant.core.quantities import weight_for_line

from .profiles import default_weight_mode, forced_grouping
from .values import format_weight


@dataclass(slots=True)
class PlanOptions:
    grouping: str
    dry_run: bool
    weight_mode: str
    profile: str = "packing_list"
    tracker_weight_mode: str = "per_carton_as_is"
    today: date | None = None
    to_sites: dict[str, str] | None = None   # None = DEFAULT_TO_SITES


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def _to_site(sh: ShipmentPlan, lines: list[POLine], table: dict[str, str]) -> None:
    """TO Site No from the lines' Delivery Address (state -> site). No address column = leave it to the site."""
    addrs = list(dict.fromkeys(" ".join(ln.delivery_address.split()) for ln in lines if ln.delivery_address.strip()))
    if not addrs:
        return
    sites = list(dict.fromkeys(site_for(a, table) for a in addrs))
    if len(sites) > 1:
        sh.flags.append(Flag("multiple_dc", "Lines of this shipment go to different DCs: " + " | ".join(addrs), "error"))
        return
    if not sites[0]:
        st = state_of(addrs[0])
        why = f"state {st} is not in the TO Site No list (Settings)" if st else "no 'ST 12345' at the end"
        sh.flags.append(Flag("to_site_unknown", f"TO Site No unknown for \"{addrs[0]}\" ({why}) - pick it in the browser",
                             "warning"))
        return
    sh.to_site_no = sites[0]
    sh.delivery_address = addrs[0]
    sh.label = sh.label[:-1] + f", TO {sites[0]})" if sh.label.endswith(")") else sh.label


def _shipment(index: int, lines: list[POLine], factory: FactoryAddress, mode: str,
              today: date | None = None, to_sites: dict[str, str] | None = None) -> ShipmentPlan:
    pos: list[str] = []
    for ln in lines:
        if ln.master_po not in pos:
            pos.append(ln.master_po)
    planned = []
    for ln in lines:
        w = weight_for_line(ln, mode)
        planned.append(PlannedLine(po_line=ln, weight_kg=w, weight_text=format_weight(w)))
    container = next((ln.container for ln in lines if ln.container), "")
    label = f"Shipment {index} ({', '.join(pos)}{', ' + container if container else ''})"
    sh = ShipmentPlan(index=index, label=label, lines=planned, factory=factory, master_pos=pos,
                      container=container)
    _to_site(sh, lines, to_sites if to_sites is not None else DEFAULT_TO_SITES)
    windows = [ln.window for ln in lines if ln.window]
    if lines and len(windows) == len(lines):
        sh.dates_source = "excel"
        for master in pos:
            ws = [ln.window for ln in lines if ln.master_po == master]
            inter = intersect(ws)
            sh.po_windows[master] = inter or ws[0]
            if inter is None:
                sh.flags.append(Flag("no_date_intersection",
                                     f"Ship windows of the lines of PO {master} do not overlap; using the first line"))
        res = compute_shipping_date(list(sh.po_windows.values()), today or date.today())
        sh.planned_ship_date = res.shipping_date
        have = {g.code for g in sh.flags}
        sh.flags += [f for f in res.flags if f.code not in have]
    return sh


def build_plan(lines: list[POLine], factory: FactoryAddress, opts: PlanOptions, source_file: str,
               sheet_name: str, fingerprint: str, run_id: str | None = None) -> RunPlan:
    if not lines:
        raise PlanError("No PO lines to plan", message_vi="No PO lines to plan")
    sel = [ln for ln in lines if ln.selected]
    if not sel:
        raise PlanError("No PO lines selected",
                        message_vi="No PO lines selected (all lines already have an ASN?)")
    seen: set[str] = set()
    for ln in sel:
        if ln.po_line_id in seen:
            raise PlanError(f"Duplicate PO line: {ln.po_line_id}",
                            message_vi=f"Duplicate PO line: {ln.po_line_id}")
        seen.add(ln.po_line_id)
    grouping = forced_grouping(opts.profile, opts.grouping)
    mode = default_weight_mode(opts.profile, opts)
    if grouping == "per_master_po":
        groups: dict[str, list[POLine]] = {}
        for ln in sel:
            groups.setdefault(ln.master_po, []).append(ln)
        chunks = list(groups.values())
    else:
        chunks = [list(sel)]
    shipments = [_shipment(i, c, factory, mode, opts.today, opts.to_sites) for i, c in enumerate(chunks, 1)]
    return RunPlan(run_id=run_id or new_run_id(), source_file=source_file, sheet_name=sheet_name,
                   template_fingerprint=fingerprint, shipments=shipments, grouping=grouping,
                   dry_run=opts.dry_run, created_at=datetime.now().isoformat(timespec="seconds"),
                   profile=opts.profile, qty_strict=(opts.profile == "po_tracker"))


def _units_per_carton(ln: POLine) -> str:
    if ln.packages > 0:
        q = ln.quantity / ln.packages
        return str(int(q)) if q == q.to_integral_value() else f"{q:.2f}"
    return "?"


def _status_text(ln: POLine) -> str:
    if ln.existing_asn:
        return f"already has ASN {ln.existing_asn}"
    if not ln.selected:
        return "not selected"
    return ""


def plan_summary_rows(plan: RunPlan, all_lines: list[POLine] | None = None) -> list[dict]:
    rows = []

    def row(index, ln: POLine, weight_text: str, sh: ShipmentPlan | None) -> dict:
        return {
            "shipment_index": index, "po_line_id": ln.po_line_id, "master_po": ln.master_po,
            "line": ln.line, "description": ln.description, "packages": ln.packages,
            "quantity": ln.quantity, "units_per_carton": _units_per_carton(ln), "weight_text": weight_text,
            "flags_vi": "; ".join(f.message_vi for f in ln.flags),
            "selected": ln.selected, "container": ln.container, "model_no": ln.model_no,
            "existing_asn": ln.existing_asn,
            "ship_date": format_mdy(sh.planned_ship_date) if sh is not None and sh.planned_ship_date else "",
            "status_text": _status_text(ln),
        }

    in_plan: set[int] = set()
    for sh in plan.shipments:
        for pl in sh.lines:
            in_plan.add(id(pl.po_line))
            rows.append(row(sh.index, pl.po_line, pl.weight_text, sh))
    if all_lines is not None:
        # Rebuild in Excel order: planned lines keep their shipment, the others get shipment_index "".
        by_id = {r["po_line_id"]: r for r in rows if r["shipment_index"] != ""}
        merged = []
        for ln in all_lines:
            if id(ln) in in_plan:
                merged.append(by_id[ln.po_line_id])
            else:
                merged.append(row("", ln, "", None))
        return merged
    return rows
