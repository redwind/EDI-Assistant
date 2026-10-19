"""FlowRunner: state machine that drives the steps for every shipment of a plan."""
from __future__ import annotations

import time
from datetime import datetime

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from edi_assistant.core.errors import (DataMismatchError, EdiAssistantError, ElementNotFoundError, ForbiddenActionError,
                                       NavigationError, PostconditionFailed, SiteBlockedError, StepSkipped,
                                       UserAbortError)
from edi_assistant.core.events import Progress, RunFinished, RunStarted, StepFinished, StepStarted
from edi_assistant.core.models import Flag, PlannedLine, RunPlan, RunResult, ShipmentPlan

from ..dom_snapshot import capture
from . import steps as S
from .context import FlowContext

MAX_ATTEMPTS = 10   # safety net against endless retry loops
MAX_LOGIN_BOUNCES = 2   # more bounces than this within a run = the site is logging us out on purpose


def estimate_steps(plan: RunPlan) -> int:
    return 1 + sum(3 * len(sh.master_pos) + 2 + 2 + 1 + 2 * len(sh.lines) + 2 for sh in plan.shipments)


class FlowRunner:
    def __init__(self, ctx: FlowContext):
        self.ctx = ctx
        self._index = 0
        self._total = 0

    # ------------------------------------------------------------------ block handling
    def _handle_block(self, e: SiteBlockedError, step: S.Step) -> None:
        """Stop and hand over to the user (abort / continue). No automatic retry: continue = user resolved it."""
        ctx = self.ctx
        ctx.warn(f"SITE BLOCKED at {step.id}: {e.message}")
        snap = capture(ctx.session, ctx.run_dir, step.id)
        ctx.ask("site_blocked",
                f"The site seems to be blocking automated access ({e.ctx.get('reason', e.message)}). "
                "Stopped to protect your account. Resolve it in the browser (wait, solve any verification, or log in again), "
                "then press Continue, or Abort the run.",
                options=["continue", "abort"], step_id=step.id, screenshot_path=snap.screenshot_path)
        ctx.session.block_reason = ""
        ctx.login_bounces = 0

    # ------------------------------------------------------------------ step execution
    def run_step(self, step: S.Step) -> bool:
        """Run one step with retry/heal/ask logic. Returns False when the step was skipped."""
        ctx = self.ctx
        self._index += 1
        sh = ctx.current_shipment
        po = step.line.po_line.po_line_id if step.line is not None else ""
        ctx.emit(StepStarted(step_id=step.id, title_vi=step.title_vi, shipment_index=sh.index if sh else 0,
                             po_line_id=po, index=self._index, total=self._total))
        if self._total:
            ctx.emit(Progress(percent=min(99, int(100 * self._index / self._total)), message_vi=step.title_vi))
        t0 = time.monotonic()
        attempt = 0
        for _ in range(MAX_ATTEMPTS):
            try:
                step.act(ctx)
                if step.check(ctx):
                    ctx.emit(StepFinished(step_id=step.id, status="ok", duration_s=time.monotonic() - t0))
                    return True
                raise PostconditionFailed(f"postcondition failed: {step.id}", message_vi="Step postcondition not met",
                                          step_id=step.id)
            except UserAbortError:
                raise
            except SiteBlockedError as e:
                self._handle_block(e, step)
                attempt += 1
                continue
            except StepSkipped:
                ctx.emit(StepFinished(step_id=step.id, status="skipped", duration_s=time.monotonic() - t0))
                return False
            except (ElementNotFoundError, PostconditionFailed, DataMismatchError, NavigationError,
                    PlaywrightTimeoutError, PlaywrightError) as e:
                if not isinstance(step, S.S0EnsureLoggedIn) and ctx.session.is_login_page():
                    ctx.login_bounces += 1
                    if ctx.login_bounces > MAX_LOGIN_BOUNCES:
                        self._handle_block(SiteBlockedError(
                            "bounced to the login page repeatedly",
                            message_vi="bounced to the login page repeatedly",
                            reason=f"sent back to the login page {ctx.login_bounces} times in one run"), step)
                        attempt += 1
                        continue
                    try:
                        S.S0EnsureLoggedIn().act(ctx)
                    except SiteBlockedError as be:
                        self._handle_block(be, step)
                    attempt += 1
                    continue
                snap = capture(ctx.session, ctx.run_dir, step.id)
                if isinstance(e, ElementNotFoundError) and attempt == 0:
                    key = e.ctx.get("key", "")
                    if key and "." in key and ctx.healer.heal_locator(ctx.page, key, ctx.vars(step.line), snap) is not None:
                        attempt += 1
                        continue
                explanation = ctx.healer.explain(step.id, step.title_vi, e, snap)
                msg = getattr(e, "message_vi", "") or str(e)
                resp = ctx.ask(
                    "step_failed",
                    f'Step "{step.title_vi}" failed: {msg}. You can fix it manually in the browser, then press Continue.',
                    step_id=step.id, screenshot_path=snap.screenshot_path,
                    ai_explanation_vi=(explanation.explanation_vi + "\n" + explanation.user_action_vi) if explanation else "")
                if resp.action == "skip":
                    ctx.emit(StepFinished(step_id=step.id, status="skipped", detail=str(e),
                                          duration_s=time.monotonic() - t0))
                    return False
                try:
                    if step.check(ctx):
                        ctx.emit(StepFinished(step_id=step.id, status="ok", detail="manual",
                                              duration_s=time.monotonic() - t0))
                        return True
                except (EdiAssistantError, PlaywrightError):
                    pass
                attempt += 1
        raise PostconditionFailed(f"too many attempts: {step.id}", message_vi="Too many attempts", step_id=step.id)

    # ------------------------------------------------------------------ shipment flow
    @staticmethod
    def _skip_master(sh: ShipmentPlan, master: str, why: str) -> None:
        for ln in sh.lines:
            if ln.po_line.master_po == master and ln.status == "pending":
                ln.status = "skipped"
                ln.error = why
        sh.po_windows.pop(master, None)

    def _run_shipment(self, sh: ShipmentPlan, is_last: bool) -> None:
        ctx = self.ctx
        ctx.current_shipment = sh
        sh.status = "running"
        first_of: dict[str, PlannedLine] = {}
        for ln in sh.lines:
            first_of.setdefault(ln.po_line.master_po, ln)
        for master in sh.master_pos:
            line = first_of[master]
            ctx.current_line = line
            if not (self.run_step(S.S1InboxSearch(line)) and self.run_step(S.S2OpenPODetail(line))
                    and self.run_step(S.S3ReadDates(line))):
                self._skip_master(sh, master, "skipped: PO not available")
        active = [ln for ln in sh.lines if ln.status == "pending"]
        if not active:
            sh.status = "failed"
            ctx.warn(f"shipment {sh.index}: no usable PO lines")
            ctx.results.write(ctx.plan)
            return
        self.run_step(S.S4ComputeShipDate())
        first = active[0]
        ctx.current_line = first
        v = ctx.vars(first)
        on_detail = "view_order.do" in ctx.session.url() and ctx.actions.exists("po.page_marker", v, 800)
        if not on_detail:
            self.run_step(S.S1InboxSearch(first))
            self.run_step(S.S2OpenPODetail(first))
        self.run_step(S.S5CreateNewShipment(first))
        self.run_step(S.S6FillHeaderSave())
        if sh.status == "dry_run" or ctx.plan.dry_run:
            # G4 hard stop: nothing after the header form may run in dry-run, even when S6 was skipped/failed
            # (S7's "Selected Purchase Orders >>" would persist the header).
            if sh.status != "dry_run":
                sh.status = "dry_run"
                ctx.warn(f"shipment {sh.index}: dry run ended before Save (header step not completed)")
            ctx.results.write(ctx.plan)
            return
        self.run_step(S.S7AddPurchaseOrders())
        for line in sh.lines:
            if line.status in ("added",):
                ctx.current_line = line
                if self.run_step(S.S8CreateCarton(line)):
                    self.run_step(S.S8bSetPartial(line))
                else:
                    line.status = "skipped"
        if any(l.status == "carton_done" for l in sh.lines):
            self.run_step(S.S9EnterWeights())
        self.run_step(S.S10FinishShipment(is_last))
        sh.status = "done"
        ctx.results.write(ctx.plan)

    def _final_review(self, plan: RunPlan) -> None:
        """One summary pause after all shipments (multi-shipment runs without per-shipment review)."""
        ctx = self.ctx
        if ctx.config.flow.review_between_shipments or len(plan.shipments) < 2 or plan.dry_run:
            return
        parts = []
        for sh in plan.shipments:
            warn = sorted({f.code for f in sh.flags if f.severity != "info"}
                          | {f.code for pl in sh.lines for f in pl.po_line.flags + (pl.carton.flags if pl.carton else [])
                             if f.severity != "info" and f.code not in ("weight_zero",)})
            parts.append(f"{', '.join(sh.master_pos)}: Web Shipment ID {sh.web_shipment_id or '-'} [{sh.status}]"
                         + (f" warnings: {', '.join(warn)}" if warn else ""))
        ctx.ask("finished_review",
                "All shipments were processed. Review them in Drafts in the browser and click Submit ASN yourself "
                "when ready.\n" + "\n".join(parts),
                options=["continue"], step_id="run")

    # ------------------------------------------------------------------ run
    def run(self, plan: RunPlan | None = None) -> RunResult:
        ctx = self.ctx
        plan = plan or ctx.plan
        ctx.plan = plan
        started = datetime.now().isoformat(timespec="seconds")
        self._total = estimate_steps(plan)
        ctx.emit(RunStarted(run_id=plan.run_id, total_steps=self._total))
        status, error = "done", ""
        try:
            self.run_step(S.S0EnsureLoggedIn())
            n = len(plan.shipments)
            for i, sh in enumerate(plan.shipments):
                if ctx.pacer is not None:
                    ctx.pacer.before_shipment(i)
                try:
                    self._run_shipment(sh, is_last=(i == n - 1))
                except (UserAbortError, ForbiddenActionError, SiteBlockedError):
                    raise   # never continue after an abort / guard trip / block
                except Exception as e:   # isolate one failing shipment from the others
                    ctx.log.exception("shipment %s failed", sh.index)
                    sh.status = "failed"
                    sh.flags.append(Flag("shipment_failed", str(e), "error"))
                    for ln in sh.lines:
                        if ln.status in ("pending", "added", "carton_done"):
                            ln.status, ln.error = "failed", str(e)
                    ctx.results.write(plan)
                    if i < n - 1:
                        ctx.ask("shipment_failed",
                                f"Shipment {sh.index} ({sh.label}) failed: {getattr(e, 'message_vi', '') or e}. "
                                "The browser is left as is. Continue with the next shipment, or Abort the run?",
                                options=["continue", "abort"], step_id="shipment")
            self._final_review(plan)
        except UserAbortError:
            status = "aborted"
            for sh in plan.shipments:
                if sh.status in ("running", "pending"):
                    sh.status = "aborted"
        except Exception as e:   # unrecoverable (incl. ForbiddenActionError): leave browser as-is
            ctx.log.exception("run failed")
            status, error = "failed", str(e)
            for sh in plan.shipments:
                if sh.status == "running":
                    sh.status = "failed"
        if status == "done":
            sts = [sh.status for sh in plan.shipments]
            if sts and all(s == "dry_run" for s in sts):
                status = "dry_run"
            elif all(s == "done" for s in sts):
                status = "done"
            elif any(s == "done" for s in sts):
                status = "partial"
            else:
                status = "failed"
        try:
            ctx.results.write(plan)
        except Exception:
            ctx.log.exception("results write failed")
        result = RunResult(run_id=plan.run_id, status=status, shipments=plan.shipments,
                           results_csv=str(ctx.results.csv_path), started_at=started,
                           finished_at=datetime.now().isoformat(timespec="seconds"), error=error,
                           ai_calls_used=ctx.healer.calls_used)
        try:
            ctx.results.write_json(result)
        except Exception:
            ctx.log.exception("run.json write failed")
        ctx.emit(RunFinished(result=result))
        return result
