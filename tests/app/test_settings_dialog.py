import time

from edi_assistant.app.dialogs.settings_dialog import SettingsDialog
from edi_assistant.core.config import AI_PRESETS, AppConfig, config_to_dict
from edi_assistant.core.errors import AiError


def test_roundtrip_unchanged(qtbot):
    cfg = AppConfig()
    dlg = SettingsDialog(cfg)
    qtbot.addWidget(dlg)
    assert config_to_dict(dlg.result_config()) == config_to_dict(cfg)


def test_preset_fills_fields(qtbot):
    dlg = SettingsDialog(AppConfig())
    qtbot.addWidget(dlg)
    for key in AI_PRESETS:
        dlg.preset.setCurrentIndex(dlg.preset.findData(key))
        ai = dlg.result_config().ai
        p = AI_PRESETS[key]
        assert (ai.provider, ai.base_url, ai.model) == (p["provider"], p["base_url"], p["model"])
    dlg.preset.setCurrentIndex(dlg.preset.findData("anthropic_sonnet"))
    assert dlg.result_config().ai.model == "claude-sonnet-5-5"


def test_edits_reach_config(qtbot):
    dlg = SettingsDialog(AppConfig())
    qtbot.addWidget(dlg)
    dlg.use_mock.setChecked(True)
    dlg.dry_run.setChecked(True)
    dlg.ai_enabled.setChecked(True)
    dlg.api_key.setText(" k123 ")
    dlg.start_win.setChecked(True)
    dlg.timeout.setValue(20000)
    c = dlg.result_config()
    assert c.site.use_mock and c.flow.dry_run and c.ai.enabled and c.notify.start_with_windows
    assert c.ai.api_key == "k123" and c.browser.default_timeout_ms == 20000


def test_existing_custom_ai_selects_custom_preset(qtbot):
    cfg = AppConfig()
    cfg.ai.model = "my-model"
    dlg = SettingsDialog(cfg)
    qtbot.addWidget(dlg)
    assert dlg.preset.currentData() == "custom"


class _Ok:
    def explain_error(self, req):
        from edi_assistant.core.ai_interface import Explanation
        return Explanation("ổn", "unknown", "")


class _Bad:
    def explain_error(self, req):
        raise AiError("boom", message_vi="lỗi mạng", provider="x", status=500)


def test_connection_button(qtbot):
    dlg = SettingsDialog(AppConfig(), advisor_factory=lambda ai: _Ok())
    qtbot.addWidget(dlg)
    dlg.test_btn.click()
    qtbot.waitUntil(lambda: dlg.test_btn.isEnabled() and "successful" in dlg.test_result.text(), timeout=3000)

    dlg2 = SettingsDialog(AppConfig(), advisor_factory=lambda ai: _Bad())
    qtbot.addWidget(dlg2)
    dlg2.test_btn.click()
    qtbot.waitUntil(lambda: dlg2.test_btn.isEnabled() and "failed" in dlg2.test_result.text(), timeout=3000)
    assert "lỗi mạng" in dlg2.test_result.text()

    dlg3 = SettingsDialog(AppConfig(), advisor_factory=lambda ai: None)
    qtbot.addWidget(dlg3)
    dlg3.test_btn.click()
    qtbot.waitUntil(lambda: dlg3.test_btn.isEnabled() and dlg3.test_result.text() != "", timeout=3000)


def test_past_date_policy_roundtrip(qtbot):
    dlg = SettingsDialog(AppConfig())
    qtbot.addWidget(dlg)
    assert dlg.result_config().flow.past_date_policy == "clamp_today"
    dlg.past_date.setCurrentIndex(dlg.past_date.findData("ask"))
    assert dlg.result_config().flow.past_date_policy == "ask"
