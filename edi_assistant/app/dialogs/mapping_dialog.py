"""Column mapping editor with header preview and suggested columns."""
from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from edi_assistant.core.models import FIELD_KEYS, OPTIONAL_BY_PROFILE, PROFILES, REQUIRED_BY_PROFILE
from edi_assistant.data.mapping import ColumnMapping, ColumnRef, suggest_mapping

from ..strings import S

GREEN = QColor("#c8e6c9")
YELLOW = QColor("#fff4cc")


class MappingDialog(QDialog):
    def __init__(self, det, mapping: ColumnMapping, scores: dict[str, float],
                 preview_rows: list[dict[int, object]], template_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(S.MAPPING_TITLE)
        self.resize(900, 650)
        self._det = det
        self._combos: dict[str, QComboBox] = {}
        self._by_letter = {c.letter: c for c in det.columns}
        self._profile = mapping.profile if mapping.profile in PROFILES else PROFILES[0]
        self._letters: dict[str, str | None] = {k: (ref.letter if (ref := mapping.columns.get(k)) else None)
                                                for k in FIELD_KEYS}
        self._scores: dict[str, float] = dict(scores)

        lay = QVBoxLayout(self)
        prof_row = QWidget()
        ph = QHBoxLayout(prof_row)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.addWidget(QLabel(S.MAPPING_PROFILE))
        self.profile_combo = QComboBox()
        for p in PROFILES:
            self.profile_combo.addItem(S.PROFILE_LABELS.get(p, p), p)
        self.profile_combo.setCurrentIndex(max(self.profile_combo.findData(self._profile), 0))
        ph.addWidget(self.profile_combo)
        ph.addStretch(1)
        lay.addWidget(prof_row)
        lay.addWidget(QLabel(S.MAPPING_HINT))

        # field -> column table (ordered: required for the profile, optional, then the rest greyed)
        self.table = QTableWidget(len(FIELD_KEYS), 3)
        self.table.setHorizontalHeaderLabels([S.MAPPING_COL_FIELD, S.MAPPING_COL_COLUMN, S.MAPPING_COL_CONF])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.computed_note = QLabel("")
        self.computed_note.setWordWrap(True)
        self.computed_note.setStyleSheet("color:#1a73e8")
        self._populate_table()
        lay.addWidget(self.table, 3)
        lay.addWidget(self.computed_note)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        # header + data preview
        box = QGroupBox(S.MAPPING_PREVIEW)
        bl = QVBoxLayout(box)
        self.preview = QTableWidget(len(preview_rows), len(det.columns))
        self.preview.setHorizontalHeaderLabels([f"{c.letter}\n{c.joined}" for c in det.columns])
        for r, row in enumerate(preview_rows):
            for ci, c in enumerate(det.columns):
                v = row.get(c.col)
                self.preview.setItem(r, ci, QTableWidgetItem("" if v is None else str(v)))
        self.preview.resizeColumnsToContents()
        bl.addWidget(self.preview)
        lay.addWidget(box, 2)

        form = QFormLayout()
        self.name_edit = QLineEdit(template_name)
        form.addRow(S.MAPPING_TEMPLATE_NAME, self.name_edit)
        self.remember = QCheckBox(S.MAPPING_REMEMBER)
        self.remember.setChecked(True)
        form.addRow("", self.remember)
        lay.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color:#d93025")
        lay.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    def field_order(self) -> list[str]:
        req = REQUIRED_BY_PROFILE[self._profile]
        opt = OPTIONAL_BY_PROFILE[self._profile]
        rest = [k for k in FIELD_KEYS if k not in req and k not in opt]
        return list(req) + [k for k in opt if k not in req] + rest

    def _populate_table(self) -> None:
        req = REQUIRED_BY_PROFILE[self._profile]
        opt = OPTIONAL_BY_PROFILE[self._profile]
        self._combos = {}
        labels = {**S.FIELD_LABELS, **S.PROFILE_FIELD_LABELS.get(self._profile, {})}
        hide_unused = self._profile == "po_tracker"   # PO tracker: show only the columns this format uses
        for r, key in enumerate(self.field_order()):
            label = labels.get(key, key) + (" *" if key in req else "")
            item = QTableWidgetItem(label)
            if key not in req and key not in opt:
                item.setForeground(QBrush(QColor("#8a8a8a")))
            self.table.setItem(r, 0, item)
            combo = QComboBox()
            combo.addItem(S.MAPPING_UNUSED, None)
            for c in self._det.columns:
                combo.addItem(f"{c.letter} — {c.joined}", c.letter)
            letter = self._letters.get(key)
            unused = key not in req and key not in opt
            self.table.setRowHidden(r, hide_unused and unused)
            if hide_unused and unused:
                letter = None   # e.g. Cartons / total G.W.: computed from the tracker, never read from a column
            if letter is not None:
                idx = combo.findData(letter)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            self._combos[key] = combo
            self.table.setCellWidget(r, 1, combo)
            score = float(self._scores.get(key, 0.0))
            conf = QTableWidgetItem(f"{score:.0%}" if score else "")
            if score >= 0.85:
                conf.setBackground(QBrush(GREEN))
            elif score >= 0.7:
                conf.setBackground(QBrush(YELLOW))
            self.table.setItem(r, 2, conf)
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(1, 380)
        note = S.MAPPING_COMPUTED.get(self._profile, "")
        self.computed_note.setText(note)
        self.computed_note.setVisible(bool(note))

    def _on_profile_changed(self, *_a) -> None:
        """New profile: refill every combo from suggest_mapping(det, profile) (earlier manual edits are dropped)."""
        self._profile = self.profile_combo.currentData()
        sugg, self._scores = suggest_mapping(self._det, self._profile)
        self._letters = {k: (ref.letter if (ref := sugg.columns.get(k)) else None) for k in FIELD_KEYS}
        self._populate_table()
        self.error_label.setText("")

    def current_mapping(self) -> ColumnMapping:
        by_letter = {c.letter: c for c in self._det.columns}
        cols: dict[str, ColumnRef | None] = {}
        for key in FIELD_KEYS:
            letter = self._combos[key].currentData()
            cols[key] = ColumnRef(letter=letter, header=by_letter[letter].joined) if letter in by_letter else None
        return ColumnMapping(columns=cols, profile=self._profile)

    def _on_accept(self) -> None:
        m = self.current_mapping()
        missing = m.missing_required()
        if missing:
            self.error_label.setText(S.MAPPING_MISSING.format(fields=", ".join(S.FIELD_LABELS.get(k, k) for k in missing)))
            return
        self.accept()

    def result(self) -> tuple[ColumnMapping, str]:  # type: ignore[override]
        return self.current_mapping(), self.name_edit.text().strip()

    def remember_layout(self) -> bool:
        return self.remember.isChecked()
