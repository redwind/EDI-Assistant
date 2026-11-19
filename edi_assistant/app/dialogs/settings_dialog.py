"""Settings: site, browser, flow, AI provider, notifications."""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from edi_assistant.core.ai_interface import ExplainRequest
from edi_assistant.core.config import AI_PRESETS, AppConfig, config_from_dict, config_to_dict
from edi_assistant.core.dc_sites import DEFAULT_TO_SITES, format_table, parse_table
from edi_assistant.core.errors import EdiAssistantError

from ..strings import S
from ..ai import build_advisor

CUSTOM = "custom"


def _form_tab(rows: list[tuple[str, QWidget]]) -> QWidget:
    w = QWidget()
    f = QFormLayout(w)
    for label, widget in rows:
        f.addRow(label, widget)
    return w


def _combo(items: list[tuple[str, str]], current: str) -> QComboBox:
    c = QComboBox()
    for label, data in items:
        c.addItem(label, data)
    i = c.findData(current)
    if i >= 0:
        c.setCurrentIndex(i)
    return c


def _range_row(lo: int, hi: int, maximum: int) -> tuple[QWidget, QSpinBox, QSpinBox]:
    """'from [min] to [max]' pair of spin boxes."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    a, b = QSpinBox(), QSpinBox()
    for sp, v in ((a, lo), (b, hi)):
        sp.setRange(0, maximum)
        sp.setValue(int(v))
    h.addWidget(QLabel(S.PACE_MIN))
    h.addWidget(a)
    h.addWidget(QLabel(S.PACE_MAX))
    h.addWidget(b)
    h.addStretch(1)
    return w, a, b


def _pair(values, default: tuple[int, int]) -> tuple[int, int]:
    from ...automation.pace import as_range
    return as_range(values, default)


class SettingsDialog(QDialog):
    test_done = Signal(str, bool)

    def __init__(self, cfg: AppConfig, parent: QWidget | None = None,
                 advisor_factory: Callable | None = None):
        super().__init__(parent)
        self.setWindowTitle(S.SETTINGS_TITLE)
        self.resize(640, 560)
        self._base = config_from_dict(config_to_dict(cfg))  # work on a copy
        self._advisor_factory = advisor_factory or (lambda ai: build_advisor(ai, force=True))
        c = self._base

        tabs = QTabWidget()
        # --- site
        self.base_url = QLineEdit(c.site.base_url)
        self.use_mock = QCheckBox(S.SET_USE_MOCK)
        self.use_mock.setChecked(c.site.use_mock)
        self.mock_url = QLineEdit(c.site.mock_url)
        self.vendor = QLineEdit(c.site.vendor_profile_name)
        self.language = _combo([(S.LANGUAGE_LABELS[k], k) for k in ("en", "vi")], c.ui.language)
        self.language.setToolTip(S.SET_LANGUAGE_HELP)
        tabs.addTab(_form_tab([(S.SET_BASE_URL, self.base_url), ("", self.use_mock), (S.SET_MOCK_URL, self.mock_url),
                               (S.SET_VENDOR, self.vendor), (S.SET_LANGUAGE, self.language)]), S.TAB_SITE)
        # --- browser
        self.channel = _combo([(S.SET_CHANNEL_AUTO, "auto"), ("Microsoft Edge", "msedge"), ("Google Chrome", "chrome"), ("Chromium", "chromium")],
                              c.browser.channel)
        self.headless = QCheckBox(S.SET_HEADLESS)
        self.headless.setChecked(c.browser.headless)
        self.slow_mo = QSpinBox()
        self.slow_mo.setRange(0, 5000)
        self.slow_mo.setValue(c.browser.slow_mo_ms)
        self.timeout = QSpinBox()
        self.timeout.setRange(1000, 120000)
        self.timeout.setSingleStep(1000)
        self.timeout.setValue(c.browser.default_timeout_ms)
        tabs.addTab(_form_tab([(S.SET_CHANNEL, self.channel), ("", self.headless), (S.SET_SLOW_MO, self.slow_mo),
                               (S.SET_TIMEOUT, self.timeout)]), S.TAB_BROWSER)
        # --- pace
        pc = c.pace
        self.pace_enabled = QCheckBox(S.SET_PACE_ENABLED)
        self.pace_enabled.setChecked(pc.enabled)
        self.pace_enabled.setToolTip(S.SET_PACE_HELP)
        w, self.pace_action_lo, self.pace_action_hi = _range_row(*_pair(pc.action_delay_ms, (400, 1200)), 60000)
        row_action = w
        w, self.pace_nav_lo, self.pace_nav_hi = _range_row(*_pair(pc.nav_delay_ms, (1000, 2000)), 60000)
        row_nav = w
        w, self.pace_type_lo, self.pace_type_hi = _range_row(*_pair(pc.type_delay_ms, (30, 80)), 2000)
        row_type = w
        self.pace_max_hour = QSpinBox()
        self.pace_max_hour.setRange(0, 10000)
        self.pace_max_hour.setValue(int(pc.max_shipments_per_hour or 0))
        w, self.pace_between_lo, self.pace_between_hi = _range_row(*_pair(pc.between_shipments_s, (20, 60)), 3600)
        row_between = w
        grp = QGroupBox(S.GRP_PACE)
        gl = QFormLayout(grp)
        gl.addRow("", self.pace_enabled)
        gl.addRow(S.SET_PACE_ACTION, row_action)
        gl.addRow(S.SET_PACE_NAV, row_nav)
        gl.addRow(S.SET_PACE_TYPE, row_type)
        gl.addRow(S.SET_PACE_MAX_HOUR, self.pace_max_hour)
        gl.addRow(S.SET_PACE_BETWEEN, row_between)
        pace_tab = QWidget()
        QVBoxLayout(pace_tab).addWidget(grp)
        pace_tab.layout().addStretch(1)
        tabs.addTab(pace_tab, S.TAB_PACE)
        # --- flow
        fl = c.flow
        self.grouping = _combo([(S.OPT_PER_FILE, "per_file"), (S.OPT_PER_MASTER_PO, "per_master_po")], fl.grouping)
        self.dry_run = QCheckBox(S.SET_DRY_RUN)
        self.dry_run.setChecked(fl.dry_run)
        self.weight_mode = _combo([(S.SET_WEIGHT_TOTAL, "total_gw"), (S.SET_WEIGHT_PER_CARTON, "per_carton_gw")],
                                  fl.weight_mode)
        self.tracker_weight = _combo([(S.SET_WEIGHT_PER_CARTON_AS_IS, "per_carton_as_is"), (S.SET_WEIGHT_TOTAL, "total_gw")],
                                     fl.tracker_weight_mode)
        self.review_between = QCheckBox(S.SET_REVIEW_BETWEEN)
        self.review_between.setChecked(fl.review_between_shipments)
        self.shipping_type = QLineEdit(fl.shipping_type)
        self.transport = QLineEdit(fl.transportation_method)
        self.scac = QLineEdit(fl.scac_code)
        self.to_sites = QLineEdit(format_table(fl.to_sites))
        self.to_sites.setToolTip(S.SET_TO_SITES_HELP)
        self.bol = QLineEdit(fl.bill_of_lading)
        self.pro = QLineEdit(fl.pro_number)
        self.pack_code = QLineEdit(fl.packaging_code_carton)
        self.complete_partial = _combo([("Partial", "Partial"), ("Complete", "Complete")], fl.complete_partial)
        self.weight_um = QLineEdit(fl.weight_um)
        self.click_validate = QCheckBox(S.SET_CLICK_VALIDATE)
        self.click_validate.setChecked(fl.click_validate)
        self.write_back = QCheckBox(S.SET_WRITE_BACK)
        self.write_back.setChecked(fl.write_back_excel)
        self.pause_qty = QCheckBox(S.SET_PAUSE_QTY)
        self.pause_qty.setChecked(fl.pause_on_qty_warning)
        self.past_date = _combo([(S.SET_PAST_DATE_CLAMP, "clamp_today"), (S.SET_PAST_DATE_ASK, "ask")],
                                fl.past_date_policy)
        self.weight_mode.setToolTip(S.SET_WEIGHT_HELP)
        self.click_validate.setToolTip(S.SET_CLICK_VALIDATE_HELP)
        tabs.addTab(_form_tab([
            (S.SET_GROUPING, self.grouping), ("", self.dry_run), (S.SET_WEIGHT_MODE, self.weight_mode),
            (S.SET_TRACKER_WEIGHT, self.tracker_weight), ("", self.review_between),
            (S.SET_SHIPPING_TYPE, self.shipping_type), (S.SET_TRANSPORT, self.transport), (S.SET_SCAC, self.scac),
            (S.SET_TO_SITES, self.to_sites),
            (S.SET_BOL, self.bol), (S.SET_PRO, self.pro), (S.SET_PACK_CODE, self.pack_code),
            (S.SET_COMPLETE_PARTIAL, self.complete_partial), (S.SET_WEIGHT_UM, self.weight_um),
            ("", self.click_validate), ("", self.write_back), ("", self.pause_qty),
            (S.SET_PAST_DATE, self.past_date)]), S.TAB_FLOW)
        # --- AI
        ai = c.ai
        self.ai_enabled = QCheckBox(S.SET_AI_ENABLED)
        self.ai_enabled.setChecked(ai.enabled)
        self.preset = QComboBox()
        self.preset.addItem(S.PRESET_LABELS[CUSTOM], CUSTOM)
        for k in AI_PRESETS:
            self.preset.addItem(S.PRESET_LABELS.get(k, k), k)
        self.provider = _combo([("Anthropic (Claude)", "anthropic"), ("OpenAI-compatible", "openai_compat")],
                               ai.provider)
        self.ai_base_url = QLineEdit(ai.base_url)
        self.api_key = QLineEdit(ai.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit(ai.model)
        self.vision = QCheckBox(S.SET_AI_VISION)
        self.vision.setChecked(ai.vision)
        self.max_calls = QSpinBox()
        self.max_calls.setRange(0, 100)
        self.max_calls.setValue(ai.max_calls_per_run)
        self.test_btn = QPushButton(S.BTN_TEST_CONNECTION)
        self.test_btn.clicked.connect(self._run_test)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        ai_tab = _form_tab([("", self.ai_enabled), (S.SET_AI_PRESET, self.preset), (S.SET_AI_PROVIDER, self.provider),
                            (S.SET_AI_BASE_URL, self.ai_base_url), (S.SET_AI_KEY, self.api_key),
                            (S.SET_AI_MODEL, self.model), ("", self.vision), (S.SET_AI_MAX_CALLS, self.max_calls),
                            ("", self.test_btn), ("", self.test_result)])
        tabs.addTab(ai_tab, S.TAB_AI)
        self._select_matching_preset(ai.provider, ai.base_url, ai.model)
        self.preset.currentIndexChanged.connect(self._on_preset)
        self.test_done.connect(self._show_test_result)
        # --- notify
        n = c.notify
        self.sound = QCheckBox(S.SET_SOUND)
        self.sound.setChecked(n.sound)
        self.balloon = QCheckBox(S.SET_BALLOON)
        self.balloon.setChecked(n.balloon)
        self.start_min = QCheckBox(S.SET_START_MIN)
        self.start_min.setChecked(n.start_minimized)
        self.start_win = QCheckBox(S.SET_START_WIN)
        self.start_win.setChecked(n.start_with_windows)
        tabs.addTab(_form_tab([("", self.sound), ("", self.balloon), ("", self.start_min), ("", self.start_win)]),
                    S.TAB_NOTIFY)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(S.BTN_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    # --- AI presets ---------------------------------------------------------
    def _select_matching_preset(self, provider: str, base_url: str, model: str) -> None:
        self.preset.blockSignals(True)
        sel = CUSTOM
        for k, p in AI_PRESETS.items():
            if p["provider"] == provider and p["base_url"] == base_url and p["model"] == model:
                sel = k
                break
        self.preset.setCurrentIndex(self.preset.findData(sel))
        self.preset.blockSignals(False)

    def _on_preset(self) -> None:
        key = self.preset.currentData()
        p = AI_PRESETS.get(key)
        if not p:
            return
        self.provider.setCurrentIndex(self.provider.findData(p["provider"]))
        self.ai_base_url.setText(p["base_url"])
        self.model.setText(p["model"])

    def _ai_config(self):
        ai = config_from_dict(config_to_dict(self._base)).ai
        ai.enabled = self.ai_enabled.isChecked()
        ai.provider = self.provider.currentData()
        ai.base_url = self.ai_base_url.text().strip()
        ai.api_key = self.api_key.text().strip()
        ai.model = self.model.text().strip()
        ai.vision = self.vision.isChecked()
        ai.max_calls_per_run = self.max_calls.value()
        return ai

    def _run_test(self) -> None:
        """Test connection in a background thread so the dialog stays responsive."""
        ai = self._ai_config()
        self.test_btn.setEnabled(False)
        self.test_result.setText(S.TEST_RUNNING)

        def work() -> None:
            try:
                adv = self._advisor_factory(ai)
                if adv is None:
                    self.test_done.emit(S.TEST_NO_KEY, False)
                    return
                res = adv.explain_error(ExplainRequest(
                    step_id="test", step_title_vi=S.TEST_STEP_TITLE, error_text="Connection test (ignore).",
                    page_url="about:blank", aria_snapshot="", dom_excerpt="", screenshot_jpeg=None))
                if res is None:
                    self.test_done.emit(S.TEST_BAD_REPLY, True)
                else:
                    self.test_done.emit(S.TEST_OK.format(text=res.explanation_vi[:200]), True)
            except EdiAssistantError as e:
                self.test_done.emit(S.TEST_FAIL.format(text=e.message_vi or e.message), False)
            except Exception as e:  # noqa: BLE001
                self.test_done.emit(S.TEST_FAIL.format(text=str(e)[:200]), False)

        threading.Thread(target=work, daemon=True, name="ai-test").start()

    def _show_test_result(self, text: str, ok: bool) -> None:
        self.test_result.setStyleSheet("color:#188038" if ok else "color:#d93025")
        self.test_result.setText(text)
        self.test_btn.setEnabled(True)

    # --- result -------------------------------------------------------------
    def result_config(self) -> AppConfig:
        c = config_from_dict(config_to_dict(self._base))
        c.site.base_url = self.base_url.text().strip()
        c.site.use_mock = self.use_mock.isChecked()
        c.site.mock_url = self.mock_url.text().strip()
        c.site.vendor_profile_name = self.vendor.text().strip()
        c.browser.channel = self.channel.currentData()
        c.browser.headless = self.headless.isChecked()
        c.browser.slow_mo_ms = self.slow_mo.value()
        c.browser.default_timeout_ms = self.timeout.value()
        c.ui.language = self.language.currentData()
        p = c.pace
        p.enabled = self.pace_enabled.isChecked()
        p.action_delay_ms = sorted([self.pace_action_lo.value(), self.pace_action_hi.value()])
        p.nav_delay_ms = sorted([self.pace_nav_lo.value(), self.pace_nav_hi.value()])
        p.type_delay_ms = sorted([self.pace_type_lo.value(), self.pace_type_hi.value()])
        p.max_shipments_per_hour = self.pace_max_hour.value()
        p.between_shipments_s = sorted([self.pace_between_lo.value(), self.pace_between_hi.value()])
        f = c.flow
        f.grouping = self.grouping.currentData()
        f.dry_run = self.dry_run.isChecked()
        f.weight_mode = self.weight_mode.currentData()
        f.tracker_weight_mode = self.tracker_weight.currentData()
        f.review_between_shipments = self.review_between.isChecked()
        f.shipping_type = self.shipping_type.text().strip()
        f.transportation_method = self.transport.text().strip()
        f.scac_code = self.scac.text().strip()
        f.to_sites = parse_table(self.to_sites.text()) or dict(DEFAULT_TO_SITES)
        f.bill_of_lading = self.bol.text().strip()
        f.pro_number = self.pro.text().strip()
        f.packaging_code_carton = self.pack_code.text().strip()
        f.complete_partial = self.complete_partial.currentData()
        f.weight_um = self.weight_um.text().strip()
        f.click_validate = self.click_validate.isChecked()
        f.write_back_excel = self.write_back.isChecked()
        f.pause_on_qty_warning = self.pause_qty.isChecked()
        f.past_date_policy = self.past_date.currentData()
        c.ai = self._ai_config()
        n = c.notify
        n.sound = self.sound.isChecked()
        n.balloon = self.balloon.isChecked()
        n.start_minimized = self.start_min.isChecked()
        n.start_with_windows = self.start_win.isChecked()
        return c
