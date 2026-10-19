"""Review table of the planned PO lines, with a per-line selection checkbox (toggles the whole master PO)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem

from ..strings import S

# column 0 is the checkbox column (no data key)
COLUMNS = ("selected", "shipment_index", "po_line_id", "master_po", "line", "container", "model_no", "description",
           "packages", "units_per_carton", "quantity", "weight_text", "ship_date", "status_text", "flags_vi")
RED = QColor("#fbd5d1")
YELLOW = QColor("#fff4cc")
GREY = QColor("#eeeeee")
GREY_TEXT = QColor("#8a8a8a")
GROUP_ALT = QColor("#eef4fb")   # alternating background per shipment


class PlanTable(QTableWidget):
    selection_changed = Signal(str, bool)   # master_po, checked

    def __init__(self, parent=None):
        super().__init__(0, len(COLUMNS), parent)
        self.setHorizontalHeaderLabels(list(S.PLAN_COLUMNS))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self._meta: list[tuple[str, str]] = []   # per row: (master_po, severity)
        self.itemChanged.connect(self._on_item_changed)

    # ------------------------------------------------------------- filling
    def set_rows(self, rows: list[dict], severities: list[str] | None = None) -> None:
        """severities[i] in {'', 'warning', 'error'} colours row i; rows may carry 'selected' (default True)."""
        severities = severities or [""] * len(rows)
        self.blockSignals(True)
        self.setRowCount(len(rows))
        self._meta = [(str(r.get("master_po", "")), sev) for r, sev in zip(rows, severities)]
        group_no, last_group = -1, object()
        for r, (row, sev) in enumerate(zip(rows, severities)):
            selected = bool(row.get("selected", True))
            group = row.get("shipment_index", "")
            if group != last_group:
                group_no, last_group = group_no + 1, group
            existing = str(row.get("existing_asn", "") or "")
            status = (S.PLAN_STATUS_HAS_ASN.format(asn=existing) if existing
                      else S.PLAN_STATUS_UNSELECTED if not selected else "")
            for c, key in enumerate(COLUMNS):
                item = QTableWidgetItem()
                if key == "selected":
                    item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
                    item.setCheckState(Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)
                else:
                    item.setText(status if key == "status_text" else str(row.get(key, "")))
                if not selected:
                    item.setBackground(QBrush(GREY))
                    item.setForeground(QBrush(GREY_TEXT))
                elif sev == "error":
                    item.setBackground(QBrush(RED))
                elif sev == "warning":
                    item.setBackground(QBrush(YELLOW))
                elif group_no % 2 == 1 and group != "":
                    item.setBackground(QBrush(GROUP_ALT))
                self.setItem(r, c, item)
        self.blockSignals(False)
        self.resizeColumnsToContents()

    def set_plan(self, plan, all_lines=None) -> None:
        from edi_assistant.data import plan_summary_rows
        rows = plan_summary_rows(plan, all_lines)
        if all_lines is not None:
            lines = list(all_lines)
        else:
            lines = [pl.po_line for sp in plan.shipments for pl in sp.lines]
        sev = []
        for i in range(len(rows)):
            flags = lines[i].flags if i < len(lines) else []
            sev.append("error" if any(f.severity == "error" for f in flags)
                       else "warning" if any(f.severity == "warning" for f in flags) else "")
        self.set_rows(rows, sev)

    # ----------------------------------------------------------- selection
    def is_checked(self, row: int) -> bool:
        item = self.item(row, 0)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or not (0 <= item.row() < len(self._meta)):
            return
        master = self._meta[item.row()][0]
        checked = item.checkState() == Qt.CheckState.Checked
        self.blockSignals(True)
        for r, (m, _sev) in enumerate(self._meta):
            if m == master and r != item.row():
                it = self.item(r, 0)
                if it is not None:
                    it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.blockSignals(False)
        self.selection_changed.emit(master, checked)

    def selected_count(self) -> int:
        return sum(1 for r in range(self.rowCount()) if self.is_checked(r))

    def has_errors(self) -> bool:
        """Only SELECTED rows count: unticking a red row unblocks Start."""
        return any(sev == "error" and self.is_checked(r) for r, (_m, sev) in enumerate(self._meta))

    def clear_plan(self) -> None:
        self.set_rows([])
