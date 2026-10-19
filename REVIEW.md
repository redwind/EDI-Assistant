# EDI Assistant — Architect's integration review

Scope: WP-A (core+data), WP-B (automation+mock_edi), WP-C (app+packaging) as integrated on 2026-10-18.
Method: full read of the seams (`app/main.py`, `main_window.py`, `worker_bridge.py` ↔ `automation/worker.py`,
`commands.py`, `core/events.py` ↔ `data/*`), of every safety-relevant module (`actions.py`, `dialogs.py`,
`session.py`, `healing.py`, `calibrate.py`, `picker.js`, `flow/*`), the packaging files, and the tests; plus one new
end-to-end test that drives the **real** GUI stack headless against the mock.

## 1. Verdict

**Integrates correctly; ship-blocking safety holes found and closed.** The three work packages fit together without
contract drift: event/command names and fields match on both sides, the bridge delivers worker events on the GUI
thread, Playwright objects are only ever touched on the worker thread, and the data facade is used exactly as §3.17
prescribes. The new `tests/test_integration_app.py` runs MainWindow → WorkerBridge → AutomationWorker (headless
chromium) → MockServer with the sample Excel through auto-mapping and passes in ~13 s with **zero pauses** and
`submit_called == False`.

The safety audit found three real holes (dry-run could persist the header via a skipped S6; learned/AI locators could
type into a password box; AI/picked candidates could be learned for guarded elements) and one GUI race (double Start
queues a second run). All four are fixed below with tests. Business logic matches the binding user decisions,
including the two just confirmed (past ship date → today; weight = total G.W. per row). Packaging is plausible but has
a few concrete issues (P2) that cannot be verified without a Windows build.

## 2. What I fixed (small, surgical, all covered by tests)

| # | File(s) | Change | Why |
|---|---|---|---|
| F1 | `edi_assistant/automation/flow/runner.py:127-135` | After `S6FillHeaderSave`, return when `ctx.plan.dry_run` even if `sh.status != "dry_run"` (sets it, warns, writes results). | **G4 hole.** If S6 failed before reaching its dry-run check (e.g. an unresolvable field) and the user chose *Bỏ qua*, the runner continued into S7, whose first action clicks `Selected Purchase Orders >>` — which **saves the header** on the real site. Test: `test_e2e_mock.py::test_dry_run_skipped_header_step_never_persists`. |
| F2 | `edi_assistant/automation/actions.py:57,124-127` | `fill_locator` raises `ForbiddenActionError` when the target is `input[type=password]` (`is_password_field`). | **G9 hole.** The flow never *intends* to fill a password, but a learned or AI-proposed locator for any `*_input` key could resolve to the password box; nothing stopped `fill()`. Test: `test_actions_guard.py::test_fill_refuses_password_field`. |
| F3 | `edi_assistant/automation/actions.py:32-54` + `healing.py:60-66` | Extracted the click guard into pure `forbidden_reason_from_attrs()` / `forbidden_reason(loc)`; `Healer.heal_locator` now rejects (and logs) any AI candidate that resolves to a guarded element or a password box **before** it is learned. | Guard was click-time only; a guarded candidate could still be persisted to `selectors.learned.yaml` and become the first candidate of e.g. `ship.save_button`. Test: `test_healing.py::test_heal_rejects_guarded_elements`. |
| F4 | `edi_assistant/automation/picker.js` (payload now carries `element`+`password`) + `calibrate.py:76-87` | Calibrator refuses to learn a user-picked element that is guarded/password and emits `CalibrationResult(saved=False)`. The attribute capture is done in JS because `_on_picked` runs inside a Playwright binding callback where further sync-API calls **deadlock** (verified: `test_pick_flow_saves_learned` hung with an in-callback `evaluate`). | Same persistence hole as F3 for the human path. Test: `test_calibrate.py::test_pick_refuses_guarded_element`. |
| F5 | `edi_assistant/automation/worker.py:60-63` | `submit(RunPlanCommand)` sets `_running = True` synchronously. | **Race:** `MainWindow.start_run` calls `_update_buttons()` right after `submit()`, but `is_running` only became true when the worker thread dequeued the command — a second click within that window queued a **second full run** that would execute after the first. Asserted in `test_integration_app.py` (`worker.is_running and not win.btn_start.isEnabled()` immediately after Start). |
| F6 | `core/config.py:52`, `core/dates.py:110-114`, `flow/steps.py:197-205`, `tests/data/test_dates.py:48` | Binding decision: a past midpoint → **today**, always (previously `w.late` when the whole window was past — a past date the portal rejects). New single switch `flow.past_date_policy: "clamp_today" (default) \| "ask"`; `"ask"` pauses in S4 with a date input (default = today). | Requested by the user; previously there was no switch (`FlowContext.today` is only a test clock). Tests: `tests/automation/test_ship_date_policy.py` (3 cases). |
| F7 | `tests/test_integration_app.py` (new) | Real stack headless: MockServer → AutomationWorker (chromium headless) → WorkerBridge → MainWindow (offscreen); sample Excel through `load_excel` + auto mapping + `MappingDialog` accept; factory auto-picked from the footer; Start; pauses answered through the real `PauseDialog`; asserts `RunFinished`/`done`, Web Shipment ID, results.csv (2 rows), mock state (2 POs, cartons 85 × qty/carton 6, Partial, 1020.00 KG, ship date per rules, CN, `submit_called False`), history row, `_ASN.xlsx` write-back, template learned, browser left open. | Task 1. No mock seeding was needed: `MockState.seed_default()` already contains 580367401/580367301. |

Everything else in this document is a finding, not a change.

## 3. Safety audit (task 2) — what was verified by reading + tests

| Guard | Status | Evidence |
|---|---|---|
| G1/G8 never click Submit ASN / Cancel / Clear Values / Validate / Remove | OK (+F3/F4 close the persistence side) | `actions.py::forbidden_reason_from_attrs` checks the element **and** its closest button/link: name/id ∈ {btnSubmitASN, cancelShipment, btnCancel}, `asn.do` in onclick, `/submit/i` in value/text, `validateShipment` unless `flow.click_validate`, text == "remove". Every click path (`click`, `click_locator`, S2's row link, S8's row buttons) goes through `click_locator → _guard_click`. The only raw Playwright clicks are `row.locator("input[type='checkbox']").first.check()` (S7/S8) — checkboxes cannot be any guarded control. `select_locator`/`check` never click buttons. Tests: `test_actions_guard.py` (7 forbidden elements + the sneaky `asn.do` onclick + "Please Submit" text). |
| G7 never navigate to `asn.do` | OK | `session.goto` refuses any URL containing `asn.do` (`ForbiddenActionError`, not in the runner's retry list → run fails, browser left as-is); `context.route("**/asn.do*", abort)` on every context; `po_dates._pdf_urls` filters `asn.do`. Tests: `test_route_block_aborts_asn`, `test_goto_refuses_asn`, `test_submit_never_reached`. |
| G9 never type a password | OK after F2 | S0 only navigates and asks (`login_required`); F2 blocks the indirect path. |
| G2 confirm() dialogs | OK | `DialogPolicy`: dismiss by default; accept only when armed by `expect_accept(pattern)` **and** the message matches **and** not matching `ALWAYS_DISMISS_RE` (submit/transmit/cancel shipment/delete/remove); arm is one-shot and expires (20 s). Arming happens only immediately before the three "Add Selected" clicks. Tests: `test_dialogs.py` (6 cases incl. catch-all arm vs forbidden text). Residual: an armed expectation outlives a failed Add click for ≤20 s; a second matching "add" confirm in that window would be accepted — semantically identical action, acceptable. |
| G4 dry-run stops before the first Save | OK after F1 | S6 asks `dry_run_stop` before `click('ship.save_button')` and raises `StepSkipped`; the runner now hard-stops after S6 whenever `plan.dry_run`. S1–S5 only read pages / click `Create New Shipment` (no persistence; opening `view_order.do` marks the PO read — documented, accepted). |
| Calibrate / picker cannot click | OK | `highlight` = `evaluate(outline)`; `pick` = inject JS + `expose_binding`; `TestKey` = resolve only; `OpenInspector` = `page.pause()`. picker.js's capture-phase `click` handler calls `preventDefault/stopPropagation/stopImmediatePropagation` on `document` so target `onclick`s never run while armed, and removes itself after one pick (verified by `test_pick_flow_saves_learned`: the next click is a normal click). |
| Healing passes through the guard | OK after F3 | The runner discards the healed locator and re-runs `act()`, so a healed click still goes through `_guard_click`; F3 additionally prevents learning the candidate at all. |
| G6 abort | OK | `_check_abort` before every action and inside every poll loop; `ask_user` polls the abort flag; `UserAbortError` → status `aborted`, browser left open (`test_worker_ask_user_and_abort`). |
| G3 no Enter key | OK | `grep keyboard.press` → none. |
| Mock assertion `submit_called False` | OK | asserted in every e2e test and in the new integration test. |

## 4. Business logic vs user decisions (task 3)

| Decision | Implementation | Status |
|---|---|---|
| PO suffix: `5803674` → `580367401`, `5803673` → `580367301` (01, 02… per master PO when the sheet has no line column) | `data/rows.py::assign_line_numbers` (per-master counters, skips used numbers, `line_assigned` info flag); `POLine.po_line_id = f"{master}{line:02d}"`. Verified on the sample: `['580367401','580367301']`. | OK |
| One shipment per file (default) | `FlowConfig.grouping="per_file"` → `planner.build_plan` makes one `ShipmentPlan`; radio in the window mirrors cfg; `per_master_po` available. | OK |
| Ship date = midpoint of the intersection of all PO windows; if no intersection → midpoint of first PO + pause | `core/dates.py::compute_shipping_date` (`intersect` → `midpoint = early + days//2`; `no_date_intersection` flag → S4 asks `continue/abort`). Dates read by the 4-rung ladder (`po_dates.py`: DOM → PDF/pypdf → AI vision → user input). | OK |
| Past ship date → **today** (binding, no prompt) | F6: always `today` when midpoint < today; `flow.past_date_policy="clamp_today"` default; `"ask"` available in YAML (not yet in the Settings dialog — see P2-6). | OK |
| Cartons Per Site = packages; Qty Per Carton = quantity / packages (÷ prepack when the item is AS with a `N EA` sub-row) | `core/quantities.py::compute_carton_plan`; S8 reads `carton.item_prepack_row`; non-integer → `non_integer_carton` pause with two inputs or skip. Sample: 510/85 = 6 → qty/carton 6, cartons 85 (asserted on mock). | OK |
| Weight = total G.W. of the row, 2 dp, KG (binding) | `FlowConfig.weight_mode="total_gw"` → `weight_for_line` quantize `0.01` HALF_UP → `format_weight` → `"1020.00"`; `weight_um="KG"` selected per row in S9; `per_carton_gw` remains a non-default option in Settings. | OK |
| Complete/Partial = Partial, always | `FlowConfig.complete_partial="Partial"`; S8b per line + postcondition re-reads the select. | OK |
| From address = selected factory; From Site No only when the factory has one | S6 fills name/address1/address2/city/state/zip from `FactoryAddress`; `ship.from_site_no` selected only if `factory.site_no`. Factory suggested from the Excel footer (`SUMEC TEXTILE COMPANY LIMITED`), remembered per template. | OK |
| Country: list has only US/CA/CN; Vietnam → pause | `select('ship.from_country', label=country, label_prefix=country[:5])` → `DataMismatchError` → `country_not_in_list` pause ("bấm More.."), then verifies the select is non-empty. `factory_from_excel_footer` maps "vietnam/việt nam" → `VIETNAM`, default `CHINA` → matches option text `CHINA` (value `CN`). | OK |
| Header defaults: Ship to DC (3), Containerized Ocean (O), SCAC MAEU → carrier auto-fill, BOL/PRO "Unknown", Shipment With Cartons | S6 steps 1–6, all config-driven. | OK |
| Never Submit; stop with a notification; `finished_review` pause only between shipments | S10 + `MainWindow._on_run_finished` notification; last shipment does not block. | OK |

## 5. Prioritized fix list for the implementer

Line numbers refer to the files as they are after my changes.

### P0 — safety
Nothing open. (All P0 items found were fixed: F1–F5.)

### P1 — correctness / robustness
1. **`automation/calibrate.py:55-57` — `expose_binding` keyed by `id(page)`.** If the page object is replaced (user closed the tab, `session.page` created a new one) and the new object reuses the id, nothing happens; if a *different* object with a new id is the same Playwright page after a reconnect, `expose_binding` raises "function already registered" and the `Pick` command fails. Fix: key by `page` identity in a `weakref.WeakSet`, or wrap `expose_binding` in `try/except PlaywrightError` and treat "already registered" as success.
2. **`automation/worker.py:54-58` + `calibrate.py:93-95` — `OpenInspector` blocks the worker in `page.pause()`.** While the inspector is open, `worker.stop()` on quit waits 10 s and then leaks the thread/browser, and `request_abort` has no effect. Fix: in `stop()`, if `self._calibrator` has an inspector open, call `self._session.page.evaluate("playwright.resume()")` is not possible from another thread — instead run `page.pause()` only when `cfg.browser.headless is False`, document in the dialog that the inspector must be closed before quitting, and in `stop()` log a warning when the join times out. (Low effort; no silent hang.)
3. **`app/main_window.py:554-560` — `open_calibrate` builds a second `SelectorStore`** instead of using `self.worker.selectors`. Both persist to the same `selectors.learned.yaml` and the dialog calls `refresh()`/`ReloadSelectors`, so it works, but the "Đã học" counts can be stale between a pick and the next refresh and the two stores can race on `_write_learned` (atomic replace, so no corruption). Fix: `CalibrateDialog(self.worker.selectors, ...)` and drop the local store; the `SelectorStore` is only mutated from the worker thread or the GUI thread when no pick is armed.
4. **`app/main.py:59-66, 85-87` — `--mock` leaks into the saved config if Settings is saved mid-session.** `open_settings` calls `save_config(self.cfg)` (`main_window.py:542`) while `cfg.site.use_mock/mock_url` hold the temporary mock values; a crash before exit also persists them. Fix: keep the override out of `cfg` — add `AppConfig.runtime_mock_url: str = ""` excluded from `config_to_dict` (or a module-level override in `SiteConfig.effective_base_url`), or have `save_config` receive a copy with `saved_site` restored when `mock is not None`.
5. **`automation/worker.py:103-108` `_pump` + `session.page`** — `BrowserSession.page` silently opens a new tab when all tabs are closed (`session.py:111-116`). During idle pumping this means closing the last tab re-opens a blank tab once (only when `is_open` still reports true, i.e. the context survived). Fix: in `_pump`, use `self._session.context.pages[0].wait_for_timeout` guarded by `if not pages: time.sleep`, or make `page` creation explicit (`ensure_page()`) and have `_pump` use a non-creating accessor.
6. **`flow/runner.py:60-62` — login detected mid-step re-runs `S0EnsureLoggedIn().act()` then `continue`s without incrementing `attempt`**; if the user never logs in, the loop still ends via `MAX_ATTEMPTS=10` but each pass asks `login_required` again. Acceptable, but add `attempt += 1` there so the 10-attempt cap also covers this path.
7. **`flow/steps.py:178,362` — local `from edi_assistant.core.models import Flag` inside steps**; hoist to the module imports (cosmetic, but it hides a cyclic-import fear that does not exist).

### P2 — packaging / UX / hygiene
1. **`packaging/hooks/hook-playwright.py:4-5`** — the second `collect_data_files("playwright", subdir="driver")` duplicates entries already collected by the first call (harmless). The real risk is that `pyinstaller-hooks-contrib` also ships a `hook-playwright.py`; user `hookspath` hooks take precedence, so ours wins — fine. Add an assertion in `build_windows.ps1` (already present for `node.exe`/`cli.js`) for `_internal/playwright/driver/package/lib/` as well (driver ≥1.45 needs it).
2. **`packaging/build_windows.ps1:30`** — `[int]$_` throws on pre-release versions (`0.1.0rc1`). Fix: `($Version -replace '[^0-9.].*$','').Split('.')`.
3. **`installer/edi_assistant.iss:16`** — `ArchitecturesInstallIn64BitMode=x64compatible` requires Inno Setup ≥ 6.3; `choco install innosetup` currently gives 6.4 so CI is fine, but pin `--version` in the workflow or add `#if Ver < EncodeVer(6,3,0) #error` for local builds. Also add `CloseApplications=yes` + `RestartApplications=no` so upgrades work while the app sits in the tray.
4. **`core/paths.py:27-39`** — spec §9 fallback (portable folder on a read-only location → `%APPDATA%` + warning) is not implemented; `_mk` will raise `PermissionError` at startup before the GUI exists. Fix: wrap `_mk(exe_dir()/"data")` in `try/except OSError` and fall back to the roaming dir with a logged warning.
5. **Frozen-only runtime assumptions (cannot be run here):** `calibrate.py::picker_source` reads `Path(__file__).with_name("picker.js")` (works: datas puts it next to the module in `_internal/edi_assistant/automation/`); `paths.bundled_selectors_path()` uses `importlib.resources.files` (PyInstaller ≥ 5 resolves to `_MEIPASS`); `app.resource()` uses `Path(__file__).parent/"resources"` (datas match); `open_guide` checks `exe_dir()`, repo root and `_MEIPASS` (README copied to `_internal/`). All consistent on paper — verify once on the first Windows build.
6. **`app/dialogs/settings_dialog.py` Flow tab** — expose `flow.past_date_policy` (combo: "Tự dùng hôm nay" / "Hỏi tôi") next to `pause_qty`; add `SET_PAST_DATE_*` strings in `strings_vi.py`; map in `result_config()` (~6 lines).
7. **`app/dialogs/calibrate_dialog.py:16-17`** — `QUICK_LINKS` labels ("Inbox", "New Shipment", "Drafts") are English; move to `strings_vi.py` (`CALIB_LINK_INBOX = "Hộp thư (Inbox)"`, …). Everything else user-facing is Vietnamese (log-tab messages are intentionally technical English, fine).
8. **`app/main_window.py:494` `write_back` and `:292` `load_grid` run on the GUI thread.** Acceptable for packing lists of this size; if large workbooks appear, move `write_back` to a `QThread`/`concurrent.futures` and show a busy cursor. `browser_install.chromium_available()` (`browser_install.py:21`) does `rglob("*")` over the Playwright cache on the GUI thread at startup when Edge is missing — cap to `glob("chromium*-*/chrome-win/chrome.exe")`-style patterns.
9. **Duplicated logic between WPs (minor):** `tests/app/conftest.py::FakeWorker` mirrors the worker's public API by hand — add a static check (`assert set(dir(FakeWorker)) >= {"submit","respond","request_abort","update_config","set_advisor","start","stop","is_running","is_browser_open"}`) so a renamed worker method fails loudly. `_PREVIEW_FACTORY` placeholder in `main_window.py:42` vs `FactoryAddress` defaults — fine.
10. **`README_VI.md`** — document `flow.past_date_policy` and that "Validate" is never clicked unless `click_validate` is enabled; mention that the inspector must be closed before quitting (P1-2).

## 6. Things checked and found correct (so nobody re-audits them)

- Event/command contracts: every `ev.*` class is in `WorkerBridge._TYPED`; `StepsView`/`LogView`/`PauseDialog` read only fields that exist (`step_id`, `title_vi`, `status`, `percent`, `message_vi`, `options`, `input_fields`, `screenshot_path`, `ai_explanation_vi`); `UserResponse(request_id, action, values)` round-trips through `worker.respond` → per-request `queue.Queue(1)`; unknown ids are ignored and logged.
- Threading: `WorkerBridge` lives in the GUI thread, so cross-thread `emit` is queued (pytest-qt test asserts delivery on the main thread). No Playwright object is referenced from `app/` (grep `.page`, `is_browser_open` → none; `is_running` is a plain bool). The `RunPlan` passed to the worker is a fresh object (`start_run` rebuilds it), so the GUI never reads what the worker mutates until `RunFinished` arrives.
- Shutdown: `worker.stop()` sets abort, queues `Shutdown`, joins 10 s; open `PauseDialog`s are force-closed and answer `abort`.
- Results: `ResultsWriter` rewrites `results.csv` after every state change and `run.json` at the end; history tab reads `run.json`; write-back only when `status != "dry_run"` and an id exists; the original workbook is never modified.
- Mock fidelity for the guarded controls: the mock renders `btnCancel`, `cancelShipment` (with confirm), `validateShipment`, `btnSubmitASN` (→ `asn.do`), exactly like `docs/EDI_REAL_STRUCTURE.md`, so the guard tests exercise the real names.

## 7. Test status after my changes

Command: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

Before review: 132 passed. New/changed tests: +1 integration (`tests/test_integration_app.py`), +3 (`test_ship_date_policy.py`),
+2 (`test_actions_guard.py`), +1 (`test_healing.py`), +1 (`test_calibrate.py`), +1 (`test_e2e_mock.py`); 1 expectation
updated (`test_dates.py::test_compute`, whole-window-past → today).

```
141 passed, 1 warning in 114.38s (0:01:54)
```
(132 → 141: 9 new tests, 0 failures; the single warning is openpyxl's pre-existing "DrawingML support is incomplete" notice raised while copying the sample workbook in `test_data_misc.py::test_writeback`, unrelated to the changes. The new integration test alone runs in ~13 s.)

## 6. Fix pass

P1
1. calibrate expose_binding -> done (WeakSet keyed by page; "already registered" PlaywrightError treated as success; test added).
2. OpenInspector blocking -> done (inspector refused with a warning when `browser.headless`; `stop()` logs a warning if the join times out; README_VI notes closing the inspector before quitting).
3. open_calibrate second SelectorStore -> done (uses `self.worker.selectors`).
4. --mock leaking into config -> done (process-only `set_runtime_mock_url()` in `core/config.py`, consulted by `effective_base_url`; never in AppConfig/config.yaml; the save/restore hack removed; test added).
5. `_pump` re-opening a tab -> done (new non-creating `BrowserSession.current_page`; `_pump` sleeps when there is none).
6. runner login path `attempt += 1` -> done.
7. Hoist `Flag` import in steps.py -> done.

P2
1. build_windows.ps1 `package\lib` assertion -> done (duplicate collect_data_files left as is: harmless).
2. Pre-release version parsing -> done.
3. Inno Setup `#if Ver < EncodeVer(6,3,0)` guard + CloseApplications/RestartApplications -> done (workflow `choco --version` pin skipped: exact available version not verifiable here; the #error guard covers it).
4. paths.py portable read-only fallback -> done (logs a warning, falls back to the roaming dir; test added).
5. Frozen-only assumptions -> skipped (verify-only; needs a Windows build).
6. Settings past_date_policy combo -> done (SET_PAST_DATE* strings; test added).
7. Calibrate QUICK_LINKS Vietnamese -> done (CALIB_LINK_* strings).
8. Threading/GUI note -> partly done: `chromium_available` now uses bounded globs instead of `rglob`; moving `write_back` off the GUI thread skipped (the review says acceptable for current sizes).
9. FakeWorker API check -> done (`tests/app/test_worker_api.py`).
10. README_VI.md -> done (past_date_policy, inspector; the Validate note was already present).

No safety guard was touched.

```
146 passed, 1 warning in 113.98s (0:01:53)
```

## §7 Pace + English UI

**Task 1 - human-pace mode (on by default).**
- `core/config.py`: new `PaceConfig` (`pace.enabled=True`, `action_delay_ms=[400,1200]`, `nav_delay_ms=[1000,2000]`, `type_delay_ms=[30,80]`, `max_shipments_per_hour=0`, `between_shipments_s=[20,60]`); old config files load unchanged (missing keys -> defaults). `core/errors.py`: additive `SiteBlockedError` (`code="site_blocked"`).
- `automation/pace.py` (new): `Pacer` - randomized, sliced (250 ms), abort-interruptible sleeps through `page.wait_for_timeout` (never `time.sleep` while a page exists); `before_shipment()` implements the between-shipments pause and the max-per-hour limit (history lives on the `BrowserSession`, so it spans runs; injectable clock/rng for tests).
- `actions.py`: delay before every click/fill/select/check; text fields are cleared, typed key by key (`press_sequentially`, 8-char chunks with abort checks) and verified, one `fill()` retry, then `PostconditionFailed`; selects are read back after `select_option` (one retry); after every navigation click: wait `load` + short `networkidle`, nav delay, block scan. All guards (click guard, password refusal, asn.do block, dry-run stop, dialog policy) are untouched.
- `session.py`: main-frame 403/429/503 response listener, `check_blocked()` (page title/body markers: Access Denied, Forbidden, Too Many Requests, captcha, unusual traffic, verify you are human), `after_navigation()` also used by `goto()`.
- `runner.py`: `SiteBlockedError` and "bounced to login more than twice per run" stop immediately and raise a `site_blocked` NeedsUser (options continue/abort only; continue = user resolved it, flag/counter reset). `S6` re-dispatches the SCAC `change` once if the carrier stays empty. Pacing is attached per run in `make_context` and detached after the run (manual browser commands are never slowed).
- Mock: `MockOptions.block_after_n_requests` + `block_mode` (`"429"` | `"access_denied"`).
- Settings: new "Pace" tab with a group box (enable, action/nav/typing min-max, max per hour, between-shipments min-max).
- Tests: `tests/automation/test_pace.py` (19 tests: defaults/back-compat, delays in range, abort interruption incl. a real browser, typing verify/fallback/reject, select read-back, fake-clock between-shipments and hourly limit, full flow with pace on, 429 and Access Denied block runs, login-bounce block, marker scan). Existing suite runs with `pace.enabled=False` (`wpb_helpers.make_config`, integration test).

**Task 2 - English UI.**
- `app/strings_en.py` (new, same keys/placeholders/shapes as `strings_vi.py`), `app/strings.py` loader (`S` lazy proxy, `tr(key, **fmt)`, `set_language`, `language()`); all `strings_vi` imports in `app/` now go through it; `main.py` calls `set_language(cfg.ui.language)`. `ui.language: 'en'|'vi'` (default `en`, tooltip says restart required). `test_strings.py` asserts identical key sets and placeholders.
- AI: `prompts.system_explain(lang)/user_explain(lang)` - `vi` returns the original verbatim prompt, `en` an English equivalent; the JSON contract (`explanation_vi`...) is unchanged. Locator/read-fields prompts untouched.
- Automation/data/core user-facing text (NeedsUser messages, step titles, flags, `message_vi` values, picker banner) is now hardcoded English (field names such as `message_vi` kept to stay additive). Consequence: with `ui.language=vi` those worker-originated messages stay English; only the app chrome/notifications/AI follow the language.
- `README.md` (English) added next to `README_VI.md`; guide menu opens the one matching the language. Packaging: spec ships both READMEs and now lists `strings_en`/`strings_vi` as `hiddenimports` (they are loaded via `importlib`, PyInstaller would otherwise miss them); `build_windows.ps1` puts both READMEs in the portable zip; the `.iss` installs both into `{app}` and its custom messages are English.

**Task 3 - app identity.** `main.py`: `set_app_user_model_id()` (win32-guarded, try/except, called before `QApplication`) with `ShyftGlobal.EDIAssistant`, plus `setApplicationDisplayName` / `setOrganizationName("SHYFT GLOBAL")`; `.iss` Start Menu + desktop icons carry `AppUserModelID`; version_info already had FileDescription/ProductName = EDI Assistant; all balloon titles are now "EDI Assistant" (needs-user text moved into the body). README.md section 11 notes macOS dev runs show "Python". Test: `test_aumid_guarded`.

Final test summary: `172 passed, 1 warning in 145.29s (0:02:25)`

**Rename (EDIAssistant -> "EDI Assistant").** Exe `EDI Assistant.exe`, dist dir `dist\EDI Assistant\`, zip `EDI-Assistant-portable-<ver>.zip`, installer `EDI-Assistant-Setup-<ver>.exe`, install dir/Start Menu/data dirs `EDI Assistant`. Kept: package `edi_assistant`, AUMID `ShyftGlobal.EDIAssistant`, Inno `AppId`, `APP_NAME`, single-instance key and HKCU Run value name `EDIAssistant`. Run command was already quoted; build script now uses `-LiteralPath`.


## §9 PO-tracker P2

Package P2 of SPEC.md section 10 (UI, skill, docs).

- **App.** `strings_en.py`/`strings_vi.py` (+ profile, plan status, tracker settings, 7 new `FIELD_LABELS`, `PLAN_COLUMNS` now 15 entries, `PAUSE_TITLE["shipment_failed"]`, `NOTIFY_SHIPMENT_DONE`; key parity test green). `PlanTable`: checkbox column, master-PO-wide toggling via `selection_changed(master_po, checked)`, greyed unselected / has-ASN rows, alternating background per shipment, `has_errors()` counts selected rows only, `set_plan(plan, all_lines)`. `MappingDialog`: profile combo (refills via `suggest_mapping(det, profile)`, required-first ordering, optional, rest greyed, `result()` mapping carries `profile`). `MainWindow`: selection state kept in `rx.lines[*].selected`, `build_plan` on the full list (empty selection shows the table and keeps Start disabled), forced per-master grouping for the tracker, factory-per-run hint, `save_config` at Start (`last_factory_id`, `last_profile`), `ERR_NO_SELECTION`, `PlanOptions(profile, tracker_weight_mode)`, incremental write-back on `ShipmentCreated` and final one on `RunFinished` into the fixed `writeback_path_for(plan)` copy (never on dry runs). `SettingsDialog`: tracker weight mode + review-between-shipments.
- **Tests.** `tests/app/test_po_tracker_ui.py` (8 tests; real tracker file via the `tracker_xlsx` fixture).
- **Skill.** `parse_packing_list.py` has a `po_tracker` profile (auto-detect, merged A-D inheritance, stop at first blank row / auto-filter end, skip rows with ASN, `--include-with-asn`, `--profile`); `plan_shipment.py` (Excel dates win, per-master default, `--ordered` A/B rule with `qpc x cps == Qty Ordered`); new `write_asn.py` (timestamped copy, never the original, never the Submit column); SKILL.md, `procedure.md`, `excel_mapping.md` updated; 10 new skill tests. Skill repackaged to `skills/burlington-asn.skill`.
- **Observation.** SPEC 10.1 says 7 master POs / "7 shipments"; the sample has 6 distinct master POs (5820678/80/82/77/79/84), so the default run is 6 shipments / 8 lines (the skill and app tests assert 6).


## §8 PO-tracker P1

Package P1 of SPEC.md section 10 (data, flow, mock, tests).

- **Contracts (committed first).** `core/models.py`: new `FIELD_KEYS`, `PROFILES`, `REQUIRED_BY_PROFILE`, `OPTIONAL_BY_PROFILE`, additive `POLine` fields + `window`, `ShipmentPlan`/`RunPlan`/`CartonPlan` fields. `core/config.py`: `FlowConfig.tracker_weight_mode`, `review_between_shipments`, `UiConfig.last_profile`. `core/quantities.py`: `decide_carton`, `carton_matches_web`, weight mode `per_carton_as_is`. `data`: `profiles.py`, `PlanOptions(profile, tracker_weight_mode, today)`, `plan_summary_rows(plan, all_lines)`, `write_back(plan, det, mapping, *, ids, dst)` + `writeback_path_for`, `MockOptions.seed_tracker`.
- **Data.** Synonyms with negative tokens and the stricter substring rule; profile-aware `ColumnMapping`/`suggest_mapping`/templates (`profile` key); `SheetGrid` merged parents / auto-filter / `is_blank`; `parse_date_cell`, `parse_text_or_blank`; `tracker_rows.extract_tracker_rows` (dispatched from `extract_rows`); planner (selection filter, forced per-master grouping, Excel windows, `planned_ship_date`, label with container); results.csv gets 4 trailing columns; write-back writes the `ASN #` column of a timestamped copy and never a `Submit` column.
- **Flow.** S3 Excel-date cross-check (`dates_mismatch_web`, never blocks), S8 via `decide_carton` (qty_mismatch ask now carries two input fields; Model # cross-check), per-shipment failure isolation in the runner (`shipment_failed` ask continue/abort; abort, forbidden-action and site-block still stop the run), `context.vars` + `model_no`/`container`, `po_dates.read_pdf_window`. Mock: `seed_tracker`, `ordered_in_packs`, `--seed-tracker`.
- **Binding user decision.** `review_between_shipments` defaults to **False**: no pause between shipments; for runs of 2+ shipments (non dry-run) the runner asks ONE final `finished_review` listing each master PO with Web Shipment ID, status and warning codes. `True` restores the per-shipment pause (and no final summary). Single-shipment runs are unchanged (no pause).
- **Deviations.** (1) SPEC says 7 master POs / 7 shipments; the sample has 6 distinct masters, so tests assert 6 shipments / 8 lines (pacing test expects >= 5000 ms for 5 pauses). (2) `tests/data/test_templates.py` exact-key assertion gained `"profile"` (the spec adds that JSON key). (3) Write-back stores an int only for the po_tracker profile; the packing-list copy keeps the string value (existing `test_writeback` expects `"9001"`). (4) The extractor derives the line from `parse_po_cell` when no Line # column is mapped (spec edge case), although `line` stays required for the UI mapping. (5) S8 does not add an extra pre-Save invariant check beyond the existing qty_mismatch pause.
- **Tests.** New: tests/data (tracker sample, edge cases, synonyms, profiles, quantities, template roundtrip, write-back), tests/automation (e2e tracker incl. variants, runner isolation, mock seed), `test_gui_to_mock_tracker_run`. All write-back files go to tmp_path copies.


## §11 Locked-down portable

Goal: the portable build must work on company PCs that block installers, Edge automation or downloads.

- **Two zips from one PyInstaller build.** `EDI-Assistant-portable-<ver>.zip` (lite, Edge) and `EDI-Assistant-portable-full-<ver>.zip` (adds Playwright Chromium in `EDI Assistant\browsers\`). `build_windows.ps1` installs chromium into `dist\browsers_stage` (`PLAYWRIGHT_BROWSERS_PATH` set), copies it into the full zip only; `-SkipFull` skips it. `dist\SHA256SUMS.txt` lists SHA256 of both zips, the installer and the exe; the workflow uploads zips, exe, SHA256SUMS.txt (artifact and release).
- **Startup.** `paths.use_bundled_browsers()` points `PLAYWRIGHT_BROWSERS_PATH` at `<exe dir>\browsers` when it exists (before playwright import); otherwise the old per-user `ms-playwright` default.
- **Channel resolution.** New `core/browser_detect.py` (Qt-free; detection moved from `browser_install`, which re-exports): `launch_plan(channel, bundled, chromium)`. `browser.channel` default is now `auto` (was `msedge`): bundled Chromium, else Edge, then downloaded Chromium if present. `msedge`/`chrome` -> that channel then Chromium if present; `chromium` -> Chromium only. `automation/session.py` `open()` only changed to loop over that plan; if Edge failed with a policy/not-found style error and nothing else worked, `BrowserLaunchError` carries `LOCKED_DOWN_MESSAGE` (RemoteDebuggingAllowed, suggest full zip). No auto-download anywhere; the existing menu/prompt flow is still the only download path. Settings has an "Auto" entry.
- **System check.** `app/system_check.py` (probes injectable, any probe exception becomes FAIL) + `dialogs/system_check_dialog.py` (QThread, Copy report). Help > System check; offered once on first run (`ui.system_check_done`). Probes: data dir writable, bundled/downloaded Chromium, Edge, headless and headed launch via the real launch plan (temp profile, closed immediately), portal HEAD/GET with `httpx trust_env=True` timeout 8 s, HKCU Run writable (Windows), tray notifications.
- **Autostart.** `autostart.apply()` never raises; `MainWindow._apply_autostart` warns, unticks and saves on failure; `autostart.refresh` swallows all errors.
- **Docs/strings.** README.md and README_VI.md "Company (locked-down) PCs"; `strings_en/vi` parity kept.
- **Tests.** `tests/app/test_locked_down.py` (13): plan variants, mocked launch failures (auto/fallback/message), bundled env, runner with mock probes, portal failure, dialog thread, autostart failure. `test_paths_config` now expects default channel `auto`.
- **Not verified here (Windows only):** actual build of both zips, Chromium staging size, unblock/MOTW flow, Edge launch under RemoteDebuggingAllowed=disabled and the exact Playwright error wording (hint lists are heuristic), headed launch from the zip, HKCU Run denial, corporate proxy behaviour of the portal probe.

## §10 Perf

**Symptom.** Tracker e2e against the mock took ~42 s (`test_tracker_full_run`, `test_gui_to_mock_tracker_run`); `test_pacing_between_shipments` took ~106-130 s.

**Profiling** (temporary monkeypatch plugins + cProfile, not committed). The suspected causes were not the culprits: no PDF ladder or navigation timeouts were hit (0 `expect_navigation` timeouts in 136 navigations). Time went to:
1. Negative/optional existence probes (`exists`/`try_resolve` with `NEG`=250 ms or 300 ms budgets: `pos.search_po_input`, `ship.error_text`, `carton.*_row`, `*.page_marker`, `weight.form`, ...). ~100 misses per run, each burning its whole budget through the 150 ms sweep sleeps: ~24 s.
2. `click_locator` called `scroll_into_view_if_needed()` on every click (~25 ms x 136 = 3.4 s), redundant with Playwright's own auto-scroll in `click()`.
3. Pacing test only: `after_navigation` waits for `networkidle` (>=500 ms quiet window) on ~136 loads (~70 s).

**Fix.**
- `automation/selectors.py`: new `PROBE_MS = 300`; `resolve()` with `timeout_ms <= PROBE_MS` does a single candidate sweep and returns/raises immediately (no sleep loop). Required elements use budgets of 1.5-8 s and keep full polling behaviour; every probe-then-wait pattern (`exists(..., NEG)` then `exists(..., 8000)`) still falls through to its long budget.
- `automation/actions.py`: explicit `scroll_into_view_if_needed()` only when human pace is enabled; `click()` still auto-scrolls and checks actionability. Safety guards (`_guard_click`, password-field check) untouched.
- `tests/automation/test_e2e_tracker.py`: pacing test monkeypatches `session.IDLE_CAP_MS` to 1 ms (networkidle settle is real-site behaviour, not needed for the mock); it still asserts `slept_ms >= 5000` for 5 inter-shipment pauses.

**Before / after (single test, this machine).**
| test | before | after |
|---|---|---|
| test_tracker_full_run | 41.8 s | 13.1 s |
| test_gui_to_mock_tracker_run | ~42 s | 13.0 s |
| other tracker e2e variants | ~42 s | 12.6-13.1 s |
| test_pacing_between_shipments | 106-130 s | 33 s |

Full suite: 251 passed in 235 s.

## §12 Final review

Scope: §7-§11 as integrated on 2026-10-18 (pace + English UI + AUMID, rename, PO-tracker P1/P2, §10 perf fix, §11 locked-down
portable) against the binding user rules. Method: full read of `selectors.py`, `actions.py`, `session.py`, `flow/steps.py`,
`flow/runner.py`, `worker.py`, `system_check*.py`, `browser_detect.py`, `paths.py`, `main.py`, `tracker_rows.py`, `planner.py`,
`quantities.py`, `excel_writeback.py`, the write-back wiring in `main_window.py`, `build_windows.ps1` + spec + hook + workflow,
both READMEs, the skill (SKILL.md, procedure.md, excel_mapping.md, `plan_shipment.py`, `write_asn.py`) and the mock's save
handlers; plus new tests for every fix.

### 12.1 Verdict

**Ready for a supervised first real run (dry run first).** The §10 perf fix did not open a false-success path *by itself*
(every post-Save error probe runs after `expect_navigation(domcontentloaded)`, so a server-rendered error is in the DOM when the
single sweep runs), but the audit found that the post-Save checks were fragile in ways the perf fix made marginally worse, and one
Save had no error check at all:

1. A probe sweep that hit a `PlaywrightError` (page still navigating) was indistinguishable from a clean miss and returned
   "absent" at once (§10 reduced two sweeps to one).
2. After a Save that does **not** reload the page (slow server > 6 s, client-side validation) S8 and S9 verified success by reading
   back the inputs - which still hold the values just typed. The mock (and a Struts form bean on the real site) re-render the typed
   values on a **rejected** Save too, so the error-text probe was the only thing standing between a rejected carton Save and
   `carton_done`.
3. `_visible_text` looked at the `.first` match only: an empty/hidden first `.error` container would mask the real message.
4. S9 (weights) had no error-text check after Save.

All four are closed below (small, additive, tested). No safety guard was touched. Tracker business logic, the dry-run hard stop in
multi-shipment runs, write-back isolation, the System check and the locked-down launch plan all check out; the remaining items are
real-site verification work and robustness nits (P1/P2 list).

### 12.2 Fixes made

| # | File(s) | Change | Tests |
|---|---|---|---|
| 1 | `automation/selectors.py` `resolve()` | A probe (`timeout_ms <= PROBE_MS`) concludes "absent" only from a **clean** sweep; a sweep disturbed by a `PlaywrightError` keeps polling until its (short) deadline. Clean misses still cost exactly one sweep and no sleep (perf of §10 preserved). | `test_selectors.py::test_probe_keeps_polling_while_page_unstable` |
| 2 | `automation/actions.py` | `click()` / `click_locator()` return `bool` = "a navigation was observed" and accept `nav_timeout_ms`; new `SAVE_NAV_TIMEOUT_MS = 20000` for Save clicks (a rejected/slow Save must be *seen*, not timed out after 6 s). Guards untouched. | `test_actions_guard.py::test_click_reports_navigation` |
| 3 | `automation/flow/steps.py` | `_visible_text` scans **all** candidates and up to 20 matches each, visible only, and requires words (`[A-Za-z]{3,}`, so a red `*` is not an error). New `_settle(ctx)` (domcontentloaded/load with caps, instant when loaded) and `_after_save(ctx, navigated, what, step_id)`: settle -> error text -> "page did not reload after Save" = `PostconditionFailed`. Applied after the header Save (S6, plus `_settle` at the start of `S6.check`), the carton Save (S8, replaces the old inline check) and the weights Save (S9, previously unchecked). | `test_post_save_gate.py` (3), `test_e2e_tracker.py::test_rejected_carton_save_is_never_success` |
| 4 | `tests/automation/test_e2e_tracker.py` | New `test_multi_shipment_dry_run_hard_stop`: 6-shipment tracker dry run -> 6 x `dry_run_stop`, no final review, mock has **no** shipment, no `save_header`/carton/weight/SUBMIT log entry, no `ShipmentCreated`. (No code change needed: `runner._run_shipment` returns after S6 for every shipment and `_final_review` skips dry runs.) | itself |
| 5 | `skills/burlington-asn/scripts/plan_shipment.py`, `SKILL.md`, `references/procedure.md`, `skills/burlington-asn.skill` (repackaged) | Binding rule "past ship date -> today" was missing from the skill: `plan(..., today=None)` + `--today YYYY-MM-DD` clamp a past midpoint to today, keep the original in `ship_date_original` and report `SHIP_DATE_IN_PAST` in `issues` (never silently, never blocking). Stale docstring for `--ordered` ("used only to warn") corrected (tracker: A/B rule, blocks on mismatch). SKILL.md step 3 and procedure.md step 2.5 state the rule. | skill tests pinned to a fixed `today` + new clamp assertions (`test_plan_sample_and_no_intersection`) |

### 12.3 Task 1 - short-budget callers audited (PROBE_MS / NEG)

| Caller | Kind | Miss means | Verdict |
|---|---|---|---|
| `S6.check` `ship.error_text` | post-Save CHECK | would have continued to id capture | **fixed** (settle + full scan; S6.act also gates on reload) |
| `S8.act` `ship.error_text` after carton Save | post-Save CHECK | read-back of typed values -> false `carton_done` | **fixed** (`_after_save`) |
| `S9.act` weights Save | post-Save CHECK (absent) | read-back echo -> false `weight_done` | **fixed** (`_after_save`) |
| `S6.act` `ship.submit_asn_button` NEG ("already saved") | pre-action probe | re-fill + Save on an already saved header (update, not duplicate) | acceptable, see P1-2 |
| `S7` `pos.selected_row` NEG ("already added") | pre-action probe | re-search + re-add the PO; followed by 6 s positive wait | acceptable, see P2-2 |
| `S7`/`S8` `pos.page_marker`, `carton.page_marker` NEG | pre-action probe | an extra click that then fails loudly (ElementNotFound -> pause) | fail-safe |
| `S0` `login.password_input` NEG, `S0.check` `inbox.document_id_input` NEG | login detection | title check comes first; a miss -> another goto / retry | fail-safe (false negative only) |
| `_capture_ids` `ship.web_shipment_id` etc. NEG | reads | falls back to body regex / URL; `check()` requires a 3+ digit id **and** the Submit button (1.5 s) | fail-safe |
| `S8` `carton.item_prepack_row` 300 ms | read | prepack None -> `web_rule` unknown/mismatch -> `qty_mismatch` pause (qty_strict for tracker) | fail-safe; page already settled by the preceding 8 s waits |
| `S9._ensure_all` `weight.orderperpage_select` NEG | pre-action | rows beyond 10 not found -> step pause | fail-safe |
| `S10` `weight.form` NEG | pre-action | skip "Back"; no write | harmless |
| block detection (`check_blocked`) | - | not resolver-based; body text read with 2 s timeout | unaffected |

Why the gates are enough: `expect_navigation(domcontentloaded)` already guarantees the response document is parsed before any
check; `_settle` covers a second (JS/meta) navigation; the "navigated" flag covers the no-reload case; fix 1 covers a sweep caught
in flux. Cost: zero on the happy path (settle returns immediately, `_visible_text` is one pass over a handful of candidates);
tracker e2e still ~13 s.

### 12.4 Task 2 - safety regression check

- Guards intact: `forbidden_reason_from_attrs` (Submit/Cancel/Clear/Remove/Validate/asn.do), password-field refusal, `asn.do`
  route block + `goto` refusal, dialog policy. `click_locator` still guards *before* any scroll/pace/click.
- Dry run: `S6` raises `StepSkipped` before Save; `runner._run_shipment` returns right after S6 for **every** shipment when
  `plan.dry_run` (also when S6 failed/was skipped); `_final_review` skips dry runs; GUI `_write_back_now` refuses `plan.dry_run`.
  New multi-shipment test proves no shipment reaches the mock.
- Multi-shipment isolation: `UserAbortError`, `ForbiddenActionError`, `SiteBlockedError` re-raised; everything else marks the
  shipment failed, writes results, asks `shipment_failed` (continue/abort) except after the last shipment (listed as `[failed]` in
  the single final summary).
- System check: `probe_browser_launch` launches the real launch plan with a **temporary profile**, never navigates, closes at once;
  `probe_portal` is a plain `httpx` HEAD/GET of `login.do` (system proxy), no cookies, no automation. First-run offer only asks.
- Browser fallback (`session.open`): tries the plan in order, never downloads; `LOCKED_DOWN_MESSAGE` only when Edge failed for a
  policy/missing reason. Install remains user-initiated (menu or the first-run question).
- Write-back: `shutil.copyfile(src, dst)` reads the original only; target column = mapped `asn` (F) or exact header `asn`, never a
  header containing "submit" (AB protected); only line rows with status not in skipped/failed; dry run never writes.
- Worker: `_run_plan` clears abort, detaches the pacer after the run; manual commands never paced; `TestKey` only resolves.

### 12.5 Task 3 - tracker business logic vs the binding rules

| Rule | Where | Status |
|---|---|---|
| D+E -> 9-digit id | `tracker_rows.py` (`parse_po_cell` + `parse_line_cell`, `POLine.po_line_id`) | OK; 9-digit PO without Line column also handled |
| Dates M/N authoritative; web only cross-checked | planner `dates_source="excel"`, `S3._cross_check` (flag `dates_mismatch_web`, never blocks) | OK |
| qpc = Q, cps = J/Q integer | `packages = J/Q` (error flag when non-integer -> red row, Start blocked) | OK |
| qpc x cps == web Qty Ordered; prepack -> qpc 1 | `decide_carton` rules units/packs/mismatch; `qty_strict` for tracker -> pause on any mismatch/unknown | OK |
| weight = T as-is, 2 dp, KG | `per_carton_as_is` + `format_weight`; `weight_um` KG | OK |
| one shipment per master PO | `forced_grouping` | OK |
| skip rows with ASN in F | `selected = (asn == "")`, whitespace = empty | OK |
| ASN into F of a COPY, original untouched, AB never written | `write_back` (see 12.4) | OK |
| factory per run | combo pre-selected from `last_factory_id`, hint shown, Start refuses without one | OK (pre-selection is a convenience; the user confirms by Start) |
| no pause between shipments, one final summary | `review_between_shipments=False`, S10 logs, `_final_review` once (>= 2 shipments, not dry run) | OK |
| failures pause continue/abort | runner per-shipment `shipment_failed` | OK |
| past ship date -> today | `past_date_policy = clamp_today` in `compute_shipping_date`/S4 | OK (skill fixed in 12.2 #5) |
| merged-cell inheritance only for identity columns | `get_merged` only for `po`/`container`; other fields raw `cell()`; forward-fill of a blank master flagged `master_po_inherited` | OK |
| secondary table excluded | stop at first blank key row, auto-filter end, header-text row | OK |

### 12.6 Task 4 - locked-down portable

- `launch_plan`: auto+bundled `[None, "msedge"]`; auto `["msedge"(, None)]`; `chromium` `[None]`; explicit channel then Chromium.
  Matches README. `channel=None` with `PLAYWRIGHT_BROWSERS_PATH` = bundled dir resolves to `chromium-<rev>` (headed) /
  `chromium_headless_shell-<rev>` (headless); both are installed by `playwright install chromium` (verified locally with 1.64:
  `chromium-1248`, `chromium_headless_shell-1248`, `ffmpeg-1013`). `_EXE_GLOBS` covers `chrome-win` and `chrome-win64`.
- Env ordering: `main()` calls `paths.use_bundled_browsers()` before PySide/Playwright are imported (`edi_assistant/__init__`,
  `app/__init__`, `core/__init__` import nothing heavy); strictly only the driver spawn needs it, so this is safe either way.
- Build: one PyInstaller build -> lite zip; `playwright install chromium` into `dist\browsers_stage` with
  `PLAYWRIGHT_BROWSERS_PATH` -> copied to `EDI Assistant\browsers` in the full zip only; `SHA256SUMS.txt` with both zips, installer
  and the exe; workflow uploads all. Driver revision = the venv's, so the bundled browser matches `browsers.json`.
- README/README_VI: steps, table, "Auto" semantics, System check, AppLocker info accurate (one wording nit, P2-3).

### 12.7 Task 5 - skill consistency

Consistent with the tool: weight = T as-is (tracker) vs total G.W. (packing list), qpc x cps == Qty Ordered invariant before Save
(`_tracker_item`), never Submit/Validate/Remove/Cancel, never type the password, one shipment per master, ASN skip, copy-only
write-back (`write_asn.py` refuses the original and the Submit column), factory asked every run. Gap fixed: past date -> today
(12.2 #5). `edi_dom.md` unchanged and still marks the three unverified pages.

### 12.8 Remaining issues (prioritized)

**P0** - none.

**P1**
1. `edi_assistant/automation/selectors.yaml:91-92` - `ship.error_text` is *unverified* and broad (`font[color='red']`,
   `span[style*='red']`, `.error`). On the real site any benign red sentence (e.g. "Fields marked * are required") would make every
   Save look rejected. Fail-safe (it pauses), but S6 would then loop: `act()` returns early ("already saved"), `check()` raises
   again -> "Too many attempts" -> shipment failed; and a *learned* candidate cannot remove a bundled one. Instruction: on the first
   real header Save, if the pause says "The site reported an error: <benign text>", take the DOM dump from `runs\<id>\` and narrow
   the bundled candidates to the real error container; also consider, in `S6.check` (`steps.py:376-380`), tolerating error text
   when the Web Shipment ID and the Submit button are both present (log a warning instead of raising).
2. `edi_assistant/automation/flow/steps.py:336` - the S6 "already saved" probe (`ship.submit_asn_button`, NEG) runs before any
   settle; a miss re-fills and re-saves the header. The real form carries `shipment_id`, so this is an update, not a duplicate, but
   add `_settle(ctx)` before the probe and use a 1500 ms budget when `"shipment_id=" in ctx.session.url()`.
3. `edi_assistant/app/dialogs/system_check_dialog.py:78-82` + `edi_assistant/app/main_window.py:640` - `done()` blocks the GUI
   thread up to 30 s if the user closes the dialog during the headed-launch probe (20 s timeout) or the portal probe (8 s), and a
   still-running `QThread` child destroyed with the MainWindow at exit makes Qt abort ("QThread: Destroyed while thread is still
   running"). Instruction: do not wait in `done()`; keep the dialog (or just the thread) owned by MainWindow and wait for it in
   `MainWindow.closeEvent`, or run the probes via `QThreadPool` with a cancellable runnable. Also `edi_assistant/app/system_check.py:124`
   calls `QSystemTrayIcon` statics off the GUI thread - evaluate `probe_notifications` on the GUI thread before starting the worker
   and pass the result in.

**P2**
1. `edi_assistant/automation/actions.py:130` - `page.expect_navigation` is deprecated upstream (works in 1.64). Plan a migration to
   `page.expect_response`/`wait_for_url` per Save (the `navigated` flag API stays).
2. `edi_assistant/automation/flow/steps.py` S7 (`pos.selected_row` NEG, line 409) - a transient miss re-adds an already added PO;
   verify on the real site that re-adding is rejected/deduplicated; otherwise call `_settle(ctx)` before the per-line loop and use
   1000 ms.
3. `README.md:44` / `README_VI.md` - "never downloads a browser by itself; only Tools > Install Chromium does": the first-run
   question (`main_window.py:666-669`) can also start the download after a Yes. Reword to "only after you confirm".
4. `edi_assistant/automation/flow/steps.py` `_HAS_WORD` is Latin-only; the portal is English, but if an error ever appears in
   another script it would be ignored - extend to `\w{3,}` with `re.UNICODE` if that happens.
5. `edi_assistant/app/main_window.py:552-559` - the incremental copy written on `ShipmentCreated` keeps an ASN for a shipment
   that later fails (its lines become `failed` and are dropped by the final rewrite on `RunFinished`); after a GUI crash the
   incremental copy stays. Acceptable (the shipment does exist on the web); document in README 4a.
6. `packaging/build_windows.ps1:91-94` - the full zip also carries `ffmpeg-*` (a few MB) and `.links`; harmless, could be pruned.
7. `skills/burlington-asn/scripts/plan_shipment.py` - `SHIP_DATE_IN_PAST` is reported per group; the table output prints it under
   ISSUES (fine), JSON consumers should read `ship_date_original`.

### 12.9 Must be verified on Windows / on the real site (first-real-run checklist for the user)

1. **Build & install (Windows only).** Build both zips + `SHA256SUMS.txt`; unblock the zip; extract to Documents; run
   `EDI Assistant.exe`; accept the first-run **System check**: expect PASS for data dir, headless *and* headed launch (a browser window
   opens and closes), bundled Chromium (full zip) or Edge (lite), portal HTTP 200/302; WARN on autostart is fine. Copy the report.
2. **Login once** via *Open browser*; log in yourself; the tool never types the password.
3. **Dry run on ONE master PO.** Load the tracker, confirm *File format: PO tracker*, tick **one** master PO only, tick **Dry run**,
   choose the factory, Start. Expect: inbox search -> PO page -> header form filled -> pause "Dry run: the form is filled but NOT
   saved". Compare every header field with the plan (Ship date = window midpoint or today; SCAC/carrier; From address), then
   Continue. Confirm `drafts.do` shows **no** new shipment and no `_ASN_` copy was written.
4. **The 3 unverified pages** (`verified: false` in `selectors.yaml`): PO detail (`po.create_new_shipment_link`, `po.page_marker`),
   Search Purchase Orders tab (`pos.tab_search`, `pos.search_po_input`, `pos.search_button`, `pos.search_row`,
   `pos.add_selected_button`) and the whole Carton page (`carton.*`). Expect pauses there on the first real run.
5. **Learn mode when a step pauses with "element not found":** Tools > Calibrate -> select the key -> *Pick* -> click the element in
   the browser (guarded: Submit/Cancel/Remove/Validate cannot be learned) -> *Test key* -> *Mark verified*; press Continue in the
   pause dialog. Learned candidates are tried first and survive updates (`data\selectors.learned.yaml`).
6. **First real header Save (one master PO, Dry run off).** Expect the Web Shipment ID to appear and no "The site reported an
   error" pause. If such a pause shows *benign* text, stop and report it (P1-1). Check the incremental `_ASN_<ts>.xlsx` copy: ASN in
   column F of that PO's rows only; column AB untouched; original file unchanged.
7. **First carton page.** Confirm the item/site rows, that Qty Ordered is read, the prepack sub-row on an AS item, and that
   Qty Per Carton x Cartons Per Site equals Qty Ordered on the page before Save; after Save no error text, values persisted,
   Complete/Partial = Partial.
8. **Weights.** 2-dp value and KG persisted after Save; with > 10 lines the page size switches to All.
9. **Two masters in one run.** No pause between shipments, one final summary listing both Web Shipment IDs; `results.csv` and the
   copy hold both ASNs. Then review in Drafts and click **Validate / Submit ASN yourself**.
10. Keep **human pace on** (default) for real runs; watch the log for "BLOCKED request" (should never appear) and for "SITE BLOCKED".

### 12.10 Test status after §12

Command: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

```
258 passed, 1 warning in 251.91s (0:04:11)
```
(251 -> 258: +1 `test_selectors`, +1 `test_actions_guard`, +3 `test_post_save_gate.py`, +2 `test_e2e_tracker`; 0 failures; the
warning is openpyxl's pre-existing DrawingML notice.)

Skill tests: `.venv/bin/python -m pytest -q skills/burlington-asn-workspace/tests`

```
19 passed, 3 warnings in 0.58s
```
`skills/burlington-asn.skill` repackaged (same 8 files).

## §13 Final fix pass

Implements the §12.8 list (P1-1 selectors deliberately untouched). No safety guard changed; nothing new clicks anything.

| Item | Change | Test |
|---|---|---|
| P1-2 | `S6.act`: `_settle(ctx)` before the "already saved" probe; the probe budget is 1500 ms when `ctx.session.url()` contains `shipment_id=` (else NEG as before). | covered by e2e (`test_e2e_mock`, `test_e2e_tracker`) |
| P1-1 tolerance | `S6.check`: residual `ship.error_text` is only a WARNING (`ctx.warn`, nothing clicked) when `_capture_ids` finds a Web Shipment ID **and** `ship.submit_asn_button` is present (enabled or not); otherwise it still raises. The selectors themselves are unchanged. Note: `_after_save` right after a real Save is unchanged and still fails on error text. | `test_s6_check_tolerates_red_text_on_saved_shipment_page`, `test_s6_check_still_fails_without_saved_state` |
| P1-3 | `SystemCheckDialog.done()` no longer waits: it only disconnects its slots. The `QThread`/runner are parentless and owned by a module registry (`_LIVE`, removed on `finished`), so closing the dialog can neither block the GUI nor destroy a running thread. `MainWindow.closeEvent` (real exit only, not hide-to-tray) calls `wait_for_background()` so the process never exits with a running QThread. `probe_notifications` (QSystemTrayIcon statics) is now evaluated in the dialog constructor on the GUI thread and passed to `default_probes(notify=...)`. | `test_closing_dialog_midrun_does_not_block_or_destroy_thread`, `test_default_probes_use_precomputed_notify_result` |
| P2-2 | S7: `_settle(ctx)` before the per-line loop; first `pos.selected_row` negative probe uses 1000 ms. | e2e |
| P2-3 | README.md / README_VI.md step 4: downloads happen only after you confirm (menu item or Yes to the first-run question). | - |
| P2-4 | `_HAS_WORD` = `[^\W\d_]{3,}` (Unicode letters). A lone `*`, digits or punctuation still do not count. | `test_unicode_error_text_counts_as_words` |
| P2-5 | `write_back(..., written=)` remembers the Excel rows already given an ASN; the final rewrite re-applies them, so an ASN written incrementally for a shipment that exists on the web is **never dropped** by a later line failure (failed lines of a not-yet-created shipment are still never written). The copy is saved to `<name>.tmp` then `os.replace`d, so it is always a valid workbook even if the process dies mid-save. `MainWindow` keeps `_writeback_rows` per run. Default (no `written`) behaviour is unchanged. | `test_already_written_asn_persists_after_later_failure` |
| P2-6 | `build_windows.ps1`: `ffmpeg*` removed from the browsers staging dir (video recording only; the app never records). `.links` left alone. | - |
| Skipped | P2-1 (`expect_navigation` deprecated: left as instructed); P2-7 (JSON consumers, informational). P1-1 selector narrowing needs the real-site DOM. | - |

Test status after §13: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` -> 264 passed, 1 warning (258 + 6 new; 0 failures).
