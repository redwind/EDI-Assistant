"""Calibrate mode: list selector keys, highlight / pick / test / forget learned candidates."""
from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from edi_assistant.automation.commands import (
    CancelPick, Highlight, NavigateTo, OpenInspector, Pick, ReloadSelectors, TestKey,
)

from ..strings import S

QUICK_LINKS = ((S.CALIB_LINK_INBOX, "gateway/inbox.do"), (S.CALIB_LINK_NEW_SHIPMENT, "gateway/new_shipment.do"),
               (S.CALIB_LINK_DRAFTS, "gateway/drafts.do"))
UNVERIFIED_BG = QColor("#fff4cc")


def vars_from_inputs(po: str, site_no: str, row_key: str) -> dict[str, str]:
    """Build resolver variables from the free-text inputs."""
    v: dict[str, str] = {}
    po = po.strip()
    if po:
        v["po"] = po
        if po.isdigit() and len(po) == 9:
            v["master_po"] = po[:7]
            v["line"] = str(int(po[7:]))
            v["line2"] = po[7:]
            v["item_label"] = f"PO{po[:7]}LN{int(po[7:])}"
    if site_no.strip():
        v["site_no"] = site_no.strip()
    if row_key.strip():
        v["row_key"] = row_key.strip()
    return v


class CalibrateDialog(QDialog):
    def __init__(self, store, worker, bridge=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(S.CALIB_TITLE)
        self.resize(980, 620)
        self._store = store
        self._worker = worker

        self.page_filter = QComboBox()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(list(S.CALIB_COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.po = QLineEdit()
        self.po.setPlaceholderText("580367401")
        self.site_no = QLineEdit()
        self.row_key = QLineEdit()
        vars_box = QGroupBox(S.CALIB_VARS)
        vf = QFormLayout(vars_box)
        vf.addRow(S.CALIB_VAR_PO, self.po)
        vf.addRow(S.CALIB_VAR_SITE, self.site_no)
        vf.addRow(S.CALIB_VAR_ROWKEY, self.row_key)

        self.status = QLabel("")
        self.status.setWordWrap(True)

        row = QHBoxLayout()
        for label, slot in ((S.CALIB_HIGHLIGHT, self.highlight), (S.CALIB_PICK, self.pick),
                            (S.CALIB_CANCEL_PICK, self.cancel_pick), (S.CALIB_TEST, self.test_key),
                            (S.CALIB_FORGET, self.forget_learned), (S.CALIB_INSPECTOR, self.open_inspector)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        nav = QHBoxLayout()
        nav.addWidget(QLabel(S.CALIB_OPEN_PAGE))
        for label, path in QUICK_LINKS:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, p=path: self._worker.submit(NavigateTo(path=p)))
            nav.addWidget(b)
        nav.addStretch(1)

        top = QHBoxLayout()
        top.addWidget(QLabel(S.CALIB_PAGE_FILTER))
        top.addWidget(self.page_filter)
        top.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        lay.addWidget(vars_box)
        lay.addLayout(row)
        lay.addLayout(nav)
        lay.addWidget(self.status)

        self._load()
        self.page_filter.currentIndexChanged.connect(self._fill)
        if bridge is not None:
            bridge.calibration.connect(self.on_calibration)

    # --- data ---------------------------------------------------------------
    def _load(self) -> None:
        keys = list(self._store.keys())
        # unverified first, then by key
        keys.sort(key=lambda k: (k.verified, k.key))
        self._keys = keys
        pages = sorted({k.page for k in keys})
        self.page_filter.blockSignals(True)
        self.page_filter.clear()
        self.page_filter.addItem(S.CALIB_ALL_PAGES, "")
        for p in pages:
            self.page_filter.addItem(p, p)
        self.page_filter.blockSignals(False)
        self._fill()

    def _fill(self) -> None:
        page = self.page_filter.currentData() or ""
        rows = [k for k in self._keys if not page or k.page == page]
        self.table.setRowCount(len(rows))
        for r, k in enumerate(rows):
            learned = sum(1 for c in k.candidates if c.source == "learned")
            vals = (k.key, k.page, "✓" if k.verified else "✗", str(learned), k.description)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if not k.verified:
                    it.setBackground(QBrush(UNVERIFIED_BG))
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()

    def refresh(self) -> None:
        try:
            self._store.load()
        except Exception:  # noqa: BLE001
            pass
        self._load()

    def current_key(self) -> str:
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.text() if it else ""

    def _vars(self) -> dict[str, str]:
        return vars_from_inputs(self.po.text(), self.site_no.text(), self.row_key.text())

    # --- actions ------------------------------------------------------------
    def highlight(self) -> None:
        if k := self.current_key():
            self._worker.submit(Highlight(key=k, vars=self._vars()))

    def pick(self) -> None:
        if k := self.current_key():
            self.status.setText(S.CALIB_WAITING)
            self._worker.submit(Pick(key=k))

    def cancel_pick(self) -> None:
        self._worker.submit(CancelPick())
        self.status.setText("")

    def test_key(self) -> None:
        if k := self.current_key():
            self._worker.submit(TestKey(key=k, vars=self._vars()))

    def forget_learned(self) -> None:
        k = self.current_key()
        if not k:
            return
        for c in list(self._store.get(k).candidates):
            if c.source == "learned":
                self._store.remove_learned(k, c.describe())
        self._worker.submit(ReloadSelectors())
        self.refresh()

    def open_inspector(self) -> None:
        self._worker.submit(OpenInspector())

    def on_calibration(self, ev) -> None:
        if ev.candidate is None:
            self.status.setText(S.CALIB_CANCELLED)
        else:
            self.status.setText(S.CALIB_SAVED.format(key=ev.key))
        self.refresh()
