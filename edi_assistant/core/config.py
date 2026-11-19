"""AppConfig dataclasses + YAML load/save."""
from __future__ import annotations

import dataclasses
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from . import paths
from .dc_sites import DEFAULT_TO_SITES


_runtime_mock_url = ""   # process-only override (--mock); never part of AppConfig, so it is never saved


def set_runtime_mock_url(url: str) -> None:
    global _runtime_mock_url
    _runtime_mock_url = url or ""


@dataclass(slots=True)
class SiteConfig:
    base_url: str = "https://edi.coat.com/vms-gateway/"
    use_mock: bool = False
    mock_url: str = "http://127.0.0.1:8765/vms-gateway/"
    vendor_profile_name: str = "SHYFT GLOBAL LLC"

    def effective_base_url(self) -> str:
        url = _runtime_mock_url or (self.mock_url if self.use_mock else self.base_url)
        return url if url.endswith("/") else url + "/"


@dataclass(slots=True)
class BrowserConfig:
    channel: str = "auto"   # "auto" | "msedge" | "chromium" (| "chrome")
    headless: bool = False
    slow_mo_ms: int = 0
    default_timeout_ms: int = 15000
    viewport_width: int = 1280
    viewport_height: int = 900


@dataclass(slots=True)
class FlowConfig:
    grouping: str = "per_file"
    dry_run: bool = False
    weight_mode: str = "total_gw"
    shipping_type: str = "Ship to DC"
    transportation_method: str = "Containerized Ocean"
    scac_code: str = "MAEU"
    bill_of_lading: str = "Unknown"
    pro_number: str = "Unknown"
    packaging_code_carton: str = "Physical Container - Carton"
    complete_partial: str = "Partial"
    weight_um: str = "KG"
    click_validate: bool = False
    write_back_excel: bool = True
    pause_on_qty_warning: bool = True
    tracker_weight_mode: str = "per_carton_as_is"   # "per_carton_as_is" | "total_gw"
    review_between_shipments: bool = False          # True: S10 finished_review pause after every shipment; False: one final summary pause
    to_sites: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TO_SITES))   # Delivery Address state -> TO Site No
    past_date_policy: str = "clamp_today"   # "clamp_today" (binding default: silently use today) | "ask" (pause, let the user type a date)


@dataclass(slots=True)
class AiConfig:
    enabled: bool = False
    provider: str = "anthropic"
    base_url: str = "https://api.anthropic.com"
    api_key: str = ""
    model: str = "claude-haiku-5-5"
    vision: bool = True
    max_calls_per_run: int = 8
    timeout_s: int = 60
    max_tokens: int = 800


@dataclass(slots=True)
class NotifyConfig:
    sound: bool = True
    balloon: bool = True
    start_minimized: bool = False
    start_with_windows: bool = False


@dataclass(slots=True)
class PaceConfig:
    """Human-pace mode: random delays + typed input + shipment throttling (anti-blocking, reliability)."""
    enabled: bool = True
    action_delay_ms: list[int] = field(default_factory=lambda: [400, 1200])    # between click/fill/select
    nav_delay_ms: list[int] = field(default_factory=lambda: [1000, 2000])      # extra, after each page load
    type_delay_ms: list[int] = field(default_factory=lambda: [30, 80])         # per character when typing
    max_shipments_per_hour: int = 0                                            # 0 = unlimited
    between_shipments_s: list[int] = field(default_factory=lambda: [20, 60])   # pause between shipments of a run


@dataclass(slots=True)
class UiConfig:
    language: str = "en"   # "en" | "vi" (takes effect after restart)
    last_excel_dir: str = ""
    last_factory_id: str = ""
    last_factory_xlsx: str = ""   # last imported factory list workbook
    last_profile: str = ""   # informational
    window_geometry_b64: str = ""
    system_check_done: bool = False   # first-run System check offered


@dataclass(slots=True)
class AppConfig:
    version: int = 1
    site: SiteConfig = field(default_factory=SiteConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    pace: PaceConfig = field(default_factory=PaceConfig)
    ui: UiConfig = field(default_factory=UiConfig)


AI_PRESETS: dict[str, dict] = {
    "anthropic": {"provider": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-haiku-5-5"},
    "anthropic_sonnet": {"provider": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5-5"},
    "openai": {"provider": "openai_compat", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "gemini": {"provider": "openai_compat", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.0-flash"},
    "deepseek": {"provider": "openai_compat", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    "qwen": {"provider": "openai_compat", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-vl-plus"},
    "openrouter": {"provider": "openai_compat", "base_url": "https://openrouter.ai/api/v1", "model": "anthropic/claude-haiku-5-5"},
    "ollama": {"provider": "openai_compat", "base_url": "http://localhost:11434/v1", "model": "llava"},
}


def _fill(cls, d):
    """Build dataclass `cls` from dict `d`: unknown keys ignored, missing -> defaults."""
    obj = cls()
    if not isinstance(d, dict):
        return obj
    for f in dataclasses.fields(cls):
        if f.name not in d:
            continue
        cur = getattr(obj, f.name)
        val = d[f.name]
        if dataclasses.is_dataclass(cur):
            setattr(obj, f.name, _fill(type(cur), val))
        elif val is not None:
            setattr(obj, f.name, val)
    return obj


def config_to_dict(cfg: AppConfig) -> dict:
    return asdict(cfg)


def config_from_dict(d: dict) -> AppConfig:
    return _fill(AppConfig, d)


def load_config(path: Path | None = None) -> AppConfig:
    p = Path(path) if path else paths.config_path()
    if not p.exists():
        return AppConfig()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        from .errors import ConfigError

        raise ConfigError(f"Invalid YAML in {p}", message_vi=f"Config file is corrupt: {p}")
    return config_from_dict(data)


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    p = Path(path) if path else paths.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(yaml.safe_dump(config_to_dict(cfg), sort_keys=False, allow_unicode=True), encoding="utf-8")
    os.replace(tmp, p)
