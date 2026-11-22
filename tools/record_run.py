"""Developer tool: run the real flow for one tracker file with network recording.

Uses the app's own config, factory list, selectors and browser profile (so an existing EDI login is reused),
records every page request/form post to <run>/network.jsonl, and stops at the first pause for the user
(except the login prompt, where it waits for the login in the opened browser).
Never clicks Validate / Submit ASN (same flow and guards as the app).

    PYTHONPATH=. .venv/bin/python tools/record_run.py <tracker.xlsx> <sheet> "<factory name>"
"""
from __future__ import annotations

import logging
import sys
import time

from edi_assistant.automation.flow.context import make_context
from edi_assistant.automation.flow.runner import FlowRunner
from edi_assistant.automation.netlog import NetworkRecorder
from edi_assistant.automation.selectors import SelectorStore
from edi_assistant.automation.session import BrowserSession
from edi_assistant.core import paths
from edi_assistant.core.config import load_config
from edi_assistant.core.errors import UserAbortError
from edi_assistant.core.events import UserResponse
from edi_assistant.data import detect_header, extract_rows, load_grid, suggest_mapping
from edi_assistant.data.factories import FactoryStore
from edi_assistant.data.planner import PlanOptions, build_plan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("record_run")


def main(xlsx: str, sheet: str, factory_name: str) -> int:
    from edi_assistant.automation import actions
    from edi_assistant.automation.flow import steps
    actions.NAV_TIMEOUT_MS = 60000          # slow site: give every navigation a full minute
    actions.SAVE_NAV_TIMEOUT_MS = steps.SAVE_NAV_TIMEOUT_MS = 60000
    cfg = load_config()
    cfg.flow.dry_run = False
    cfg.browser.default_timeout_ms = max(cfg.browser.default_timeout_ms, 60000)   # the site can take 20 s+ per page
    grid = load_grid(xlsx, sheet)
    det = detect_header(grid)
    mapping, _ = suggest_mapping(det)
    rx = extract_rows(grid, det, mapping)
    fac = next(f for f in FactoryStore().list() if f.name.strip().lower() == factory_name.strip().lower())
    plan = build_plan(rx.lines, fac, PlanOptions("per_master_po", False, cfg.flow.weight_mode, profile=mapping.profile,
                                                tracker_weight_mode=cfg.flow.tracker_weight_mode,
                                                to_sites=cfg.flow.to_sites), xlsx, sheet, "record-run")
    for sh in plan.shipments:
        log.info("plan: %s, %d lines, TO %s, ship %s", sh.label, len(sh.lines), sh.to_site_no, sh.planned_ship_date)
    store = SelectorStore(paths.bundled_selectors_path(), paths.learned_selectors_path())
    store.load()
    session = BrowserSession(cfg.browser, cfg.site, paths.browser_profile_dir(), lambda e: None,
                             logging.getLogger("edi_assistant.session"))
    session.open()

    def ask_user(ev):
        log.warning("PAUSE [%s] %s: %s", ev.kind, ev.step_id, ev.message_vi)
        if ev.kind == "login_required" or (ev.kind == "step_failed" and ev.step_id.startswith("S0")):
            end = time.monotonic() + 600
            ok = 0
            while time.monotonic() < end:   # past the login: no password box on a loaded page, twice in a row
                session.wait(2000)
                ok = ok + 1 if session.title() and not session.is_login_page() else 0
                if ok >= 2:
                    return UserResponse(request_id=ev.request_id, action="continue")
        if ev.kind == "finished_review":
            return UserResponse(request_id=ev.request_id, action="continue")
        return UserResponse(request_id=ev.request_id, action="abort")

    run_dir = paths.run_dir(plan.run_id)
    rec = NetworkRecorder(session.context, run_dir / "network.jsonl")
    log.info("run folder: %s", run_dir)
    ctx = make_context(session, cfg, plan, run_dir, lambda e: None, ask_user, store,
                       log=logging.getLogger("edi_assistant.flow"))
    t0 = time.monotonic()
    try:
        res = FlowRunner(ctx).run(plan)
        log.info("result: %s %s", res.status, res.error)
    except UserAbortError:
        log.warning("stopped at a pause")
    finally:
        rec.close()
        log.info("elapsed %.1fs", time.monotonic() - t0)
        for sh in plan.shipments:
            log.info("shipment %s: web id %s, lines %s", sh.index, sh.web_shipment_id,
                     [ln.status for ln in sh.lines])
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
