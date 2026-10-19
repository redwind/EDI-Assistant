"""OpenAI-compatible chat/completions client (OpenAI, Gemini, DeepSeek, Qwen, OpenRouter, Ollama)."""
from __future__ import annotations

from .base import BaseAdvisor, _b64


class OpenAICompatAdvisor(BaseAdvisor):
    provider = "openai_compat"

    def _request(self, system, user_text, image):
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        if image:
            content = [{"type": "text", "text": user_text},
                       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + _b64(image)}}]
        else:
            content = user_text
        body = {"model": self.cfg.model, "temperature": 0, "max_tokens": self.cfg.max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}]}
        return url, headers, body

    def _extract_text(self, data):
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""
        if isinstance(content, list):  # some servers return content parts
            return "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content or ""
