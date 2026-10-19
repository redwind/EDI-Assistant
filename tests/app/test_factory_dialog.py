from edi_assistant.app.dialogs.factory_dialog import FactoryDialog
from edi_assistant.core.models import FactoryAddress
from edi_assistant.data import FactoryStore


def test_add_select_roundtrip(qtbot):
    store = FactoryStore()
    prefill = FactoryAddress(id="", name="SUMEC TEXTILE COMPANY LIMITED", address1="68 Yunlongshan Road",
                             address2="Jianye District", city="Nanjing", country="CHINA")
    dlg = FactoryDialog(store, prefill)
    qtbot.addWidget(dlg)
    assert dlg.name.text() == prefill.name
    dlg.aliases.setText("Sumec, Sumec Textile ")
    dlg._on_accept()
    sel = dlg.selected()
    assert sel is not None and sel.id and sel.aliases == ["Sumec", "Sumec Textile"]
    assert store.get(sel.id).city == "Nanjing"
    # reopening preselects it
    dlg2 = FactoryDialog(store, sel)
    qtbot.addWidget(dlg2)
    assert dlg2.list.count() == 1 and dlg2.name.text() == prefill.name


def test_requires_name(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    dlg = FactoryDialog(FactoryStore())
    qtbot.addWidget(dlg)
    dlg._on_accept()
    assert dlg.selected() is None
