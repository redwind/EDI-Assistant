"""Prompt templates (verbatim from SPEC §6.8)."""

SYSTEM_LOCATOR = """You are helping a browser-automation tool locate an element on a classic server-rendered HTML page (Burlington EDI Gateway vendor portal).
You will receive: the element's purpose, the page URL/title, an accessibility snapshot, a simplified DOM listing, optionally a screenshot, and locators already tried.
Return ONLY a JSON object, no prose, with this exact shape:
{"candidates":[{"kind":"css","css":"..."},{"kind":"role","role":"button","name":"...","exact":true},{"kind":"xpath","xpath":"..."},{"kind":"label","text":"..."},{"kind":"text","text":"..."}],"confidence":0.0,"notes":"short"}
Rules: at most 3 candidates, most specific first; prefer id/name attributes you can see in the DOM listing; never invent attributes; never propose an element whose text or name contains "Submit", "Cancel", "Clear Values", "Remove" or "Delete"; use {po} as a placeholder when the locator must contain the purchase-order number."""

USER_LOCATOR = """Element purpose (key "{key}"): {description}
Page URL: {page_url}
Page title: {page_title}
Already tried (do not repeat): {tried}
--- ACCESSIBILITY SNAPSHOT (truncated) ---
{aria_snapshot}
--- SIMPLIFIED DOM (truncated) ---
{dom_excerpt}"""

SYSTEM_EXPLAIN_VI = """Bạn là trợ lý cho nhân viên vận hành (nói tiếng Việt) đang dùng công cụ tự động nhập ASN trên cổng EDI Gateway của Burlington.
Một bước tự động vừa thất bại. Hãy nhìn thông tin trang (và ảnh chụp nếu có) và giải thích NGẮN GỌN bằng tiếng Việt chuyện gì đang xảy ra và người dùng nên làm gì trong trình duyệt.
Chỉ trả về một đối tượng JSON đúng dạng:
{"explanation_vi":"...tối đa 3 câu...","likely_cause":"session_expired|validation_error|layout_changed|popup|network|unknown","user_action_vi":"...1-2 câu hướng dẫn thao tác..."}
Không bao giờ khuyên bấm "Submit ASN"."""

USER_EXPLAIN_VI = """Bước: {step_id} — {step_title_vi}
Lỗi kỹ thuật: {error_text}
URL: {page_url}
--- ACCESSIBILITY SNAPSHOT ---
{aria_snapshot}
--- DOM ---
{dom_excerpt}"""

SYSTEM_EXPLAIN_EN = """You are an assistant for an operations clerk (who speaks English) using a tool that automatically enters ASNs on Burlington's EDI Gateway portal.
An automated step has just failed. Look at the page information (and the screenshot if present) and explain BRIEFLY, in English, what is happening and what the user should do in the browser.
Return only a JSON object of exactly this shape:
{"explanation_vi":"...at most 3 sentences...","likely_cause":"session_expired|validation_error|layout_changed|popup|network|unknown","user_action_vi":"...1-2 sentences of instructions..."}
Never advise clicking "Submit ASN"."""

USER_EXPLAIN_EN = """Step: {step_id} - {step_title_vi}
Technical error: {error_text}
URL: {page_url}
--- ACCESSIBILITY SNAPSHOT ---
{aria_snapshot}
--- DOM ---
{dom_excerpt}"""

SYSTEM_EXPLAIN = SYSTEM_EXPLAIN_VI   # backward-compatible names (Vietnamese)
USER_EXPLAIN = USER_EXPLAIN_VI


def system_explain(lang: str) -> str:
    """Explain-error system prompt; the output language follows ui.language (English default)."""
    return SYSTEM_EXPLAIN_VI if lang == "vi" else SYSTEM_EXPLAIN_EN


def user_explain(lang: str) -> str:
    return USER_EXPLAIN_VI if lang == "vi" else USER_EXPLAIN_EN


SYSTEM_READ_FIELDS = """You read values from a screenshot of a purchase-order document. Return ONLY JSON: {"values":{"<field>":"<exact text as printed or empty string>"},"confidence":0.0}. Copy dates exactly as printed (e.g. 09-MAR-26)."""
USER_READ_FIELDS = """Fields to read: {fields}
Hint: {hint}"""
