"""Factory list editor / picker."""
from __future__ import annotations

import dataclasses
import uuid

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from edi_assistant.core.models import FactoryAddress

from ..strings import S

COUNTRIES = ["CHINA", "VIETNAM", "UNITED STATES", "CANADA", "INDIA", "BANGLADESH", "CAMBODIA", "INDONESIA"]


class FactoryDialog(QDialog):
    def __init__(self, store, prefill: FactoryAddress | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(S.FACTORY_TITLE)
        self.resize(820, 480)
        self._store = store
        self._current_id = ""
        self._selected: FactoryAddress | None = None

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_pick)
        self.name = QLineEdit()
        self.addr1 = QLineEdit()
        self.addr2 = QLineEdit()
        self.city = QLineEdit()
        self.state = QLineEdit()
        self.zip = QLineEdit()
        self.country = QComboBox()
        self.country.setEditable(True)
        self.country.addItems(COUNTRIES)
        self.site_no = QLineEdit()
        self.aliases = QLineEdit()
        form = QFormLayout()
        for label, w in ((S.FACTORY_NAME, self.name), (S.FACTORY_ADDR1, self.addr1), (S.FACTORY_ADDR2, self.addr2),
                         (S.FACTORY_CITY, self.city), (S.FACTORY_STATE, self.state), (S.FACTORY_ZIP, self.zip),
                         (S.FACTORY_COUNTRY, self.country), (S.FACTORY_SITE_NO, self.site_no),
                         (S.FACTORY_ALIASES, self.aliases)):
            form.addRow(label, w)
        btn_new = QPushButton(S.BTN_NEW)
        btn_new.clicked.connect(self._new)
        btn_save = QPushButton(S.BTN_SAVE)
        btn_save.clicked.connect(self._save)
        btn_del = QPushButton(S.BTN_DELETE)
        btn_del.clicked.connect(self._delete)
        row = QHBoxLayout()
        for b in (btn_new, btn_save, btn_del):
            row.addWidget(b)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(row)
        right.addStretch(1)
        body = QHBoxLayout()
        body.addWidget(self.list, 1)
        body.addLayout(right, 2)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(S.BTN_CHOOSE)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(S.BTN_CANCEL)
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addWidget(self.buttons)

        self._reload()
        if prefill is not None:
            if prefill.id and self._select_id(prefill.id):
                pass
            else:
                self._fill(prefill)
                self._current_id = prefill.id
        elif self.list.count():
            self.list.setCurrentRow(0)

    # --- list/form plumbing ------------------------------------------------
    def _reload(self, select_id: str = "") -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for f in self._store.list():
            it = QListWidgetItem(f.name)
            it.setData(256, f.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if select_id:
            self._select_id(select_id)

    def _select_id(self, fid: str) -> bool:
        for i in range(self.list.count()):
            if self.list.item(i).data(256) == fid:
                self.list.setCurrentRow(i)
                return True
        return False

    def _on_pick(self, item, _prev=None) -> None:
        if item is None:
            return
        f = self._store.get(item.data(256))
        if f is not None:
            self._fill(f)
            self._current_id = f.id

    def _fill(self, f: FactoryAddress) -> None:
        self.name.setText(f.name)
        self.addr1.setText(f.address1)
        self.addr2.setText(f.address2)
        self.city.setText(f.city)
        self.state.setText(f.state)
        self.zip.setText(f.zip)
        self.country.setCurrentText(f.country or "CHINA")
        self.site_no.setText(f.site_no)
        self.aliases.setText(", ".join(f.aliases))

    def _form_value(self) -> FactoryAddress:
        return FactoryAddress(
            id=self._current_id, name=self.name.text().strip(), address1=self.addr1.text().strip(),
            address2=self.addr2.text().strip(), city=self.city.text().strip(), state=self.state.text().strip(),
            zip=self.zip.text().strip(), country=self.country.currentText().strip().upper() or "CHINA",
            site_no=self.site_no.text().strip(),
            aliases=[a.strip() for a in self.aliases.text().split(",") if a.strip()])

    def _new(self) -> None:
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self._current_id = ""
        self._fill(FactoryAddress(id="", name="", address1=""))

    def _save(self) -> bool:
        f = self._form_value()
        if not f.name or not f.address1:
            QMessageBox.warning(self, S.APP_TITLE, S.FACTORY_NEED_NAME)
            return False
        if not f.id:
            f = dataclasses.replace(f, id=uuid.uuid4().hex)
        self._store.upsert(f)
        self._current_id = f.id
        self._reload(f.id)
        return True

    def _delete(self) -> None:
        if not self._current_id:
            return
        if QMessageBox.question(self, S.APP_TITLE, S.FACTORY_CONFIRM_DELETE) == QMessageBox.StandardButton.Yes:
            self._store.delete(self._current_id)
            self._current_id = ""
            self._reload()
            self._new()

    def _on_accept(self) -> None:
        if self._save():
            self._selected = self._store.get(self._current_id)
            self.accept()

    def selected(self) -> FactoryAddress | None:
        return self._selected
