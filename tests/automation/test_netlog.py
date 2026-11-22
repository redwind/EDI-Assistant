"""Per-run network recorder: page requests + form posts, secrets redacted."""
from __future__ import annotations

import json

from edi_assistant.automation.netlog import NetworkRecorder, redact_form


def test_redact_form():
    out = redact_form("username=a%40b.com&password=hunter2&PO_NO=672346001&txtPwd=x")
    assert "hunter2" not in out and "a%40b.com" not in out and "PO_NO=672346001" in out
    assert redact_form(None) is None


def test_records_get_and_form_post(session, tmp_path):
    page = session.page
    path = tmp_path / "network.jsonl"
    rec = NetworkRecorder(session.context, path)
    try:
        form = ("<form method=post action='/echo'><input name=PO_NO value=672346001>"
                "<input name=password value=secret><input type=submit id=go></form>")
        page.route("http://edi.test/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body=form if r.request.method == "GET" else "<p>ok</p>"))
        page.goto("http://edi.test/search_po.do")
        with page.expect_navigation():
            page.click("#go")
    finally:
        rec.close()
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    post = next(x for x in lines if x["method"] == "POST")
    assert "PO_NO=672346001" in post["form"] and "secret" not in post["form"]
    assert post["status"] == 200 and "<p>ok</p>" in post["html"]
