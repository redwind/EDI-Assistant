"""results.csv / run.json writer and run history."""
from __future__ import annotations

import csv
import dataclasses
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from edi_assistant.core import paths
from edi_assistant.core.models import RunPlan, RunResult

HEADER = ["run_id", "excel_file", "shipment_index", "web_shipment_id", "asn_shipment_id", "po_line_id",
          "master_po", "line", "shipping_date", "qty_per_carton", "cartons_per_site", "weight_kg",
          "status", "flags", "container", "model_no", "excel_asn", "profile"]


def _default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


class ResultsWriter:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._dir = paths.run_dir(run_id)

    @property
    def csv_path(self) -> Path:
        return self._dir / "results.csv"

    def write(self, plan: RunPlan) -> Path:
        with open(self.csv_path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(HEADER)
            for sh in plan.shipments:
                for pl in sh.lines:
                    ln, c = pl.po_line, pl.carton
                    flags = [f.code for f in sh.flags] + [f.code for f in ln.flags]
                    if c:
                        flags += [f.code for f in c.flags]
                    w.writerow([plan.run_id, plan.source_file, sh.index, sh.web_shipment_id,
                                sh.asn_shipment_id, ln.po_line_id, ln.master_po, ln.line,
                                sh.shipping_date.isoformat() if sh.shipping_date else "",
                                c.qty_per_carton if c else "", c.cartons_per_site if c else "",
                                pl.weight_text, pl.status, ";".join(flags), ln.container, ln.model_no,
                                ln.existing_asn, plan.profile])
        return self.csv_path

    def write_json(self, result: RunResult) -> Path:
        p = self._dir / "run.json"
        p.write_text(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2, default=_default),
                     encoding="utf-8")
        return p


def load_run_history(limit: int = 50) -> list[dict]:
    out = []
    for d in sorted((p for p in paths.runs_dir().iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        f = d / "run.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data["run_dir"] = str(d)
        out.append(data)
        if len(out) >= limit:
            break
    return out
