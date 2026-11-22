"""AutomationWorker: one long-lived thread that owns the Playwright browser."""
from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime

from edi_assistant.core import paths
from edi_assistant.core.ai_interface import VisionAdvisor
from edi_assistant.core.config import AppConfig
from edi_assistant.core.errors import BrowserLaunchError, EdiAssistantError, UserAbortError
from edi_assistant.core.events import BrowserState, EventSink, LogEvent, NeedsUser, RunFinished, UserResponse
from edi_assistant.core.models import RunResult

from .calibrate import Calibrator
from .commands import (CancelPick, CloseBrowser, Command, Highlight, NavigateTo, OpenBrowser, OpenInspector, Pick,
                       ReloadSelectors, RunPlanCommand, Shutdown, TestKey)
from .flow.context import make_context
from .flow.runner import FlowRunner
from .selectors import SelectorResolver, SelectorStore
from .session import BrowserSession

log = logging.getLogger("edi_assistant.worker")


class AutomationWorker:
    def __init__(self, config: AppConfig, sink: EventSink, advisor: VisionAdvisor | None,
                 selectors: SelectorStore | None = None, profile_dir=None):
        self._config = config
        self._sink = sink
        self._advisor = advisor
        self._profile_dir = profile_dir
        self._lock = threading.Lock()
        self._queue: queue.Queue[Command] = queue.Queue()
        self._abort = threading.Event()
        self._pending: dict[str, queue.Queue[UserResponse]] = {}
        self._thread: threading.Thread | None = None
        self._session: BrowserSession | None = None
        self._calibrator: Calibrator | None = None
        self._running = False
        if selectors is None:
            selectors = SelectorStore(paths.bundled_selectors_path(), paths.learned_selectors_path())
            selectors.load()
        self.selectors = selectors

    # ------------------------------------------------------------------ public API (any thread)
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="edi-automation", daemon=True)
            self._thread.start()

    def stop(self, timeout_s: float = 10) -> None:
        self.submit(Shutdown())
        self._abort.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            if self._thread.is_alive():
                log.warning("worker did not stop within %ss (Playwright inspector still open?)", timeout_s)

    def submit(self, cmd: Command) -> None:
        if isinstance(cmd, RunPlanCommand):
            self._running = True   # visible to the GUI immediately: a second click must not queue a second run
        self._queue.put(cmd)

    def respond(self, resp: UserResponse) -> None:
        q = self._pending.get(resp.request_id)
        if q is None:
            log.warning("response for unknown request %s ignored", resp.request_id)
            return
        q.put(resp)

    def request_abort(self) -> None:
        self._abort.set()

    def update_config(self, config: AppConfig) -> None:
        with self._lock:
            self._config = config

    def set_advisor(self, advisor: VisionAdvisor | None) -> None:
        with self._lock:
            self._advisor = advisor

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_browser_open(self) -> bool:
        s = self._session
        return bool(s is not None and s.is_open)

    # ------------------------------------------------------------------ internals (worker thread)
    def _emit(self, ev) -> None:
        try:
            self._sink(ev)
        except Exception:
            log.exception("event sink failed")

    def _cfg(self) -> AppConfig:
        with self._lock:
            return self._config

    def _pump(self, ms: int = 100) -> None:
        """Let Playwright process events (dialogs, popups, bindings) while idle."""
        try:
            page = self._session.current_page if self._session is not None else None
            if page is None:
                time.sleep(ms / 1000)
                return
            page.wait_for_timeout(ms)
        except Exception:
            time.sleep(ms / 1000)

    def _loop(self) -> None:
        while True:
            try:
                if self.is_browser_open:
                    try:
                        cmd = self._queue.get_nowait()
                    except queue.Empty:
                        self._pump(100)
                        continue
                else:
                    cmd = self._queue.get()
            except Exception:
                continue
            if isinstance(cmd, Shutdown):
                self._close_browser()
                return
            try:
                self._dispatch(cmd)
            except Exception as ex:
                log.exception("command %s failed", type(cmd).__name__)
                msg = getattr(ex, "message_vi", "") or str(ex)
                self._emit(LogEvent(level="ERROR", message=f"{type(cmd).__name__}: {msg}"))
                if isinstance(cmd, RunPlanCommand):
                    plan = cmd.plan
                    now = datetime.now().isoformat(timespec="seconds")
                    self._emit(RunFinished(result=RunResult(
                        run_id=plan.run_id if plan else "", status="failed", shipments=plan.shipments if plan else [],
                        results_csv="", started_at=now, finished_at=now, error=str(ex))))
                    self._running = False
                    self._emit_state()

    def _ensure_session(self) -> BrowserSession:
        cfg = self._cfg()
        s = self._session
        if s is not None and s.is_open:
            s.site = cfg.site
            return s
        if s is not None:
            s.close()
        s = BrowserSession(cfg.browser, cfg.site, self._profile_dir or paths.browser_profile_dir(), self._emit,
                           logging.getLogger("edi_assistant.session"))
        s.open()
        self._session = s
        resolver = SelectorResolver(self.selectors, log)
        self._calibrator = Calibrator(s, self.selectors, resolver, self._emit, log)
        return s

    def _close_browser(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        self._calibrator = None
        self._emit_state()

    def _emit_state(self) -> None:
        s = self._session
        if s is None or not s.is_open:
            self._emit(BrowserState(is_open=False, url="", logged_in=None))
            return
        try:
            logged = False if s.is_login_page() else None
            self._emit(BrowserState(is_open=True, url=s.url(), logged_in=logged))
        except Exception:
            self._emit(BrowserState(is_open=True, url="", logged_in=None))

    def ask_user(self, ev: NeedsUser) -> UserResponse:
        q: queue.Queue[UserResponse] = queue.Queue(1)
        self._pending[ev.request_id] = q
        self._emit(ev)
        try:
            while True:
                if self._abort.is_set():
                    raise UserAbortError("aborted by user", message_vi="Aborted by user")
                try:
                    return q.get(timeout=0.01)
                except queue.Empty:
                    self._pump(250)
        finally:
            self._pending.pop(ev.request_id, None)

    def _dispatch(self, cmd: Command) -> None:
        if isinstance(cmd, OpenBrowser):
            s = self._ensure_session()
            if cmd.navigate_home:
                s.goto("gateway/inbox.do")
                if s.is_login_page():
                    from .autologin import DONE, try_auto_login
                    if try_auto_login(s) == DONE:
                        s.goto("gateway/inbox.do")
            self._emit_state()
        elif isinstance(cmd, CloseBrowser):
            self._close_browser()
        elif isinstance(cmd, NavigateTo):
            self._ensure_session().goto(cmd.path)
            self._emit_state()
        elif isinstance(cmd, RunPlanCommand):
            self._run_plan(cmd)
        elif isinstance(cmd, ReloadSelectors):
            self.selectors.load()
        elif isinstance(cmd, Highlight):
            self._ensure_session()
            self._calibrator.highlight(cmd.key, cmd.vars)
        elif isinstance(cmd, Pick):
            self._ensure_session()
            self._calibrator.pick(cmd.key)
        elif isinstance(cmd, CancelPick):
            if self._calibrator:
                self._calibrator.cancel_pick()
        elif isinstance(cmd, TestKey):
            s = self._ensure_session()
            try:
                _, cand = SelectorResolver(self.selectors, log).resolve(s.page, cmd.key, cmd.vars, timeout_ms=2000)
                self._emit(LogEvent(level="INFO", message=f"{cmd.key}: found via {cand.describe()}"))
            except EdiAssistantError as ex:
                self._emit(LogEvent(level="WARNING", message=f"{cmd.key}: not found ({ex})"))
        elif isinstance(cmd, OpenInspector):
            self._ensure_session()
            self._calibrator.open_inspector()

    def _run_plan(self, cmd: RunPlanCommand) -> None:
        plan = cmd.plan
        cfg = self._cfg()
        self._abort.clear()
        self._running = True
        try:
            s = self._ensure_session()
            with self._lock:
                advisor = self._advisor if cfg.ai.enabled else None
            ctx = make_context(s, cfg, plan, paths.run_dir(plan.run_id), self._emit, self.ask_user, self.selectors,
                               advisor=advisor, abort_event=self._abort, log=logging.getLogger("edi_assistant.flow"))
            FlowRunner(ctx).run(plan)
        finally:
            if self._session is not None:
                self._session.pacer = None   # human-pace delays apply to runs only, never to manual commands
            self._running = False
            self._emit_state()
