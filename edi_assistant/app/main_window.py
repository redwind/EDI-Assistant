"""Main window: Excel -> mapping -> plan review -> run, with pauses handled via dialogs."""
from __future__ import annotations

import dataclasses
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from edi_assistant import APP_DISPLAY_NAME, __version__
from edi_assistant.core import paths
from edi_assistant.core.config import AppConfig, save_config
from edi_assistant.core.errors import EdiAssistantError, HeaderNotFoundError
from edi_assistant.core.events import UserResponse
from edi_assistant.core.models import FactoryAddress, RunPlan
from edi_assistant.data import (
    FactoryStore, PlanOptions, TemplateStore, apply_template_to_detection, build_plan, detect_header,
    extract_rows, list_sheets, load_grid, suggest_mapping, validate_mapping, write_back, writeback_path_for,
)
from edi_assistant.data.results import load_run_history
from edi_assistant.data.templates import compute_fingerprint

from . import autostart, browser_install, notifications
from .strings import S, language
from .ai import build_advisor
from .dialogs.calibrate_dialog import CalibrateDialog
from .dialogs.factory_dialog import FactoryDialog
from .dialogs.mapping_dialog import MappingDialog
from .dialogs.pause_dialog import PauseDialog
from .dialogs.settings_dialog import SettingsDialog
from .widgets.log_view import LogView
from .widgets.plan_table import PlanTable
from .widgets.steps_view import StepsView

log = logging.getLogger(__name__)
_PREVIEW_FACTORY = FactoryAddress(id="", name="", address1="")  # placeholder for the review table only


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, worker, bridge, *, template_store=None, factory_store=None,
                 startup_checks: bool = False, open_mapping_on_load: bool = True):
        super().__init__()
        self.cfg = cfg
        self.worker = worker
        self.bridge = bridge
        self.tray = None  # set by main() after construction
        self.templates = template_store or TemplateStore()
        self.factories = factory_store or FactoryStore()
        self._open_mapping_on_load = open_mapping_on_load
        self._quitting = False
        self._pause_dialogs: dict[str, PauseDialog] = {}
        self._reset_file_state()

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._build_menu()
        self._connect_bridge()
        self.refresh_history()
        self._update_buttons()
        if startup_checks:
            QTimer.singleShot(0, self._startup_check)

    # ------------------------------------------------------------------ state
    def _reset_file_state(self) -> None:
        self.path: Path | None = None
        self.sheet = ""
        self.grid = None
        self.det = None
        self.mapping = None
        self.scores: dict[str, float] = {}
        self.match = None
        self.fingerprint = ""
        self.mapping_confirmed = False
        self.remember_layout = True
        self.template_name = ""
        self.rx = None
        self.preview_plan = None
        self.run_plan = None
        self.company_text = ""
        self._writeback_ids: dict[int, str] = {}
        self._writeback_rows: dict[int, set[int]] = {}
        self._writeback_path: Path | None = None

    # --------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), S.TAB_MAIN)
        self.log_view = LogView()
        tabs.addTab(self.log_view, S.TAB_LOG)
        tabs.addTab(self._build_history_tab(), S.TAB_HISTORY)
        self.tabs = tabs
        self.setCentralWidget(tabs)

    def _build_main_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        # Excel group
        g1 = QGroupBox(S.GRP_EXCEL)
        h1 = QHBoxLayout(g1)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        btn_choose = QPushButton(S.BTN_CHOOSE_FILE)
        btn_choose.clicked.connect(self.choose_file)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self._on_sheet_changed)
        self.template_status = QLabel(S.STATUS_NO_FILE)
        self.btn_mapping = QPushButton(S.BTN_EDIT_MAPPING)
        self.btn_mapping.clicked.connect(self.edit_mapping)
        h1.addWidget(self.path_edit, 3)
        h1.addWidget(btn_choose)
        h1.addWidget(QLabel(S.LBL_SHEET))
        h1.addWidget(self.sheet_combo, 1)
        h1.addWidget(self.template_status, 2)
        h1.addWidget(self.btn_mapping)
        lay.addWidget(g1)

        # factory group
        g2 = QGroupBox(S.GRP_FACTORY)
        h2 = QHBoxLayout(g2)
        self.factory_combo = QComboBox()
        self.factory_combo.currentIndexChanged.connect(self._on_factory_changed)
        btn_factory = QPushButton(S.BTN_EDIT_FACTORY)
        btn_factory.clicked.connect(self.edit_factories)
        self.btn_import_factories = QPushButton(S.BTN_IMPORT_FACTORIES)
        self.btn_import_factories.clicked.connect(self.import_factories)
        self.btn_import_factories.setToolTip(S.FACTORY_IMPORT_TIP.format(file=self.cfg.ui.last_factory_xlsx or "-"))
        self.factory_hint = QLabel("")
        self.factory_hint.setWordWrap(True)
        h2.addWidget(self.factory_combo, 2)
        h2.addWidget(btn_factory)
        h2.addWidget(self.btn_import_factories)
        h2.addWidget(self.factory_hint, 3)
        lay.addWidget(g2)
        self._reload_factories()

        # options group
        g3 = QGroupBox(S.GRP_OPTIONS)
        h3 = QHBoxLayout(g3)
        self.rb_file = QRadioButton(S.OPT_PER_FILE)
        self.rb_master = QRadioButton(S.OPT_PER_MASTER_PO)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_file)
        grp.addButton(self.rb_master)
        self.cb_dry = QCheckBox(S.OPT_DRY_RUN)
        self.cb_writeback = QCheckBox(S.OPT_WRITE_BACK)
        self._sync_options_from_cfg()
        for wd in (self.rb_file, self.rb_master, self.cb_dry, self.cb_writeback):
            h3.addWidget(wd)
        h3.addStretch(1)
        self.rb_file.toggled.connect(self._rebuild_plan)
        self.cb_dry.toggled.connect(self._rebuild_plan)
        lay.addWidget(g3)

        self.plan_table = PlanTable()
        self.plan_table.selection_changed.connect(self._on_selection_changed)
        lay.addWidget(self.plan_table, 3)

        # buttons
        h4 = QHBoxLayout()
        # Start entry opens the browser and logs in by itself (saved login), so there is no separate
        # "Open browser" step here any more; the tray menu still has it for looking at the site by hand.
        self.btn_start = QPushButton(S.BTN_START)
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self.start_run)
        self.btn_abort = QPushButton(S.BTN_ABORT)
        self.btn_abort.clicked.connect(self.abort_run)
        for b in (self.btn_start, self.btn_abort):
            h4.addWidget(b)
        h4.addStretch(1)
        lay.addLayout(h4)

        self.steps = StepsView()
        lay.addWidget(self.steps, 2)
        return w

    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.history = QTableWidget(0, len(S.HISTORY_COLUMNS))
        self.history.setHorizontalHeaderLabels(list(S.HISTORY_COLUMNS))
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.history)
        h = QHBoxLayout()
        b1 = QPushButton(S.BTN_OPEN_FOLDER)
        b1.clicked.connect(lambda: self._open_history("dir"))
        b2 = QPushButton(S.BTN_OPEN_CSV)
        b2.clicked.connect(lambda: self._open_history("csv"))
        h.addWidget(b1)
        h.addWidget(b2)
        h.addStretch(1)
        lay.addLayout(h)
        return w

    def _build_menu(self) -> None:
        mb = self.menuBar()

        def add(menu, text, slot):
            a = QAction(text, self)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m1 = mb.addMenu(S.MENU_FILE)
        add(m1, S.MENU_OPEN_EXCEL, self.choose_file)
        add(m1, S.MENU_IMPORT_FACTORIES, self.import_factories)
        add(m1, S.MENU_EXIT, self.request_quit)
        m2 = mb.addMenu(S.MENU_TOOLS)
        add(m2, S.MENU_SETTINGS, self.open_settings)
        add(m2, S.MENU_CALIBRATE, self.open_calibrate)
        add(m2, S.MENU_INSPECTOR, self.open_inspector)
        add(m2, S.MENU_INSTALL_CHROMIUM, self.install_chromium)
        add(m2, S.MENU_OPEN_DATA, lambda: self._open_path(paths.user_data_dir()))
        m3 = mb.addMenu(S.MENU_HELP)
        add(m3, S.MENU_GUIDE, self.open_guide)
        add(m3, S.MENU_SYSTEM_CHECK, self.open_system_check)
        add(m3, S.MENU_ABOUT, self.show_about)

    def _connect_bridge(self) -> None:
        b = self.bridge
        b.log.connect(self.log_view.on_log)
        b.step_started.connect(self.steps.on_step_started)
        b.step_finished.connect(self.steps.on_step_finished)
        b.progress.connect(self.steps.on_progress)
        b.needs_user.connect(self._on_needs_user)
        b.run_finished.connect(self._on_run_finished)
        b.run_started.connect(self._on_run_started)
        b.shipment_created.connect(self._on_shipment_created)
        b.browser_state.connect(self._on_browser_state)

    # ------------------------------------------------------------- cfg <-> UI
    def _sync_options_from_cfg(self) -> None:
        (self.rb_master if self.cfg.flow.grouping == "per_master_po" else self.rb_file).setChecked(True)
        self.cb_dry.setChecked(self.cfg.flow.dry_run)
        self.cb_writeback.setChecked(self.cfg.flow.write_back_excel)

    def _sync_cfg_from_options(self) -> None:
        self.cfg.flow.grouping = "per_master_po" if self.rb_master.isChecked() else "per_file"
        self.cfg.flow.dry_run = self.cb_dry.isChecked()
        self.cfg.flow.write_back_excel = self.cb_writeback.isChecked()

    def _profile(self) -> str:
        return self.mapping.profile if self.mapping is not None else "packing_list"

    def _plan_options(self) -> PlanOptions:
        return PlanOptions("per_master_po" if self.rb_master.isChecked() else "per_file",
                           self.cb_dry.isChecked(), self.cfg.flow.weight_mode, profile=self._profile(),
                           tracker_weight_mode=self.cfg.flow.tracker_weight_mode, to_sites=self.cfg.flow.to_sites)

    def _apply_profile_ui(self) -> None:
        """PO-tracker files always create one shipment per master PO: force the radio and disable it."""
        forced = self._profile() == "po_tracker"
        if forced:
            self.rb_master.setChecked(True)
        for rb in (self.rb_file, self.rb_master):
            rb.setEnabled(not forced)
            rb.setToolTip(S.OPT_GROUPING_FORCED if forced else "")

    def _set_status(self, text: str) -> None:
        if self.mapping is not None and self.det is not None:
            text += " | " + S.STATUS_PROFILE.format(profile=S.PROFILE_LABELS.get(self._profile(), self._profile()))
        self.template_status.setText(text)

    # ------------------------------------------------------------ Excel flow
    def choose_file(self) -> None:
        start = self.cfg.ui.last_excel_dir or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(self, S.DLG_CHOOSE_EXCEL, start, S.FILTER_EXCEL)
        if fn:
            self.load_excel(Path(fn))

    def load_excel(self, path: Path) -> None:
        """Run the §3.17 sequence; errors become a Vietnamese message box."""
        try:
            sheets = list_sheets(path)
            if not sheets:
                raise EdiAssistantError("no sheets", message_vi=S.ERR_NO_SHEETS)
            sheet = self._first_sheet_with_header(path, sheets)
        except EdiAssistantError as e:
            self._show_error(e)
            return
        except Exception as e:  # noqa: BLE001
            self._show_error(e)
            return
        self._reset_file_state()
        self.path = path
        self.cfg.ui.last_excel_dir = str(path.parent)
        self.path_edit.setText(str(path))
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheets)
        self.sheet_combo.setCurrentText(sheet)
        self.sheet_combo.blockSignals(False)
        self._load_sheet(sheet)

    @staticmethod
    def _first_sheet_with_header(path: Path, sheets: list[str]) -> str:
        for s in sheets:
            try:
                detect_header(load_grid(path, s))
                return s
            except HeaderNotFoundError:
                continue
        return sheets[0]

    def _on_sheet_changed(self, sheet: str) -> None:
        if sheet and self.path is not None and sheet != self.sheet:
            self._load_sheet(sheet)

    def _load_sheet(self, sheet: str) -> None:
        self.sheet = sheet
        self.rx = self.preview_plan = self.run_plan = None
        self.mapping_confirmed = False
        try:
            self.grid = load_grid(self.path, sheet)
            self.det = detect_header(self.grid)
        except Exception as e:  # noqa: BLE001
            self.grid = self.det = self.mapping = None
            self.template_status.setText(S.STATUS_NO_HEADER)
            self.plan_table.clear_plan()
            self._update_buttons()
            self._show_error(e)
            return
        self.fingerprint, _ = compute_fingerprint(self.det)
        suggested, self.scores = suggest_mapping(self.det)
        self.match = self.templates.find(self.det)
        if self.match is not None:
            self.mapping = apply_template_to_detection(self.match.template, self.det)
            self.template_name = self.match.template.name
        else:
            self.mapping = suggested
            self.template_name = self.path.stem if self.path else ""
        if self.match is not None and self.match.kind == "exact" and self.mapping.is_complete():
            self.mapping_confirmed = True
            self._set_status(S.STATUS_TEMPLATE_EXACT.format(name=self.match.template.name))
        elif self.match is not None:
            self._set_status(S.STATUS_TEMPLATE_SIMILAR.format(name=self.match.template.name))
        else:
            self._set_status(S.STATUS_TEMPLATE_NEW)
        self._extract_and_preview()
        if not self.mapping_confirmed and self._open_mapping_on_load:
            QTimer.singleShot(0, self.edit_mapping)

    def edit_mapping(self) -> None:
        if self.det is None or self.mapping is None:
            return
        first = self.det.data_start_row
        last = min(self.grid.max_row, first + 4)
        preview = [self.grid.row_values(r) for r in range(first, last + 1)]
        dlg = MappingDialog(self.det, self.mapping, self.scores, preview, self.template_name, self)
        if dlg.exec():
            self.mapping, self.template_name = dlg.result()
            self.remember_layout = dlg.remember_layout()
            self.mapping_confirmed = True
            self._set_status(S.STATUS_MAPPING_CONFIRMED)
            self._extract_and_preview()

    def _extract_and_preview(self) -> None:
        """Extract rows with the current mapping and refresh the review table."""
        self.rx = self.preview_plan = None
        if self.mapping is not None and self.mapping.is_complete():
            try:
                validate_mapping(self.mapping)
                self.rx = extract_rows(self.grid, self.det, self.mapping)
            except Exception as e:  # noqa: BLE001
                self._show_error(e)
        if self.rx is not None:
            self.company_text = self.rx.company_text
            self.factory_hint.setText(S.LBL_FACTORY_HINT.format(text=self.rx.company_text) if self.rx.company_text
                                      else S.LBL_FACTORY_PICK_RUN)
            self._autoselect_factory()
        self._apply_profile_ui()
        self._rebuild_plan()

    def _rebuild_plan(self, *_args) -> None:
        if self.rx is None or not self.rx.lines:
            self.plan_table.clear_plan()
            self._update_buttons()
            return
        lines = self.rx.lines
        try:
            if not any(ln.selected for ln in lines):   # nothing ticked: show the table, Start stays disabled
                self.preview_plan = None
                self.plan_table.set_plan(RunPlan(run_id="", source_file=str(self.path), sheet_name=self.sheet,
                                                 template_fingerprint=self.fingerprint, shipments=[],
                                                 grouping="", dry_run=False, created_at=""), lines)
                self._update_buttons()
                return
            self.preview_plan = build_plan(lines, self._current_factory() or _PREVIEW_FACTORY,
                                           self._plan_options(), str(self.path), self.sheet, self.fingerprint)
            self.plan_table.set_plan(self.preview_plan, lines)
        except Exception as e:  # noqa: BLE001
            self.preview_plan = None
            self.plan_table.clear_plan()
            self._show_error(e)
        self._update_buttons()

    def _on_selection_changed(self, master_po: str, checked: bool) -> None:
        if self.rx is None:
            return
        for ln in self.rx.lines:
            if ln.master_po == master_po:
                ln.selected = checked
        self._rebuild_plan()

    # -------------------------------------------------------------- factories
    def _reload_factories(self, select_id: str = "") -> None:
        self.factory_combo.blockSignals(True)
        cur = select_id or self.factory_combo.currentData() or ""
        self.factory_combo.clear()
        self.factory_combo.addItem(S.FACTORY_NONE, "")
        for f in self.factories.list():
            self.factory_combo.addItem(f.name, f.id)
        i = self.factory_combo.findData(cur or self.cfg.ui.last_factory_id)
        self.factory_combo.setCurrentIndex(max(i, 0))
        self.factory_combo.blockSignals(False)

    def _autoselect_factory(self) -> None:
        f = None
        if self.rx and self.rx.company_text:
            f, _score = self.factories.suggest(self.rx.company_text)
            self.factory_hint.setText((S.LBL_FACTORY_HINT if f is not None else S.LBL_FACTORY_NOT_FOUND)
                                      .format(text=self.rx.company_text))
        if f is None and self.path is not None:
            f = self.factories.by_file_code(self.path.name)
        if f is None and self.match is not None and self.match.template.factory_id:
            f = self.factories.get(self.match.template.factory_id)
        if f is not None:
            i = self.factory_combo.findData(f.id)
            if i >= 0:
                self.factory_combo.setCurrentIndex(i)

    def _current_factory(self) -> FactoryAddress | None:
        fid = self.factory_combo.currentData()
        return self.factories.get(fid) if fid else None

    def _on_factory_changed(self, *_a) -> None:
        fid = self.factory_combo.currentData() or ""
        self.cfg.ui.last_factory_id = fid
        self._rebuild_plan()

    def edit_factories(self) -> None:
        prefill = self._current_factory()
        if prefill is None and self.company_text:
            from edi_assistant.data.factories import factory_from_excel_footer
            prefill = factory_from_excel_footer(self.company_text)
        dlg = FactoryDialog(self.factories, prefill, self)
        accepted = dlg.exec()
        sel = dlg.selected() if accepted else None
        self._reload_factories(sel.id if sel else "")
        self._rebuild_plan()

    def import_factories(self) -> None:
        """Load/refresh the factory list from an Excel workbook (add new, update existing by name)."""
        from edi_assistant.data.factories import read_factories_xlsx

        last = self.cfg.ui.last_factory_xlsx
        start = last if last else (self.cfg.ui.last_excel_dir or str(Path.home()))
        fn, _ = QFileDialog.getOpenFileName(self, S.FACTORY_IMPORT_TITLE, start, "Excel (*.xlsx *.xlsm)")
        if not fn:
            return
        try:
            items = read_factories_xlsx(fn)
        except Exception as e:  # noqa: BLE001
            self._show_error(e)
            return
        name = Path(fn).name
        if not items:
            QMessageBox.warning(self, S.APP_TITLE, S.FACTORY_IMPORT_EMPTY.format(file=name))
            return
        added, updated = self.factories.merge(items)
        self.cfg.ui.last_factory_xlsx = fn
        self.btn_import_factories.setToolTip(S.FACTORY_IMPORT_TIP.format(file=fn))
        try:
            save_config(self.cfg)
        except Exception:  # noqa: BLE001
            pass
        self._reload_factories()
        if self.rx is not None:
            self._autoselect_factory()
        self._rebuild_plan()
        QMessageBox.information(self, S.APP_TITLE, S.FACTORY_IMPORT_DONE.format(
            file=name, added=added, updated=updated, total=len(self.factories.list())))

    # -------------------------------------------------------------------- run
    def can_start(self) -> bool:
        return (self.preview_plan is not None and self.mapping_confirmed and not self.plan_table.has_errors()
                and not self.worker.is_running)

    def _update_buttons(self) -> None:
        running = bool(self.worker.is_running)
        self.btn_start.setEnabled(self.can_start())
        self.btn_abort.setEnabled(running)
        self.btn_mapping.setEnabled(self.det is not None and not running)

    def start_run(self) -> None:
        factory = self._current_factory()
        if factory is None:
            QMessageBox.warning(self, S.APP_TITLE, S.ERR_NO_FACTORY)
            return
        if self.rx is None or not any(ln.selected for ln in self.rx.lines):
            QMessageBox.warning(self, S.APP_TITLE, S.ERR_NO_SELECTION)
            return
        try:
            validate_mapping(self.mapping)
            plan = build_plan(self.rx.lines, factory, self._plan_options(), str(self.path), self.sheet,
                              self.fingerprint)
        except Exception as e:  # noqa: BLE001
            self._show_error(e)
            return
        if self.remember_layout:
            self.templates.learn(self.det, self.mapping, self.template_name or (self.path.stem if self.path else ""),
                                 factory.id, self.sheet)
        self.factories.upsert(factory)
        self._sync_cfg_from_options()
        self.cfg.ui.last_factory_id = factory.id or self.cfg.ui.last_factory_id
        self.cfg.ui.last_profile = self._profile()
        try:
            save_config(self.cfg)   # the last factory survives a crash
        except Exception as e:  # noqa: BLE001
            log.warning("save_config failed: %s", e)
        self.worker.update_config(self.cfg)
        self.run_plan = plan
        self._writeback_ids = {}
        self._writeback_rows = {}
        self._writeback_path = writeback_path_for(plan)
        self.steps.clear()
        from edi_assistant.automation.commands import RunPlanCommand
        self.worker.submit(RunPlanCommand(plan=plan))
        self._update_buttons()

    def abort_run(self) -> None:
        self.worker.request_abort()

    def open_browser(self) -> None:
        from edi_assistant.automation.commands import OpenBrowser
        self.worker.submit(OpenBrowser())

    def open_inspector(self) -> None:
        from edi_assistant.automation.commands import OpenInspector
        self.worker.submit(OpenInspector())

    # --------------------------------------------------------- worker events
    def _notify(self, title: str, text: str, warn: bool = False) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon
        icon = QSystemTrayIcon.MessageIcon.Warning if warn else QSystemTrayIcon.MessageIcon.Information
        notifications.notify(self.tray, title, text, sound=self.cfg.notify.sound, balloon=self.cfg.notify.balloon,
                             icon=icon)

    def _on_run_started(self, _ev) -> None:
        self._update_buttons()

    def _on_browser_state(self, _ev) -> None:
        self._update_buttons()

    def _on_needs_user(self, ev) -> None:
        if ev.kind == "finished_review":
            self._notify(S.APP_TITLE, S.NOTIFY_FILLED_DONE)
        else:
            self._notify(S.APP_TITLE, f"{S.NOTIFY_NEEDS_USER}: {ev.message_vi[:200]}", warn=True)
            self.show_and_raise()
        dlg = PauseDialog(ev, self)
        self._pause_dialogs[ev.request_id] = dlg
        dlg.finished.connect(lambda _r, d=dlg, rid=ev.request_id: self._on_pause_finished(rid, d))
        dlg.open()

    def _on_pause_finished(self, request_id: str, dlg: PauseDialog) -> None:
        self._pause_dialogs.pop(request_id, None)
        resp = dlg.response() or UserResponse(request_id=request_id, action="abort")
        self.worker.respond(resp)
        dlg.deleteLater()

    def _write_back_now(self) -> Path | None:
        """Incremental / final write-back into the copy fixed at Start (never on dry runs)."""
        plan = self.run_plan
        if (not self.cfg.flow.write_back_excel or plan is None or plan.dry_run or self.det is None
                or not self._writeback_ids):
            return None
        try:
            out = write_back(plan, self.det, self.mapping, ids=self._writeback_ids, dst=self._writeback_path,
                             written=self._writeback_rows)
            self.log_view.append("INFO", S.LOG_WRITEBACK.format(path=out))
            return out
        except Exception as e:  # noqa: BLE001
            log.exception("write_back failed")
            self.log_view.append("ERROR", S.LOG_WRITEBACK_FAIL.format(err=e))
            return None

    def _on_shipment_created(self, ev) -> None:
        if not ev.web_shipment_id:
            return
        self._writeback_ids[ev.shipment_index] = ev.web_shipment_id
        out = self._write_back_now()
        if out is not None:
            self._notify(S.APP_TITLE, S.NOTIFY_SHIPMENT_DONE.format(idx=ev.shipment_index, wid=ev.web_shipment_id,
                                                                    path=out))

    def _on_run_finished(self, ev) -> None:
        result = ev.result
        self._update_buttons()
        self.refresh_history()
        if result is None:
            return
        ids = [s.web_shipment_id for s in result.shipments if s.web_shipment_id]
        for s in result.shipments:   # ids from the result win over (or complete) the incremental ones
            if s.web_shipment_id:
                self._writeback_ids[s.index] = s.web_shipment_id
        if result.status != "dry_run":
            self._write_back_now()
        if result.status in ("done", "partial"):
            self._notify(S.APP_TITLE, S.NOTIFY_RUN_DONE.format(n=len(result.shipments), ids=", ".join(ids) or "-"))
        elif result.status == "dry_run":
            self._notify(S.APP_TITLE, S.NOTIFY_DRY_RUN_DONE)
        elif result.status == "aborted":
            self._notify(S.APP_TITLE, S.NOTIFY_RUN_ABORTED)
        else:
            self._notify(S.APP_TITLE, S.NOTIFY_RUN_FAILED.format(err=result.error[:150]), warn=True)

    # ---------------------------------------------------------------- history
    def refresh_history(self) -> None:
        try:
            runs = load_run_history()
        except Exception:  # noqa: BLE001
            runs = []
        self._runs = runs
        self.history.setRowCount(len(runs))
        for r, d in enumerate(runs):
            ships = d.get("shipments")
            ids = ", ".join(str(s.get("web_shipment_id")) for s in ships if isinstance(s, dict)
                            and s.get("web_shipment_id")) if isinstance(ships, list) else ""
            vals = (d.get("run_id", ""), d.get("started_at", ""), d.get("status", ""),
                    len(ships) if isinstance(ships, list) else "", ids)
            for c, v in enumerate(vals):
                self.history.setItem(r, c, QTableWidgetItem(str(v)))

    def _open_history(self, what: str) -> None:
        r = self.history.currentRow()
        if r < 0 or r >= len(self._runs):
            return
        d = self._runs[r]
        folder = Path(d.get("run_dir") or paths.run_dir(d.get("run_id", "")))
        self._open_path(folder if what == "dir" else Path(d.get("results_csv") or folder / "results.csv"))

    # ---------------------------------------------------------------- dialogs
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if not dlg.exec():
            return
        new = dlg.result_config()
        for f in dataclasses.fields(AppConfig):  # update in place: other objects hold a reference to cfg
            setattr(self.cfg, f.name, getattr(new, f.name))
        try:
            save_config(self.cfg)
        except Exception as e:  # noqa: BLE001
            self._show_error(e)
        self.worker.update_config(self.cfg)
        self.worker.set_advisor(build_advisor(self.cfg.ai))
        self._apply_autostart()
        self._sync_options_from_cfg()
        self._rebuild_plan()

    def _apply_autostart(self) -> None:
        """Write the HKCU Run entry; on failure (policy) warn gently, untick the option and keep running."""
        err = autostart.apply(self.cfg.notify.start_with_windows)
        if err is None:
            return
        log.warning("autostart failed: %s", err)
        self.cfg.notify.start_with_windows = False
        try:
            save_config(self.cfg)
        except Exception:  # noqa: BLE001
            pass
        QMessageBox.warning(self, S.APP_TITLE, S.AUTOSTART_BLOCKED)

    def open_system_check(self) -> None:
        from .dialogs.system_check_dialog import SystemCheckDialog
        SystemCheckDialog(self.cfg, self).exec()

    def open_calibrate(self) -> None:
        dlg = CalibrateDialog(self.worker.selectors, self.worker, self.bridge, self)
        dlg.show()
        self._calibrate = dlg

    def install_chromium(self) -> None:
        if browser_install.install_chromium(self):
            QMessageBox.information(self, S.APP_TITLE, S.INSTALL_CHROMIUM_OK)
            if not browser_install.edge_available():
                self.cfg.browser.channel = "chromium"
                self.worker.update_config(self.cfg)
        else:
            QMessageBox.warning(self, S.APP_TITLE, S.INSTALL_CHROMIUM_FAIL)

    def _startup_check(self) -> None:
        if not self.cfg.ui.system_check_done:   # first run: offer the system check once
            self.cfg.ui.system_check_done = True
            try:
                save_config(self.cfg)
            except Exception:  # noqa: BLE001
                pass
            if QMessageBox.question(self, S.APP_TITLE, S.ASK_SYSTEM_CHECK_FIRST_RUN) == QMessageBox.StandardButton.Yes:
                self.open_system_check()
                return
        if (self.cfg.browser.channel in ("auto", "msedge") and not browser_install.edge_available()
                and not browser_install.chromium_available()
                and not (self.cfg.browser.channel == "auto" and browser_install.chrome_available())):
            if QMessageBox.question(self, S.APP_TITLE, S.ASK_INSTALL_CHROMIUM) == QMessageBox.StandardButton.Yes:
                self.install_chromium()

    def open_guide(self) -> None:
        for base in (paths.exe_dir(), Path(__file__).resolve().parents[2], Path(getattr(sys, "_MEIPASS", "."))):
            names = ("README_VI.md", "README.md") if language() == "vi" else ("README.md", "README_VI.md")
            for name in names:
                p = base / name
                if p.is_file():
                    self._open_path(p)
                    return
        QMessageBox.information(self, S.APP_TITLE, S.ERR_GUIDE_MISSING)

    def show_about(self) -> None:
        QMessageBox.about(self, S.MENU_ABOUT, S.ABOUT_TEXT.format(name=APP_DISPLAY_NAME, version=__version__))

    # ------------------------------------------------------------------ misc
    @staticmethod
    def _open_path(p: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _show_error(self, e: BaseException) -> None:
        msg = getattr(e, "message_vi", "") or str(e)
        log.warning("error: %s", e)
        QMessageBox.warning(self, S.APP_TITLE, msg)

    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request_quit(self) -> None:
        if self.worker.is_running:
            if QMessageBox.question(self, S.APP_TITLE, S.CONFIRM_QUIT_RUNNING) != QMessageBox.StandardButton.Yes:
                return
        self._quitting = True
        for d in list(self._pause_dialogs.values()):
            d.force_close()
        self.close()
        QApplication.quit()

    def closeEvent(self, e) -> None:  # noqa: N802
        if not self._quitting and self.tray is not None and self.tray.isVisible():
            e.ignore()
            self.hide()
            self.tray.setToolTip(S.TRAY_TOOLTIP)
            return
        from .dialogs.system_check_dialog import wait_for_background
        wait_for_background()
        super().closeEvent(e)
