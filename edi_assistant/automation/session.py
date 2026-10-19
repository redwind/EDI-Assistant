"""BrowserSession: persistent Playwright context on the worker thread."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from edi_assistant.core.config import BrowserConfig, SiteConfig
from edi_assistant.core.errors import (BrowserLaunchError, ForbiddenActionError, NavigationError, SiteBlockedError)
from edi_assistant.core.events import EventSink

from .dialogs import DialogPolicy

BLOCK_PATTERN = "**/asn.do*"
BLOCK_STATUSES = (403, 429, 503)
BLOCK_MARKERS = ("access denied", "forbidden", "too many requests", "captcha", "unusual traffic",
                 "verify you are human")
LOAD_CAP_MS = 5000
IDLE_CAP_MS = 2000


class BrowserSession:
    def __init__(self, cfg: BrowserConfig, site: SiteConfig, profile_dir: Path, sink: EventSink, log: logging.Logger):
        self.cfg = cfg
        self.site = site
        self.profile_dir = Path(profile_dir)
        self.sink = sink
        self.log = log
        self.dialogs = DialogPolicy(log, sink)
        self.blocked: list[str] = []      # URLs of aborted asn.do requests
        self.pacer = None                 # automation.pace.Pacer while a run is active (human-pace mode)
        self.shipment_starts: list[float] = []   # hourly-limit history, shared by all runs of this session
        self.block_reason = ""            # set by the response listener on 403/429/503 main-frame responses
        self._pw: Playwright | None = None
        self.context: BrowserContext | None = None
        self._pages: list[Page] = []

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> None:
        self._pw = sync_playwright().start()
        kwargs = dict(
            user_data_dir=str(self.profile_dir), headless=self.cfg.headless, slow_mo=self.cfg.slow_mo_ms,
            viewport={"width": self.cfg.viewport_width, "height": self.cfg.viewport_height},
            accept_downloads=True, args=["--disable-blink-features=AutomationControlled"])
        from edi_assistant.core import browser_detect as bd
        plan = bd.launch_plan(self.cfg.channel, bundled=bd.bundled_chromium_available(), chromium=bd.chromium_available())
        errors: list[tuple[str | None, str]] = []
        for channel in plan:
            try:
                self.context = self._pw.chromium.launch_persistent_context(channel=channel, **kwargs)
                break
            except PlaywrightError as ex:
                first = str(ex).splitlines()[0] if str(ex) else repr(ex)
                self.log.warning("launch with channel=%s failed: %s", channel, first)
                errors.append((channel, str(ex)))
        if self.context is None:
            self._stop_pw()
            edge_err = next((e for c, e in errors if c == "msedge"), None)
            if edge_err is not None and bd.launch_failure_kind(edge_err) in ("policy", "missing"):
                msg = bd.LOCKED_DOWN_MESSAGE
            else:
                msg = 'Edge/Chromium not found or could not start. Use Tools > Install Chromium browser, or Help > System check.'
            raise BrowserLaunchError(errors[-1][1] if errors else "no launch attempt", message_vi=msg)
        ctx = self.context
        ctx.set_default_timeout(self.cfg.default_timeout_ms)
        ctx.route(BLOCK_PATTERN, self._block)
        ctx.on("page", self._on_new_page)
        for p in list(ctx.pages):
            self._adopt(p)
        if not self._pages:
            self._adopt(ctx.new_page())

    def _block(self, route) -> None:
        self.blocked.append(route.request.url)
        self.log.warning("BLOCKED request to %s", route.request.url)
        route.abort()

    def _adopt(self, page: Page) -> None:
        if page in self._pages:
            return
        self._pages.append(page)
        self.dialogs.install(page)
        page.on("close", lambda p=page: self._on_close(p))
        page.on("response", self._on_response)

    def _on_response(self, resp) -> None:
        try:
            if resp.status in BLOCK_STATUSES and resp.request.is_navigation_request() \
                    and resp.frame is not None and resp.frame.parent_frame is None:
                self.block_reason = f"HTTP {resp.status} from {resp.url}"
        except Exception:
            pass

    def _on_new_page(self, page: Page) -> None:
        self._adopt(page)

    def _on_close(self, page: Page) -> None:
        if page in self._pages:
            self._pages.remove(page)

    def _stop_pw(self) -> None:
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def close(self) -> None:
        try:
            if self.context is not None:
                self.context.close()
        except Exception as ex:
            self.log.debug("context close: %s", ex)
        self.context = None
        self._pages.clear()
        self._stop_pw()

    @property
    def is_open(self) -> bool:
        if self.context is None:
            return False
        try:
            return any(not p.is_closed() for p in self.context.pages)
        except Exception:
            return False

    # ------------------------------------------------------------------ page access
    @property
    def page(self) -> Page:
        self._pages = [p for p in self._pages if not p.is_closed()]
        if not self._pages:
            if self.context is None:
                raise NavigationError("browser is not open", message_vi="The browser is not open")
            self._adopt(self.context.new_page())
        return self._pages[-1]

    @property
    def current_page(self) -> Page | None:
        """Last open page, or None. Never creates a tab (unlike `page`)."""
        pages = [p for p in self._pages if not p.is_closed()]
        return pages[-1] if pages else None

    def goto(self, path_or_url: str, wait: str = "domcontentloaded") -> None:
        url = path_or_url if "://" in path_or_url else urljoin(self.site.effective_base_url(), path_or_url)
        if "asn.do" in url:
            raise ForbiddenActionError(f"navigation to asn.do refused: {url}")
        try:
            self.page.goto(url, wait_until=wait)
        except PlaywrightError as ex:
            self.check_blocked()
            raise NavigationError(f"goto {url} failed: {ex}", message_vi=f"Cannot open page {url}") from ex
        self.after_navigation()

    # ------------------------------------------------------------------ pace + block detection
    def wait(self, ms: int) -> None:
        """Pump Playwright events while waiting (never time.sleep while a page exists)."""
        page = self.current_page
        if page is None:
            import time
            time.sleep(ms / 1000)
            return
        page.wait_for_timeout(ms)

    def after_navigation(self) -> None:
        """Settle after a page load (human-pace mode), then look for signs that the site is blocking us."""
        pacer = self.pacer
        if pacer is not None and pacer.enabled:
            page = self.current_page
            if page is not None:
                for state, cap in (("load", LOAD_CAP_MS), ("networkidle", IDLE_CAP_MS)):
                    try:
                        page.wait_for_load_state(state, timeout=cap)
                    except PlaywrightError:
                        pass
            pacer.after_navigation()
        self.check_blocked(scan_page=True)

    def check_blocked(self, scan_page: bool = False) -> None:
        """Raise SiteBlockedError on a 403/429/503 main-frame response or (scan_page) a block/captcha page."""
        reason = self.block_reason
        if not reason and scan_page:
            try:
                text = (self.title() + "\n" + self.page.locator("body").inner_text(timeout=2000)).lower()
            except PlaywrightError:
                text = ""
            hit = next((m for m in BLOCK_MARKERS if m in text), "")
            if hit:
                reason = f'page contains "{hit}"'
        if reason:
            raise SiteBlockedError(f"site appears to be blocking us: {reason}",
                                   message_vi=f"The site appears to be blocking automated access ({reason}).",
                                   reason=reason)

    def title(self) -> str:
        try:
            return self.page.title()
        except PlaywrightError:
            return ""

    def url(self) -> str:
        try:
            return self.page.url
        except PlaywrightError:
            return ""

    def is_login_page(self) -> bool:
        if "-- Login" in self.title():
            return True
        try:
            return self.page.locator("input[type=password]").count() > 0
        except PlaywrightError:
            return False

    def screenshot_jpeg(self, path: Path | None = None, quality: int = 55) -> bytes:
        data = self.page.screenshot(type="jpeg", quality=quality, full_page=False, scale="css")
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return data
