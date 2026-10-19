"""UI language: en/vi key parity, placeholder parity, loader, prompts, settings."""
from __future__ import annotations

import string

from edi_assistant.app import strings, strings_en, strings_vi
from edi_assistant.app.ai import prompts
from edi_assistant.core.config import AppConfig, load_config, save_config


def _keys(mod):
    return {k for k in vars(mod) if k.isupper()}


def _fields(v) -> list:
    """Sorted placeholder names of a string / nested container of strings."""
    out: list[str] = []
    if isinstance(v, str):
        out += [f for _, f, _, _ in string.Formatter().parse(v) if f]
    elif isinstance(v, dict):
        for x in v.values():
            out += _fields(x)
    elif isinstance(v, (tuple, list)):
        for x in v:
            out += _fields(x)
    return sorted(out)


def test_same_keys():
    assert _keys(strings_en) == _keys(strings_vi)


def test_same_placeholders_and_shapes():
    for k in _keys(strings_en):
        en, vi = getattr(strings_en, k), getattr(strings_vi, k)
        assert type(en) is type(vi), k
        assert _fields(en) == _fields(vi), k
        if isinstance(en, (tuple, list, dict)):
            assert len(en) == len(vi), k
        if isinstance(en, dict):
            assert set(en) == set(vi), k


def test_loader_default_is_english_and_switches():
    strings.set_language(None)
    try:
        assert strings.language() == "en" and strings.S.BTN_START == strings_en.BTN_START
        assert strings.tr("NOTIFY_RUN_FAILED", err="x") == "The run failed: x"
        strings.set_language("vi")
        assert strings.S.BTN_START == strings_vi.BTN_START
        assert strings.normalize("fr") == "en"
    finally:
        strings.set_language("en")


def test_loader_reads_config(tmp_path):
    cfg = AppConfig()
    cfg.ui.language = "vi"
    save_config(cfg)
    assert load_config().ui.language == "vi"
    strings._lang = strings._mod = None
    try:
        assert strings.language() == "vi"
    finally:
        strings.set_language("en")


def test_explain_prompt_follows_language():
    assert "English" in prompts.system_explain("en") and "tiếng Việt" not in prompts.system_explain("en")
    assert "tiếng Việt" in prompts.system_explain("vi")
    for lang in ("en", "vi"):
        t = prompts.user_explain(lang)
        t.format(step_id="a", step_title_vi="b", error_text="c", page_url="d", aria_snapshot="e", dom_excerpt="f")
        assert prompts.system_explain(lang).count("explanation_vi") == 1   # JSON contract unchanged


def test_settings_pace_and_language_roundtrip(qtbot):
    from edi_assistant.app.dialogs.settings_dialog import SettingsDialog
    cfg = AppConfig()
    dlg = SettingsDialog(cfg)
    qtbot.addWidget(dlg)
    assert dlg.pace_enabled.isChecked() and dlg.language.currentData() == "en"
    dlg.pace_enabled.setChecked(False)
    dlg.pace_action_lo.setValue(10)
    dlg.pace_action_hi.setValue(20)
    dlg.pace_max_hour.setValue(5)
    dlg.pace_between_lo.setValue(1)
    dlg.pace_between_hi.setValue(2)
    dlg.language.setCurrentIndex(dlg.language.findData("vi"))
    out = dlg.result_config()
    assert out.pace.enabled is False and out.pace.action_delay_ms == [10, 20]
    assert out.pace.max_shipments_per_hour == 5 and out.pace.between_shipments_s == [1, 2]
    assert out.pace.nav_delay_ms == [1000, 2000] and out.ui.language == "vi"
    assert dlg.language.toolTip()
