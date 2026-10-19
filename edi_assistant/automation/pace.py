"""Human-pace mode: randomized, abort-interruptible delays and shipment throttling.

All sleeps go through `wait` (normally `page.wait_for_timeout`, never time.sleep) so the Playwright event loop keeps
pumping while we wait, and are sliced so an abort is honoured within ~250 ms.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable

from edi_assistant.core.config import PaceConfig
from edi_assistant.core.errors import UserAbortError

SLICE_MS = 250


def as_range(value, default: tuple[int, int]) -> tuple[int, int]:
    """Coerce a config value ([lo, hi] / scalar / junk) into an ordered non-negative (lo, hi)."""
    try:
        vals = [int(x) for x in value]
        lo, hi = (vals[0], vals[1]) if len(vals) >= 2 else (vals[0], vals[0])
    except (TypeError, ValueError, IndexError):
        try:
            lo = hi = int(value)
        except (TypeError, ValueError):
            lo, hi = default
    lo, hi = max(0, lo), max(0, hi)
    return (lo, hi) if lo <= hi else (hi, lo)


class Pacer:
    def __init__(self, cfg: PaceConfig, abort_event: threading.Event | None = None,
                 wait: Callable[[int], None] | None = None, log: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic, rng: random.Random | None = None,
                 history: list[float] | None = None):
        self.cfg = cfg
        self.abort_event = abort_event or threading.Event()
        self._wait = wait or (lambda ms: time.sleep(ms / 1000))
        self._log = log or (lambda msg: None)
        self._clock = clock
        self._rng = rng or random.Random()
        self.history: list[float] = history if history is not None else []   # monotonic start time of each shipment
        self.slept_ms = 0   # total requested sleep (diagnostics/tests)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled)

    def _check_abort(self) -> None:
        if self.abort_event.is_set():
            raise UserAbortError("aborted by user", message_vi="Aborted by user")

    def pick(self, rng_cfg, default: tuple[int, int]) -> int:
        lo, hi = as_range(rng_cfg, default)
        return self._rng.randint(lo, hi)

    # ------------------------------------------------------------------ sleeping
    def sleep_ms(self, ms: float) -> None:
        """Interruptible sleep that keeps Playwright pumping."""
        self._check_abort()
        if ms <= 0:
            return
        self.slept_ms += int(ms)
        end = self._clock() + ms / 1000
        while True:
            self._check_abort()
            remaining_ms = (end - self._clock()) * 1000
            if remaining_ms <= 0:
                return
            self._wait(int(min(SLICE_MS, max(1, remaining_ms))))

    def sleep_action(self) -> None:
        if self.enabled:
            self.sleep_ms(self.pick(self.cfg.action_delay_ms, (400, 1200)))

    def after_navigation(self) -> None:
        if self.enabled:
            self.sleep_ms(self.pick(self.cfg.nav_delay_ms, (1000, 2000)))

    def type_delay(self) -> int:
        return self.pick(self.cfg.type_delay_ms, (30, 80))

    # ------------------------------------------------------------------ shipment throttling
    def before_shipment(self, started_in_run: int) -> None:
        """Call before starting each shipment; `started_in_run` = shipments already started in this run."""
        if not self.enabled:
            return
        self._check_abort()
        lo, hi = as_range(self.cfg.between_shipments_s, (20, 60))
        if started_in_run > 0 and hi > 0:
            secs = self._rng.randint(lo, hi)
            self._log(f"human pace: waiting {secs}s before the next shipment")
            self.sleep_ms(secs * 1000)
        limit = int(self.cfg.max_shipments_per_hour or 0)
        if limit > 0:
            while True:
                now = self._clock()
                self.history[:] = [t for t in self.history if now - t < 3600]
                if len(self.history) < limit:
                    break
                wait_s = int(self.history[0] + 3600 - now) + 1
                self._log(f"human pace: hourly limit of {limit} shipments reached, waiting {wait_s}s")
                self.sleep_ms(wait_s * 1000)
        self.history.append(self._clock())
