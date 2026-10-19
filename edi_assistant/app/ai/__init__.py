"""AI provider clients."""
from __future__ import annotations

from urllib.parse import urlparse

from edi_assistant.core.config import AiConfig

from .anthropic_client import AnthropicAdvisor
from .base import _parse_json  # noqa: F401  (re-export)
from .openai_compat import OpenAICompatAdvisor


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def build_advisor(cfg: AiConfig, *, force: bool = False):
    """Return a VisionAdvisor or None (disabled / no key). force=True ignores cfg.enabled (test connection)."""
    if not (cfg.enabled or force):
        return None
    if not cfg.api_key and not (cfg.provider == "openai_compat" and _is_local(cfg.base_url)):
        return None
    if cfg.provider == "anthropic":
        return AnthropicAdvisor(cfg)
    return OpenAICompatAdvisor(cfg)
