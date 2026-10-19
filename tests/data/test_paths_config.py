import yaml

from edi_assistant.core import paths
from edi_assistant.core.config import AppConfig, load_config, save_config, SiteConfig


def test_portable(tmp_path, monkeypatch):
    monkeypatch.delenv("EDI_ASSISTANT_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path)
    assert not paths.is_portable()
    (tmp_path / "portable.flag").write_text("")
    assert paths.is_portable()
    assert paths.user_data_dir() == tmp_path / "data" and paths.local_data_dir() == tmp_path / "data"
    assert paths.config_path() == tmp_path / "data" / "config.yaml"
    assert paths.run_dir("r1").is_dir()


def test_env_override(data_dir):
    assert paths.user_data_dir() == data_dir and data_dir.is_dir()
    assert paths.browser_profile_dir() == data_dir / "browser_profile"


def test_config_roundtrip(tmp_path):
    p = tmp_path / "c.yaml"
    assert load_config(p) == AppConfig()
    p.write_text(yaml.safe_dump({"site": {"use_mock": True, "bogus": 1}, "flow": {"dry_run": True},
                                 "unknown": {"a": 1}}), encoding="utf-8")
    c = load_config(p)
    assert c.site.use_mock and c.flow.dry_run and c.browser.channel == "auto"
    assert c.site.effective_base_url() == "http://127.0.0.1:8765/vms-gateway/"
    c.ai.api_key = "k"
    c.ui.last_excel_dir = "Thư mục"
    save_config(c, p)
    assert load_config(p) == c
    assert SiteConfig(base_url="http://x").effective_base_url() == "http://x/"


def test_runtime_mock_override_never_saved(tmp_path):
    from edi_assistant.core.config import set_runtime_mock_url
    cfg = AppConfig()
    try:
        set_runtime_mock_url("http://127.0.0.1:9/vms-gateway/")
        assert cfg.site.effective_base_url() == "http://127.0.0.1:9/vms-gateway/"
        p = tmp_path / "c.yaml"
        save_config(cfg, p)
        saved = load_config(p)
        assert not saved.site.use_mock and "127.0.0.1:9" not in p.read_text(encoding="utf-8")
    finally:
        set_runtime_mock_url("")
    assert cfg.site.effective_base_url() == cfg.site.base_url


def test_portable_readonly_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("EDI_ASSISTANT_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "exe_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "is_portable", lambda: True)
    fallback = tmp_path / "roam"
    real_mk = paths._mk

    def fake_mk(p):
        if p == tmp_path / "data":
            raise PermissionError("read-only")
        return real_mk(p)
    monkeypatch.setattr(paths, "_mk", fake_mk)
    monkeypatch.setenv("HOME", str(fallback))
    monkeypatch.setenv("XDG_DATA_HOME", str(fallback))
    monkeypatch.setenv("APPDATA", str(fallback))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: fallback))
    assert str(paths.user_data_dir()).startswith(str(fallback))


def test_user_dirs_use_spaced_app_name(tmp_path, monkeypatch):
    monkeypatch.delenv("EDI_ASSISTANT_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "is_portable", lambda: False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "x"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "x"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "x"))
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.user_data_dir().name == "EDI Assistant"
    assert paths.local_data_dir().name == "EDI Assistant"
