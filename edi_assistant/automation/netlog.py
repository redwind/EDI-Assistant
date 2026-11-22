"""Network recorder for one run: every page-level request the site handles (method, URL, form body,
status, redirect, response HTML), one JSON object per line in <run>/network.jsonl.

Purpose: learn the exact form posts of the EDI pages so steps can later be sent directly over HTTP.
Passwords and e-mail addresses are redacted; cookies and auth headers are never written."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from playwright.sync_api import BrowserContext, Request, Response

KEEP_TYPES = ("document", "xhr", "fetch")
SECRET_KEY = re.compile(r"pass|pwd|secret|token|otp", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
BODY_LIMIT = 400_000


def redact_form(body: str | None) -> str | None:
    """Form-encoded body with secret fields blanked and e-mails masked (non-form bodies: e-mails masked)."""
    if not body:
        return body
    try:
        pairs = parse_qsl(body, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return EMAIL.sub("[email]", body)
    return urlencode([(k, "[redacted]" if SECRET_KEY.search(k) else EMAIL.sub("[email]", v)) for k, v in pairs])


class NetworkRecorder:
    def __init__(self, context: BrowserContext, path: Path):
        self.context, self.path = context, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._started: dict[int, float] = {}
        context.on("request", self._on_request)
        context.on("response", self._on_response)

    def _on_request(self, req: Request) -> None:
        if req.resource_type in KEEP_TYPES:
            self._started[id(req)] = time.monotonic()

    def _on_response(self, resp: Response) -> None:
        req = resp.request
        if req.resource_type not in KEEP_TYPES:
            return
        t_start = self._started.pop(id(req), time.monotonic())
        rec = {
            "t": round(t_start - self._t0, 3),
            "ms": round((time.monotonic() - t_start) * 1000),
            "type": req.resource_type,
            "method": req.method,
            "url": EMAIL.sub("[email]", req.url),
            "form": redact_form(req.post_data),
            "content_type": req.headers.get("content-type", ""),
            "status": resp.status,
            "location": resp.headers.get("location", ""),
            "redirected_from": EMAIL.sub("[email]", req.redirected_from.url) if req.redirected_from else "",
        }
        if 200 <= resp.status < 300 and "html" in resp.headers.get("content-type", ""):
            try:
                rec["html"] = EMAIL.sub("[email]", resp.text()[:BODY_LIMIT])
            except Exception:   # body gone (navigated away) - the request line is still useful
                pass
        self._write(rec)

    def _write(self, rec: dict) -> None:
        with self._lock:
            if not self._fh.closed:
                self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                self._fh.flush()

    def close(self) -> None:
        for ev, fn in (("request", self._on_request), ("response", self._on_response)):
            try:
                self.context.remove_listener(ev, fn)
            except Exception:
                pass
        with self._lock:
            self._fh.close()
