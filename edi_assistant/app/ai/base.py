"""Shared logic of the AI advisors: prompt building, JSON parsing, HTTP with one retry."""
from __future__ import annotations

import base64
import json
import logging
import re
import time

import httpx

from edi_assistant.core.ai_interface import (
    Explanation, ExplainRequest, LocatorProposal, LocatorRequest, ReadFieldsRequest, ReadFieldsResult,
)
from edi_assistant.core.config import AiConfig
from edi_assistant.core.errors import AiError

from ..strings import S, language
from . import prompts

log = logging.getLogger(__name__)

MAX_CTX = 12_000
FORBIDDEN_WORDS = re.compile(r"submit|cancel|clear values|remove|delete", re.I)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _parse_json(text: str) -> dict | None:
    """Strip ``` fences and parse the first {...} block; None if nothing parses."""
    if not text:
        return None
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1)
    start = text.find("{")
    if start < 0:
        return None
    dec = json.JSONDecoder()
    try:
        obj, _ = dec.raw_decode(text[start:])
    except ValueError:
        # fall back to the widest brace span
        end = text.rfind("}")
        if end <= start:
            return None
        try:
            obj = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return obj if isinstance(obj, dict) else None


def _b64(img: bytes) -> str:
    return base64.b64encode(img).decode("ascii")


def _float(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


class BaseAdvisor:
    provider = ""

    def __init__(self, cfg: AiConfig, client: httpx.Client | None = None, retry_delay_s: float = 2.0):
        self.cfg = cfg
        self.name = f"{cfg.provider}:{cfg.model}"
        self.supports_vision = bool(cfg.vision)
        self._client = client
        self.retry_delay_s = retry_delay_s

    # --- provider specific -------------------------------------------------
    def _request(self, system: str, user_text: str, image: bytes | None) -> tuple[str, dict, dict]:
        """Return (url, headers, json_body)."""
        raise NotImplementedError

    def _extract_text(self, data: dict) -> str:
        raise NotImplementedError

    # --- transport ---------------------------------------------------------
    def _complete(self, system: str, user_text: str, image: bytes | None) -> str:
        if not self.cfg.vision:
            image = None
        url, headers, body = self._request(system, user_text, image)
        client = self._client or httpx.Client(timeout=self.cfg.timeout_s)
        try:
            resp = None
            for attempt in (0, 1):
                try:
                    resp = client.post(url, headers=headers, json=body)
                except httpx.HTTPError as e:
                    raise AiError(f"{self.provider} request failed: {type(e).__name__}",
                                  message_vi=S.AI_ERR_NETWORK,
                                  provider=self.provider, status=None) from e
                if attempt == 0 and (resp.status_code == 429 or resp.status_code >= 500):
                    time.sleep(self.retry_delay_s)
                    continue
                break
            assert resp is not None
            if resp.status_code < 200 or resp.status_code >= 300:
                snippet = resp.text[:200].replace(self.cfg.api_key, "***") if self.cfg.api_key else resp.text[:200]
                raise AiError(f"{self.provider} HTTP {resp.status_code}: {snippet}",
                              message_vi=S.AI_ERR_HTTP.format(status=resp.status_code),
                              provider=self.provider, status=resp.status_code)
            try:
                data = resp.json()
            except ValueError:
                return ""
            return self._extract_text(data) if isinstance(data, dict) else ""
        finally:
            if self._client is None:
                client.close()

    # --- VisionAdvisor -----------------------------------------------------
    def propose_locator(self, req: LocatorRequest) -> LocatorProposal | None:
        user = prompts.USER_LOCATOR.format(
            key=req.key, description=req.description, page_url=req.page_url, page_title=req.page_title,
            tried="; ".join(req.tried) or "(none)",
            aria_snapshot=req.aria_snapshot[:MAX_CTX], dom_excerpt=req.dom_excerpt[:MAX_CTX])
        d = _parse_json(self._complete(prompts.SYSTEM_LOCATOR, user, req.screenshot_jpeg))
        if not d or not isinstance(d.get("candidates"), list):
            return None
        cands = []
        for c in d["candidates"]:
            if not isinstance(c, dict) or not c.get("kind"):
                continue
            if FORBIDDEN_WORDS.search(" ".join(str(v) for v in c.values() if isinstance(v, str))):
                continue
            cands.append(c)
        if not cands:
            return None
        return LocatorProposal(candidates=cands[:3], confidence=_float(d.get("confidence")),
                               notes=str(d.get("notes", "")))

    def explain_error(self, req: ExplainRequest) -> Explanation | None:
        lang = language()
        user = prompts.user_explain(lang).format(
            step_id=req.step_id, step_title_vi=req.step_title_vi, error_text=req.error_text,
            page_url=req.page_url, aria_snapshot=req.aria_snapshot[:MAX_CTX], dom_excerpt=req.dom_excerpt[:MAX_CTX])
        d = _parse_json(self._complete(prompts.system_explain(lang), user, req.screenshot_jpeg))
        if not d or not d.get("explanation_vi"):
            return None
        return Explanation(explanation_vi=str(d["explanation_vi"]),
                           likely_cause=str(d.get("likely_cause", "unknown")),
                           user_action_vi=str(d.get("user_action_vi", "")))

    def read_fields(self, req: ReadFieldsRequest) -> ReadFieldsResult | None:
        user = prompts.USER_READ_FIELDS.format(fields=", ".join(req.fields), hint=req.hint)
        d = _parse_json(self._complete(prompts.SYSTEM_READ_FIELDS, user, req.screenshot_jpeg))
        if not d or not isinstance(d.get("values"), dict):
            return None
        vals = {str(k): str(v) for k, v in d["values"].items() if v not in (None, "")}
        return ReadFieldsResult(values=vals, confidence=_float(d.get("confidence")))
