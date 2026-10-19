import json

import httpx
import pytest

from edi_assistant.app.ai import _parse_json, build_advisor
from edi_assistant.app.ai.anthropic_client import AnthropicAdvisor
from edi_assistant.app.ai.openai_compat import OpenAICompatAdvisor
from edi_assistant.core.ai_interface import ExplainRequest, LocatorRequest, ReadFieldsRequest
from edi_assistant.core.config import AiConfig
from edi_assistant.core.errors import AiError

JPEG = b"\xff\xd8fakejpeg"


def make(cls, handler, **cfg_kw):
    cfg = AiConfig(enabled=True, api_key="sk-secret", **cfg_kw)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return cls(cfg, client=client, retry_delay_s=0)


def oa_reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def an_reply(text):
    return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": text}]})


EXPLAIN = ExplainRequest("S5", "Điền header", "boom", "http://x", "aria", "dom", JPEG)
LOCATE = LocatorRequest("k", "desc", "http://x", "t", "aria", "dom", JPEG, ["css=#a"])


def test_parse_json_variants():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('noise {"a": {"b": 2}} tail') == {"a": {"b": 2}}
    assert _parse_json("nothing") is None and _parse_json("") is None and _parse_json("[1]") is None


def test_openai_request_shape_with_image():
    seen = {}

    def h(req):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return oa_reply('{"explanation_vi":"Hết phiên","likely_cause":"session_expired","user_action_vi":"Đăng nhập"}')

    adv = make(OpenAICompatAdvisor, h, provider="openai_compat", base_url="https://api.openai.com/v1/", model="gpt-4o-mini")
    res = adv.explain_error(EXPLAIN)
    assert res.likely_cause == "session_expired" and res.explanation_vi == "Hết phiên"
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer sk-secret"
    b = seen["body"]
    assert b["temperature"] == 0 and b["model"] == "gpt-4o-mini" and b["max_tokens"] == 800
    assert b["messages"][0]["role"] == "system"
    parts = b["messages"][1]["content"]
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_no_image_when_vision_off_or_missing():
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        return oa_reply("{}")

    make(OpenAICompatAdvisor, h, provider="openai_compat", vision=False).explain_error(EXPLAIN)
    assert isinstance(bodies[-1]["messages"][1]["content"], str)
    import dataclasses
    make(OpenAICompatAdvisor, h, provider="openai_compat").explain_error(dataclasses.replace(EXPLAIN, screenshot_jpeg=None))
    assert isinstance(bodies[-1]["messages"][1]["content"], str)


def test_anthropic_request_shape():
    seen = {}

    def h(req):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, json.loads(req.content)
        return an_reply('```json\n{"candidates":[{"kind":"css","css":"#x"}],"confidence":0.8,"notes":"n"}\n```')

    adv = make(AnthropicAdvisor, h, provider="anthropic", base_url="https://api.anthropic.com")
    prop = adv.propose_locator(LOCATE)
    assert prop.candidates == [{"kind": "css", "css": "#x"}] and prop.confidence == 0.8
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-secret"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    b = seen["body"]
    assert "temperature" not in b and "top_p" not in b and b["model"] == "claude-haiku-5-5"
    assert b["system"] and b["messages"][0]["role"] == "user" and len(b["messages"]) == 1
    c = b["messages"][0]["content"]
    assert c[0]["type"] == "image" and c[0]["source"]["media_type"] == "image/jpeg" and c[-1]["type"] == "text"


def test_anthropic_without_image():
    seen = {}

    def h(req):
        seen["body"] = json.loads(req.content)
        return an_reply("{}")

    make(AnthropicAdvisor, h, provider="anthropic", vision=False).explain_error(EXPLAIN)
    assert [p["type"] for p in seen["body"]["messages"][0]["content"]] == ["text"]


def test_locator_filters_forbidden_candidates():
    adv = make(AnthropicAdvisor, lambda r: an_reply(json.dumps({"candidates": [
        {"kind": "role", "role": "button", "name": "Submit ASN"},
        {"kind": "css", "css": "#ok"}, {"kind": "text", "text": "Remove"}, {"nokind": 1}], "confidence": "0.5"})),
        provider="anthropic")
    prop = adv.propose_locator(LOCATE)
    assert prop.candidates == [{"kind": "css", "css": "#ok"}] and prop.confidence == 0.5


def test_read_fields():
    adv = make(OpenAICompatAdvisor, lambda r: oa_reply('{"values":{"early_ship_date":"09-MAR-26","late_ship_date":""},"confidence":0.9}'),
               provider="openai_compat")
    res = adv.read_fields(ReadFieldsRequest(["early_ship_date", "late_ship_date"], "top table", JPEG))
    assert res.values == {"early_ship_date": "09-MAR-26"} and res.confidence == 0.9


@pytest.mark.parametrize("cls,prov", [(OpenAICompatAdvisor, "openai_compat"), (AnthropicAdvisor, "anthropic")])
def test_non_2xx_raises_aierror_without_leaking_key(cls, prov):
    adv = make(cls, lambda r: httpx.Response(401, text="bad key sk-secret"), provider=prov)
    with pytest.raises(AiError) as ei:
        adv.explain_error(EXPLAIN)
    assert ei.value.ctx["status"] == 401 and ei.value.ctx["provider"] == prov
    assert "sk-secret" not in ei.value.message


@pytest.mark.parametrize("cls,prov,reply", [(OpenAICompatAdvisor, "openai_compat", oa_reply), (AnthropicAdvisor, "anthropic", an_reply)])
def test_garbage_returns_none(cls, prov, reply):
    adv = make(cls, lambda r: reply("sorry, I cannot do that"), provider=prov)
    assert adv.explain_error(EXPLAIN) is None
    assert adv.propose_locator(LOCATE) is None
    assert adv.read_fields(ReadFieldsRequest(["a"], "h", JPEG)) is None


def test_retry_once_on_429_then_success():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) == 1 else oa_reply('{"explanation_vi":"ok"}')

    assert make(OpenAICompatAdvisor, h, provider="openai_compat").explain_error(EXPLAIN).explanation_vi == "ok"
    assert len(calls) == 2


def test_network_error_is_aierror():
    def h(req):
        raise httpx.ConnectError("down")

    with pytest.raises(AiError):
        make(OpenAICompatAdvisor, h, provider="openai_compat").explain_error(EXPLAIN)


def test_build_advisor_rules():
    assert build_advisor(AiConfig(enabled=False, api_key="k")) is None
    assert build_advisor(AiConfig(enabled=True, api_key="")) is None
    assert isinstance(build_advisor(AiConfig(enabled=True, api_key="k")), AnthropicAdvisor)
    oa = build_advisor(AiConfig(enabled=True, provider="openai_compat", base_url="https://x/v1", api_key="k"))
    assert isinstance(oa, OpenAICompatAdvisor)
    assert build_advisor(AiConfig(enabled=True, provider="openai_compat", base_url="http://localhost:11434/v1", api_key=""))
    assert build_advisor(AiConfig(enabled=False, api_key="k"), force=True) is not None
