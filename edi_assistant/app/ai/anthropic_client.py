"""Anthropic Messages API client (plain httpx). No temperature/prefill: current models reject them."""
from __future__ import annotations

from .base import BaseAdvisor, _b64

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdvisor(BaseAdvisor):
    provider = "anthropic"

    def _request(self, system, user_text, image):
        base = self.cfg.base_url.rstrip("/")
        url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        headers = {"x-api-key": self.cfg.api_key, "anthropic-version": ANTHROPIC_VERSION,
                   "content-type": "application/json"}
        content: list[dict] = []
        if image:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(image)}})
        content.append({"type": "text", "text": user_text})
        body = {"model": self.cfg.model, "max_tokens": self.cfg.max_tokens, "system": system,
                "messages": [{"role": "user", "content": content}]}
        return url, headers, body

    def _extract_text(self, data):
        blocks = data.get("content")
        if not isinstance(blocks, list):
            return ""
        return "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
