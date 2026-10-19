# EDI Assistant — Implementation Specification

Version 1.0 — 2026-10-18 — lead architect spec. Implementers: three parallel work packages (WP-A data, WP-B automation, WP-C app). Read §0–§2 fully before starting your own section; §2 contains the shared contracts that every WP codes against. Do not modify a file owned by another WP. If this spec is ambiguous, choose the simplest interpretation that keeps the stated interfaces unchanged and leave a `# SPEC-NOTE:` comment at the site.

**Contents**: §0 Overview, non-goals, safety guards, key decisions · §1 Layout & work packages · §2 Shared contracts (paths, config, models, events, errors, AI interface, flag codes) · §3 WP-A data layer (Excel, header detection, synonyms, mapping, templates, values, factories, dates, quantities, planner, results) · §4 WP-B automation (threading, session, selectors.yaml, resolver, row keys, actions/guards, dialogs, snapshots, healing, date ladder, flow state machine, worker/commands, calibrate) · §5 WP-B mock EDI Gateway · §6 WP-C app, AI clients, prompts, cost control, README · §7 Packaging (portable zip, installer, CI) · §8 Testing, acceptance, integration order · §9 Risks & mitigations.


Language: code, identifiers, comments, logs and this spec are English. Every string shown to the end user (GUI labels, dialog text, notifications, README_VI.md, AI "explain error" output) is Vietnamese.

---

## 0. Overview

### 0.1 What the tool does

Ops staff at SHYFT GLOBAL LLC receive packing-list Excel files from factories and must create ASN shipments on Burlington's "EDI Gateway" vendor portal (classic server-rendered HTML forms; `edi.coat.com`). EDI Assistant:

1. Reads a packing-list Excel file (structure varies per factory), detects the header row, lets the user map columns to the required fields once, fingerprints the layout and re-applies the saved mapping automatically next time. Each data row is one PO line.
2. Plans shipments (grouping, carton math, weights, ship-date rule) and shows a review table.
3. Drives a built-in, visible Playwright browser (Edge channel, persistent profile — the user logs into the portal manually once) through the documented entry procedure in a background thread while the GUI stays responsive and lives in the system tray.
4. **Never submits.** It stops at the "review" point, notifies the user (tray balloon + sound), and leaves the browser on the shipment page for manual review and manual click of "Submit ASN".
5. Is robust to the unknown real DOM: locators are data (YAML) with multiple candidates, learned overrides, a calibration/picker mode, and an optional AI vision "healer" that proposes new locators or explains failures in Vietnamese. The tool is fully functional with AI disabled.
6. Ships with a local mock of the EDI Gateway so the whole flow is testable end-to-end offline.

### 0.2 Non-goals

- No submission of ASNs, no "Validate Shipment" by default (configurable, off), no label generation, no PRO number handling.
- No handling of the "PO replaced" procedure (screens 19–22). The tool only *detects* a `Replaced` status in the Selected Purchase Orders table and pauses with a Vietnamese message telling the user to perform the replace procedure manually, then Continue.
- No automatic login, no credential storage for the portal. The persistent browser profile keeps the session cookie.
- No Odoo integration (the docx says "look up the From address in Odoo"; we use the local factory list).
- No multi-user/shared storage. All state is per Windows user (or portable folder).
- No OCR library, no PIL. PDF text extraction uses `pypdf` (pure Python, added to the fixed stack as the only extra dependency).

### 0.3 Safety guards (binding)

| Guard | Where | Behaviour |
|---|---|---|
| G1 Submit guard | `automation/actions.py::SafeActions.click` | Before any click, the accessible name / `value` / `textContent` of the target is read; if it matches `re.compile(r"submit", re.I)` the click raises `ForbiddenActionError` and is never performed. The selectors file contains key `ship.submit_asn_button` only so it can be checked for *existence* (postcondition "we are on a shipment page") — it is never clicked. |
| G2 Dialog guard | `automation/dialogs.py` | Native `confirm()` dialogs are **dismissed by default**. They are accepted only when the flow has explicitly armed an expectation (`DialogPolicy.expect_accept(pattern)`) and the message matches that pattern (e.g. `(?i)do you want to add the selected`). A dialog whose message matches `(?i)submit|transmit|cancel .*shipment|delete|remove` is always dismissed and logged. `alert()` dialogs are accepted (they have no cancel) and their text is logged. |
| G7 Route block | `automation/session.py` | `context.route("**/asn.do*", lambda r: r.abort())` is installed on every context (real and mock). `asn.do` is the Submit ASN endpoint on the real site. Also never navigated to by `goto`. |
| G8 Forbidden elements | `actions.py` | Clicks on elements whose `name`/`id` is one of `btnSubmitASN`, `cancelShipment`, `btnCancel` (Clear Values), `validateShipment` (unless `flow.click_validate`) raise `ForbiddenActionError`. "Remove" links are never clicked. |
| G9 No password typing | `flow/steps.py::S0Login` | The tool never fills a password field. When the page title contains `-- Login`, it pauses with `NeedsUser(kind="login_required")` and waits for the user to log in in the visible browser, then continues. |
| G3 Keyboard guard | `actions.py` | `page.keyboard.press("Enter")` is never used on shipment pages (Enter can trigger a default form button). Fields are filled with `fill()`; forms are advanced only by explicit button clicks. |
| G4 Dry run | config `flow.dry_run` | When true: steps S1–S5 run up to (not including) the click on the shipment header "Save". The run then pauses with `NeedsUser(kind="dry_run_stop")` and finishes with `ShipmentResult.status="dry_run"`. Nothing is persisted on the portal in dry-run (no Save, no Add Selected). |
| G5 Mock assertion | `tests/automation/test_e2e_mock.py` | The mock records `submit_called`; e2e tests assert it stays `False`. |
| G6 Abort | all steps | `request_abort()` sets a flag checked before every action; abort raises `UserAbortError` and the browser is left open as-is. |

### 0.4 Key architectural decisions (summary)

- **Playwright sync API on ONE dedicated long-lived `threading.Thread`** (`AutomationWorker`), **not** a `QThread`. Reason: the automation package must be importable and testable without Qt (pytest e2e against the mock runs the exact same worker); Playwright sync objects (Browser, Context, Page, Locator) are bound to the thread that created them and to its greenlet loop, so one thread owns the browser for the whole app lifetime and receives commands over a `queue.Queue`. The GUI (WP-C) wraps the worker in a `WorkerBridge(QObject)` that converts callback events into Qt signals (cross-thread emission is queued automatically by Qt). Blocking "ask the user" calls are implemented with a per-request `queue.Queue` the worker waits on.
- **Selectors are data** (`automation/selectors.yaml` bundled, `selectors.learned.yaml` in user data). Each key has an ordered list of candidate locators; learned candidates are tried first. The real site was inspected read-only (see `docs/EDI_REAL_STRUCTURE.md`): inbox, shipment header, selected-POs and weight pages have **verified** ids/names which are the primary candidates; PO detail, Search Purchase Orders tab and the Create Carton page are **unverified** (screenshot-based candidates, marked `verified: false`) and are the first targets of calibrate mode.
- **Per-row controls on the real site are keyed by an internal numeric id** (`complete_shipment_N`, `pack_code_N`, `editedSiteWgtquM`). Rows are located by the 9-digit PO text, then the id suffix is derived from a control inside that row (`RowKeyExtractor`, §4.4).
- **Ship dates come from an embedded PDF** on the PO detail page (screenshot image5 shows a PDF viewer). A four-rung ladder is specified in §4.9: DOM text → PDF fetch + `pypdf` → AI vision `read_fields` → ask the user to type the dates.
- **AI is a pluggable `VisionAdvisor` protocol** (core, WP-A owns the protocol file), implemented by WP-C with plain `httpx` for OpenAI-compatible and Anthropic Messages APIs; called by WP-B only on failure or as a date fallback, with a per-run call budget.
- **Portable-first packaging**: PyInstaller one-folder → `EDI-Assistant-portable-x.y.z.zip` (primary) and an Inno Setup installer (secondary). A `portable.flag` next to the exe redirects all user data to `<exe_dir>/data/`.

---

## 1. Directory layout and work packages

Project root: `/Users/HongPhong/Data/Develope/other/shyft/` (venv at `.venv`). Package: `edi_assistant`.

```
shyft/
├── pyproject.toml                         WP-A   project metadata, deps, pytest config
├── SPEC.md                                (this file)
├── README_VI.md                           WP-C   Vietnamese user guide
├── .github/workflows/build-windows.yml    WP-C   CI build of portable zip + installer
├── packaging/
│   ├── edi_assistant.spec                 WP-C   PyInstaller spec (one-folder, windowed)
│   ├── build_windows.ps1                  WP-C   venv → pip → pyinstaller → zip → iscc
│   ├── version_info.txt                   WP-C   Windows version resource (generated by build script from __version__)
│   ├── portable.flag                      WP-C   empty marker copied into the portable zip
│   └── hooks/hook-playwright.py           WP-C   PyInstaller hook collecting the playwright driver
├── installer/edi_assistant.iss            WP-C   Inno Setup script
├── edi_assistant/
│   ├── __init__.py                        WP-A   __version__ = "0.1.0", APP_NAME = "EDIAssistant"
│   ├── __main__.py                        WP-C   `from edi_assistant.app.main import main; main()`
│   ├── core/                              WP-A   shared contracts + pure logic (no Qt, no Playwright)
│   │   ├── __init__.py
│   │   ├── paths.py                       user-data directory resolution (portable / %APPDATA%)
│   │   ├── config.py                      AppConfig dataclasses + YAML load/save/defaults
│   │   ├── models.py                      domain dataclasses (POLine, ShipmentPlan, results…)
│   │   ├── events.py                      worker→GUI event dataclasses, UserResponse
│   │   ├── errors.py                      error taxonomy
│   │   ├── ai_interface.py                VisionAdvisor protocol + request/response dataclasses
│   │   ├── dates.py                       ship-date parsing + midpoint/intersection rules
│   │   ├── quantities.py                  carton math, ordered-qty cross-check
│   │   ├── textnorm.py                    text normalisation helpers (NFKC, token sets)
│   │   └── logging_setup.py               rotating file logger in <data>/logs
│   ├── data/                              WP-A   Excel + templates + factories + planning
│   │   ├── __init__.py
│   │   ├── excel_reader.py                openpyxl loading, sheet grid, merged-cell aware
│   │   ├── header_detect.py               header row scoring, two-row header merge
│   │   ├── synonyms.py                    EN/ZH/VI synonym dictionary + field matching
│   │   ├── mapping.py                     ColumnMapping, suggestion, validation
│   │   ├── templates.py                   fingerprint, TemplateStore (JSON files)
│   │   ├── values.py                      cell value parsing (numbers with units, PO ids)
│   │   ├── rows.py                        grid + mapping → list[POLine]
│   │   ├── factories.py                   FactoryStore (factories.json) + name suggestion
│   │   ├── planner.py                     POLine list → RunPlan (grouping, line suffixes)
│   │   ├── results.py                     results.csv / run.json writer
│   │   └── excel_writeback.py             copy of Excel with ASN column
│   ├── automation/                        WP-B   Playwright, selectors, flow, calibration
│   │   ├── __init__.py
│   │   ├── selectors.yaml                 bundled candidate locators
│   │   ├── selectors.py                   SelectorStore (bundled+learned merge), SelectorResolver
│   │   ├── session.py                     BrowserSession (launch, persistent profile, page tracking)
│   │   ├── actions.py                     SafeActions (click/fill/select with guards + logging)
│   │   ├── dialogs.py                     native dialog handling, popup adoption
│   │   ├── dom_snapshot.py                aria snapshot + simplified DOM + screenshot capture
│   │   ├── healing.py                     Healer: AI locator proposal / explanation with budget
│   │   ├── po_dates.py                    ship-date ladder (DOM, PDF via pypdf, AI, user)
│   │   ├── commands.py                    worker command dataclasses
│   │   ├── worker.py                      AutomationWorker thread + command loop + ask_user
│   │   ├── calibrate.py                   highlight / picker / inspector
│   │   ├── picker.js                      injected element picker
│   │   └── flow/
│   │       ├── __init__.py
│   │       ├── context.py                 FlowContext (page, actions, plan, results, ask_user)
│   │       ├── steps.py                   Step classes S1…S9
│   │       └── runner.py                  FlowRunner state machine
│   ├── mock_edi/                          WP-B   local mock of the portal (stdlib http.server)
│   │   ├── __init__.py
│   │   ├── __main__.py                    `python -m edi_assistant.mock_edi --port 8765`
│   │   ├── state.py                       in-memory state + seed data
│   │   ├── pages.py                       HTML rendering functions
│   │   ├── minipdf.py                     minimal text PDF generator (for the PDF-dates variant)
│   │   └── server.py                      routes, MockServer class (start/stop in-thread)
│   └── app/                               WP-C   PySide6 GUI, AI clients, packaging glue
│       ├── __init__.py
│       ├── main.py                        QApplication bootstrap, single-instance guard, tray
│       ├── strings_vi.py                  all Vietnamese UI strings (module-level constants)
│       ├── main_window.py                 MainWindow
│       ├── worker_bridge.py               WorkerBridge(QObject): worker callbacks → signals
│       ├── tray.py                        TrayIcon
│       ├── notifications.py               balloon/toast + sound (Windows bits guarded)
│       ├── browser_install.py             first-run chromium download with progress dialog
│       ├── single_instance.py             QLocalServer/QLocalSocket guard
│       ├── autostart.py                   HKCU Run key (Windows only)
│       ├── dialogs/
│       │   ├── __init__.py
│       │   ├── mapping_dialog.py          column mapping editor
│       │   ├── factory_dialog.py          factory list editor / picker
│       │   ├── settings_dialog.py         site, browser, flow, AI provider settings
│       │   ├── pause_dialog.py            NeedsUser dialog (Continue/Skip/Abort, inputs)
│       │   └── calibrate_dialog.py        selector keys list, highlight/pick/save/inspector
│       ├── widgets/
│       │   ├── __init__.py
│       │   ├── steps_view.py              step list with status icons
│       │   ├── plan_table.py              review table of planned PO lines
│       │   └── log_view.py                log tail
│       ├── ai/
│       │   ├── __init__.py                build_advisor(config) factory
│       │   ├── prompts.py                 prompt templates (verbatim from §7)
│       │   ├── openai_compat.py           OpenAICompatAdvisor (httpx)
│       │   └── anthropic_client.py        AnthropicAdvisor (httpx)
│       └── resources/
│           ├── app.ico, app.png           icon
│           └── notify.wav                 notification sound
└── tests/
    ├── data/                              WP-A   (own conftest.py)
    ├── automation/                        WP-B   (own conftest.py; starts mock server)
    └── app/                               WP-C   (own conftest.py; pytest-qt)
```

Ownership rules:
- WP-A owns `pyproject.toml`, `edi_assistant/__init__.py`, `core/`, `data/`, `tests/data/`.
- WP-B owns `automation/`, `mock_edi/`, `tests/automation/`.
- WP-C owns `app/`, `__main__.py`, `packaging/`, `installer/`, `.github/`, `README_VI.md`, `tests/app/`.
- There is **no** top-level `tests/conftest.py`. Each WP has its own.
- The shared contract files (`core/paths.py`, `core/config.py`, `core/models.py`, `core/events.py`, `core/errors.py`, `core/ai_interface.py`) are written by WP-A **verbatim from §2 within the first hour** and committed before anything else. WP-B/WP-C may paste §2 code locally to unblock themselves but must never commit files under `core/`.

### 1.1 pyproject.toml (WP-A)

```toml
[project]
name = "edi-assistant"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "PySide6>=6.7",
  "playwright>=1.45",
  "openpyxl>=3.1",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "pypdf>=4.2",
]
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-qt>=4.4", "pyinstaller>=6.6"]

[tool.pytest.ini_options]
testpaths = ["tests"]
qt_api = "pyside6"
markers = ["e2e: launches a browser against the mock site"]
```

`edi_assistant/__init__.py`:
```python
__version__ = "0.1.0"
APP_NAME = "EDIAssistant"
APP_DISPLAY_NAME = "EDI Assistant"
```

---

## 2. Shared contracts (owner: WP-A, package `edi_assistant.core`)

All dataclasses use `from __future__ import annotations`, `@dataclass(slots=True)` unless noted, and `Decimal` for quantities/weights. No Qt, no Playwright imports anywhere in `core`.

### 2.1 `core/paths.py`

```python
from pathlib import Path
import os, sys

def exe_dir() -> Path:
    """Directory of the running executable (frozen) or the repo root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]

def is_portable() -> bool:
    """True if <exe_dir>/portable.flag exists OR <exe_dir>/data/ is a directory."""

def user_data_dir() -> Path:
    """
    Portable: <exe_dir>/data
    Windows:  %APPDATA%/EDI Assistant
    macOS:    ~/Library/Application Support/EDI Assistant
    Linux:    $XDG_DATA_HOME or ~/.local/share, + /EDI Assistant
    Override for tests: env EDI_ASSISTANT_DATA_DIR (highest priority).
    Creates the directory.
    """

def local_data_dir() -> Path:
    """
    Large/cache data (browser profile, ms-playwright download).
    Portable: same as user_data_dir()
    Windows:  %LOCALAPPDATA%/EDI Assistant
    others:   user_data_dir()
    """

# Fixed sub-paths (all functions create parent dirs):
def config_path() -> Path:            # user_data_dir()/config.yaml
def templates_dir() -> Path:          # user_data_dir()/templates
def factories_path() -> Path:         # user_data_dir()/factories.json
def learned_selectors_path() -> Path: # user_data_dir()/selectors.learned.yaml
def logs_dir() -> Path:               # user_data_dir()/logs
def runs_dir() -> Path:               # user_data_dir()/runs
def run_dir(run_id: str) -> Path:     # runs_dir()/<run_id>
def browser_profile_dir() -> Path:    # local_data_dir()/browser_profile
def playwright_browsers_dir() -> Path:# local_data_dir()/ms-playwright
def bundled_selectors_path() -> Path: # Path(edi_assistant.automation.__file__).parent / "selectors.yaml"  (works frozen; resolved lazily via importlib.resources.files)
```

`run_id` format: `time.strftime("%Y%m%d-%H%M%S")` + `-` + 4 hex chars.

### 2.2 `core/config.py`

```python
@dataclass(slots=True)
class SiteConfig:
    base_url: str = "https://edi.coat.com/vms-gateway/"
    use_mock: bool = False                 # when True, effective_base_url() returns mock_url
    mock_url: str = "http://127.0.0.1:8765/vms-gateway/"
    vendor_profile_name: str = "SHYFT GLOBAL LLC"   # link text clicked on the Select Profile page
    def effective_base_url(self) -> str: ...   # always ends with "/"

@dataclass(slots=True)
class BrowserConfig:
    channel: str = "msedge"                # "msedge" | "chrome" | "chromium"
    headless: bool = False
    slow_mo_ms: int = 0
    default_timeout_ms: int = 15000
    viewport_width: int = 1280
    viewport_height: int = 900

@dataclass(slots=True)
class FlowConfig:
    grouping: str = "per_file"             # "per_file" | "per_master_po"
    dry_run: bool = False
    weight_mode: str = "total_gw"          # "total_gw" (binding default) | "per_carton_gw" (= total_gw / packages)
    shipping_type: str = "Ship to DC"
    transportation_method: str = "Containerized Ocean"
    scac_code: str = "MAEU"                # matched against option text starting with this code, e.g. "MAEU-MAERSK"
    bill_of_lading: str = "Unknown"
    pro_number: str = "Unknown"
    packaging_code_carton: str = "Physical Container - Carton"
    complete_partial: str = "Partial"
    weight_um: str = "KG"
    click_validate: bool = False
    write_back_excel: bool = True
    pause_on_qty_warning: bool = True

@dataclass(slots=True)
class AiConfig:
    enabled: bool = False
    provider: str = "anthropic"            # "anthropic" | "openai_compat"
    base_url: str = "https://api.anthropic.com"   # openai_compat example: "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "claude-haiku-5-5"
    vision: bool = True
    max_calls_per_run: int = 8
    timeout_s: int = 60
    max_tokens: int = 800

@dataclass(slots=True)
class NotifyConfig:
    sound: bool = True
    balloon: bool = True
    start_minimized: bool = False
    start_with_windows: bool = False

@dataclass(slots=True)
class UiConfig:
    last_excel_dir: str = ""
    last_factory_id: str = ""
    window_geometry_b64: str = ""

@dataclass(slots=True)
class AppConfig:
    version: int = 1
    site: SiteConfig = field(default_factory=SiteConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    flow: FlowConfig = field(default_factory=FlowConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    ui: UiConfig = field(default_factory=UiConfig)

def load_config(path: Path | None = None) -> AppConfig
    # missing file → defaults; unknown keys ignored; missing keys → defaults (forward compatible)
def save_config(cfg: AppConfig, path: Path | None = None) -> None
    # yaml.safe_dump(asdict(cfg), sort_keys=False, allow_unicode=True), atomic write (tmp + os.replace)
def config_to_dict(cfg: AppConfig) -> dict
def config_from_dict(d: dict) -> AppConfig
```

YAML file layout mirrors the dataclass nesting exactly (`site:`, `browser:`, `flow:`, `ai:`, `notify:`, `ui:`). `api_key` is stored in plain text in the user's profile directory (documented in README_VI; acceptable for this tool).

Provider presets (WP-C uses these in the settings dialog; defined here so tests can share them):

```python
AI_PRESETS: dict[str, dict] = {
  "anthropic":   {"provider": "anthropic",     "base_url": "https://api.anthropic.com",                      "model": "claude-haiku-5-5"},
  "anthropic_sonnet": {"provider": "anthropic","base_url": "https://api.anthropic.com",                      "model": "claude-sonnet-5-5"},
  "openai":      {"provider": "openai_compat", "base_url": "https://api.openai.com/v1",                      "model": "gpt-4o-mini"},
  "gemini":      {"provider": "openai_compat", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.0-flash"},
  "deepseek":    {"provider": "openai_compat", "base_url": "https://api.deepseek.com/v1",                    "model": "deepseek-chat"},
  "qwen":        {"provider": "openai_compat", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-vl-plus"},
  "openrouter":  {"provider": "openai_compat", "base_url": "https://openrouter.ai/api/v1",                   "model": "anthropic/claude-haiku-5-5"},
  "ollama":      {"provider": "openai_compat", "base_url": "http://localhost:11434/v1",                      "model": "llava"},
}
```

### 2.3 `core/models.py`

```python
from decimal import Decimal
from datetime import date

FIELD_KEYS: tuple[str, ...] = ("po", "line", "description", "packages", "quantity",
                               "gross_weight", "net_weight", "size")
REQUIRED_FIELDS: tuple[str, ...] = ("po", "packages", "quantity", "gross_weight")

@dataclass(slots=True)
class Flag:
    code: str            # see §2.7 flag codes
    message_vi: str
    severity: str = "warning"   # "info" | "warning" | "error"

@dataclass(slots=True)
class POLine:
    master_po: str                 # 7 digits, e.g. "5803674"
    line: int                      # 1..99
    excel_row: int                 # 1-based source row
    description: str = ""
    packages: Decimal = Decimal(0)         # cartons (Excel "Packages")
    quantity: Decimal = Decimal(0)         # units (Excel "Quantity")
    gross_weight: Decimal = Decimal(0)     # KG, total for the row
    net_weight: Decimal | None = None
    size: str = ""
    raw: dict[str, object] = field(default_factory=dict)   # field_key -> raw cell value
    flags: list[Flag] = field(default_factory=list)

    @property
    def po_line_id(self) -> str:   # f"{master_po}{line:02d}"  e.g. "580367401"
    @property
    def item_label(self) -> str:   # f"PO{master_po}LN{line}"  e.g. "PO5803674LN1" (as shown on carton page)

@dataclass(slots=True)
class FactoryAddress:
    id: str                        # uuid4 hex
    name: str
    address1: str
    address2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "CHINA"         # option text in the Country select
    site_no: str = ""              # optional "Site No" option text; "" = leave "Select One"
    aliases: list[str] = field(default_factory=list)   # extra names for matching

@dataclass(slots=True)
class CartonPlan:
    units_per_carton: Decimal      # quantity / packages
    qty_per_carton: int            # value typed into "Qty Per Carton"
    cartons_per_site: int          # value typed into "Cartons Per Site"
    prepack_units: int | None      # N when a prepack sub-row was detected, else None
    flags: list[Flag]

@dataclass(slots=True)
class DateWindow:
    early: date
    late: date

@dataclass(slots=True)
class ShipDateResult:
    shipping_date: date
    window: DateWindow | None      # intersection used, None if no intersection
    flags: list[Flag]

@dataclass(slots=True)
class PlannedLine:
    po_line: POLine
    weight_kg: Decimal             # already rounded to 2 dp per weight_mode
    weight_text: str               # f"{weight_kg:.2f}"
    carton: CartonPlan | None = None       # filled during the run once prepack is known
    web_qty_ordered: Decimal | None = None
    web_um: str = ""
    status: str = "pending"        # "pending" | "added" | "carton_done" | "weight_done" | "skipped" | "failed"
    error: str = ""

@dataclass(slots=True)
class ShipmentPlan:
    index: int                     # 1-based within the run
    label: str                     # "Lô 1 (5803674, 5803673)"
    lines: list[PlannedLine]
    factory: FactoryAddress
    master_pos: list[str]          # distinct, in order of appearance
    shipping_date: date | None = None       # computed during run
    date_result: ShipDateResult | None = None
    po_windows: dict[str, DateWindow] = field(default_factory=dict)   # master_po -> window
    to_site_no: str = ""           # read from the header page after Save
    web_shipment_id: str = ""
    asn_shipment_id: str = ""
    status: str = "pending"        # "pending" | "running" | "done" | "dry_run" | "failed" | "aborted"
    flags: list[Flag] = field(default_factory=list)

@dataclass(slots=True)
class RunPlan:
    run_id: str
    source_file: str               # absolute path of the Excel file
    sheet_name: str
    template_fingerprint: str
    shipments: list[ShipmentPlan]
    grouping: str                  # copied from FlowConfig
    dry_run: bool
    created_at: str                # ISO-8601

@dataclass(slots=True)
class RunResult:
    run_id: str
    status: str                    # "done" | "partial" | "failed" | "aborted" | "dry_run"
    shipments: list[ShipmentPlan]  # same objects, mutated with ids/status
    results_csv: str               # path
    started_at: str
    finished_at: str
    error: str = ""
    ai_calls_used: int = 0
```

### 2.4 `core/events.py`

```python
@dataclass(slots=True)
class Event:               # base; every event has these
    ts: float = field(default_factory=time.time)

@dataclass(slots=True)
class RunStarted(Event):
    run_id: str = ""
    total_steps: int = 0

@dataclass(slots=True)
class StepStarted(Event):
    step_id: str = ""              # e.g. "S5.fill_header"
    title_vi: str = ""
    shipment_index: int = 0
    po_line_id: str = ""           # "" when not line-specific
    index: int = 0                 # running step number
    total: int = 0

@dataclass(slots=True)
class StepFinished(Event):
    step_id: str = ""
    status: str = "ok"             # "ok" | "skipped" | "failed"
    detail: str = ""
    duration_s: float = 0.0

@dataclass(slots=True)
class Progress(Event):
    percent: int = 0
    message_vi: str = ""

@dataclass(slots=True)
class LogEvent(Event):
    level: str = "INFO"            # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    message: str = ""

@dataclass(slots=True)
class InputField:
    key: str                       # e.g. "early_ship_date"
    label_vi: str
    default: str = ""
    placeholder: str = ""

@dataclass(slots=True)
class NeedsUser(Event):
    request_id: str = ""           # uuid4 hex
    kind: str = ""                 # "step_failed" | "login_required" | "qty_mismatch" | "non_integer_carton"
                                   # | "po_replaced" | "dry_run_stop" | "dates_needed" | "no_date_intersection"
                                   # | "country_not_in_list" | "unverified_selector" | "finished_review" | "confirm"
    message_vi: str = ""
    step_id: str = ""
    screenshot_path: str = ""
    ai_explanation_vi: str = ""
    options: list[str] = field(default_factory=lambda: ["continue", "skip", "abort"])
    input_fields: list[InputField] = field(default_factory=list)

@dataclass(slots=True)
class UserResponse:
    request_id: str
    action: str                    # "continue" | "skip" | "abort"
    values: dict[str, str] = field(default_factory=dict)

@dataclass(slots=True)
class ShipmentCreated(Event):
    shipment_index: int = 0
    web_shipment_id: str = ""
    asn_shipment_id: str = ""

@dataclass(slots=True)
class BrowserState(Event):
    is_open: bool = False
    url: str = ""
    logged_in: bool | None = None  # None = unknown

@dataclass(slots=True)
class CalibrationResult(Event):
    key: str = ""
    candidate: dict | None = None  # SelectorCandidate as dict, None = cancelled
    saved: bool = False

@dataclass(slots=True)
class RunFinished(Event):
    result: "RunResult | None" = None

EventSink = Callable[[Event], None]
```

Protocol between worker and GUI:
1. GUI → worker: `submit(Command)` (see §4.12) and `respond(UserResponse)`.
2. Worker → GUI: `EventSink` callback, called **from the worker thread**. The GUI must marshal to the UI thread (WorkerBridge).
3. `NeedsUser` blocks the worker until a `UserResponse` with the same `request_id` arrives, or until abort. `options` tells the GUI which buttons to show; `input_fields` non-empty means the dialog must show text inputs and return `values`.
4. Semantics of `UserResponse.action` on `kind="step_failed"`: `continue` = re-check the step postcondition, if satisfied mark ok, else re-run the step action; `skip` = mark step skipped and move on; `abort` = raise `UserAbortError`.

### 2.5 `core/errors.py`

```python
class EdiAssistantError(Exception):
    code: str = "generic"
    def __init__(self, message: str, *, message_vi: str = "", **ctx): ...
    # .message (English, for logs), .message_vi (for UI; defaults to message), .ctx dict

# Data (WP-A raises)
class ExcelReadError(EdiAssistantError):        code = "excel_read"
class HeaderNotFoundError(EdiAssistantError):   code = "header_not_found"
class MappingIncompleteError(EdiAssistantError):code = "mapping_incomplete"   # ctx: missing=list[str]
class RowParseError(EdiAssistantError):         code = "row_parse"            # ctx: row=int, field=str, raw=object
class PlanError(EdiAssistantError):             code = "plan"
class ConfigError(EdiAssistantError):           code = "config"

# Automation (WP-B raises)
class BrowserLaunchError(EdiAssistantError):    code = "browser_launch"
class NavigationError(EdiAssistantError):       code = "navigation"
class ElementNotFoundError(EdiAssistantError):  code = "element_not_found"    # ctx: key=str, tried=list[str]
class PostconditionFailed(EdiAssistantError):   code = "postcondition"        # ctx: step_id=str
class DataMismatchError(EdiAssistantError):     code = "data_mismatch"
class ForbiddenActionError(EdiAssistantError):  code = "forbidden_action"
class SessionExpiredError(EdiAssistantError):   code = "session_expired"
class UserAbortError(EdiAssistantError):        code = "user_abort"
class StepSkipped(EdiAssistantError):           code = "step_skipped"         # control flow, not an error

# AI (WP-C raises, WP-B catches)
class AiError(EdiAssistantError):               code = "ai"                   # ctx: provider=str, status=int|None
class AiBudgetExceeded(EdiAssistantError):      code = "ai_budget"
```

### 2.6 `core/ai_interface.py`

```python
@dataclass(slots=True)
class LocatorRequest:
    key: str                       # selector key, e.g. "inbox.document_id_input"
    description: str               # from selectors.yaml, English
    page_url: str
    page_title: str
    aria_snapshot: str             # truncated to 12_000 chars
    dom_excerpt: str               # simplified DOM, truncated to 12_000 chars
    screenshot_jpeg: bytes | None  # None when vision disabled
    tried: list[str]               # textual form of candidates already tried

@dataclass(slots=True)
class LocatorProposal:
    candidates: list[dict]         # each a SelectorCandidate dict (see §4.3), best first
    confidence: float
    notes: str = ""

@dataclass(slots=True)
class ExplainRequest:
    step_id: str
    step_title_vi: str
    error_text: str                # exception text
    page_url: str
    aria_snapshot: str
    dom_excerpt: str
    screenshot_jpeg: bytes | None

@dataclass(slots=True)
class Explanation:
    explanation_vi: str
    likely_cause: str              # "session_expired" | "validation_error" | "layout_changed" | "popup" | "network" | "unknown"
    user_action_vi: str

@dataclass(slots=True)
class ReadFieldsRequest:
    fields: list[str]              # e.g. ["early_ship_date", "late_ship_date"]
    hint: str                      # English description of where to look
    screenshot_jpeg: bytes

@dataclass(slots=True)
class ReadFieldsResult:
    values: dict[str, str]         # field -> raw string as seen ("09-MAR-26"); missing keys = not found
    confidence: float

class VisionAdvisor(Protocol):
    name: str                      # "anthropic:claude-haiku-5-5"
    supports_vision: bool
    def propose_locator(self, req: LocatorRequest) -> LocatorProposal | None: ...
    def explain_error(self, req: ExplainRequest) -> Explanation | None: ...
    def read_fields(self, req: ReadFieldsRequest) -> ReadFieldsResult | None: ...
```

Contract: implementations never raise on provider errors except `AiError`; they return `None` when the model output cannot be parsed. Timeouts are `AiConfig.timeout_s`. Callers (WP-B `Healer`) enforce the budget and catch `AiError`.

### 2.7 Flag codes (used in `Flag.code`)

| code | severity | meaning / message_vi |
|---|---|---|
| `line_assigned` | info | Line suffix assigned by order of appearance: "Đã tự gán số dòng {line:02d} cho PO {master}" |
| `non_integer_units` | error | quantity/packages not integer: "Số lượng {qty} không chia hết cho số thùng {pkgs}" |
| `non_integer_prepack` | error | units_per_carton / prepack N not integer |
| `qty_over_ordered` | warning | Excel qty > web ordered |
| `qty_under_ordered` | info | Excel qty < web ordered (partial) |
| `no_date_intersection` | warning | PO windows do not overlap; first PO's midpoint used |
| `date_in_past` | warning | midpoint before today; moved to today / late |
| `dates_manual` | info | dates typed by user |
| `weight_zero` | warning | gross weight missing or 0 |
| `po_replaced` | error | PO shows "Replaced" on the portal |
| `totals_row_skipped` | info | Excel row skipped (no PO) |

---
## 3. WP-A — data layer (`edi_assistant.data`, plus `core/dates.py`, `core/quantities.py`, `core/textnorm.py`)

Reference sample: `docs/5803674 & 5803673 PKL.xlsx`, sheet `page 1`, dimensions A1:I8, merged `B1:I1, B2:I2, C3:D3, C4:D4, B8:I8`. Row 3 Chinese headers (B3 品名, C3 包装, E3 数量, F3 毛重, G3 净重, H3 尺码), row 4 English headers (A4 PO, B4 Description, C4 Packages, E4 Quantity, F4 G.W.(KGS), G4 N.W.(KGS), H4 Size). Data rows 5–6; row 7 totals (A7 empty); row 8 merged footer text containing the factory name and address. Cell types vary: `'85'` vs `85`, `'510 PCS'`, `'1,020     PCS'`, `'1020.00'` vs `1020`.

### 3.1 `core/textnorm.py`

```python
def normalize_header(s: object) -> str:
    """NFKC → str → lowercase → replace '\n' with ' ' → remove characters that are not
    [a-z0-9], CJK (一-鿿), Vietnamese letters (unicode letters) or space → collapse spaces → strip.
    'G.W.(KGS)' -> 'gw kgs'; '品名/Description' -> '品名 description'; 'Packages' -> 'packages'."""
def header_tokens(s: str) -> list[str]        # normalize_header(s).split()
def normalize_company(s: str) -> str          # lowercase NFKC, strip punctuation, drop stop words {co, ltd, limited, company, inc, corp, corporation, the, llc}
def token_set(s: str) -> set[str]
def jaccard(a: set[str], b: set[str]) -> float
```

### 3.2 `data/excel_reader.py`

```python
@dataclass(slots=True)
class CellInfo:
    row: int; col: int            # 1-based
    value: object                 # raw openpyxl value (str|int|float|datetime|None)
    merged_span: tuple[int, int]  # (n_rows, n_cols) of the merged range whose top-left is this cell; (1,1) if not merged
    is_merged_child: bool         # True for non-top-left cells of a merged range

@dataclass(slots=True)
class SheetGrid:
    sheet_name: str
    max_row: int
    max_col: int
    cells: dict[tuple[int, int], CellInfo]           # only non-None values + merged top-lefts
    def get(self, row: int, col: int) -> object      # value or None
    def row_values(self, row: int) -> dict[int, object]   # col -> value (non-None only)
    def text_blobs(self) -> list[str]                # every str value with len > 20 (title/footer blocks), document order

def list_sheets(path: Path) -> list[str]
def load_grid(path: Path, sheet_name: str | None = None) -> SheetGrid
    # openpyxl.load_workbook(path, data_only=True, read_only=False); warnings filtered; raises ExcelReadError
def col_letter(col: int) -> str ; def col_index(letter: str) -> int   # thin wrappers over openpyxl.utils
```

### 3.3 `data/synonyms.py`

```python
SYNONYMS: dict[str, list[str]] = {
  "po":           ["po", "po no", "po number", "po#", "purchase order", "purchase order no", "order no", "order number",
                   "订单号", "采购订单", "po号", "订单", "số po", "mã po", "đơn hàng", "số đơn hàng"],
  "line":         ["line", "line no", "line number", "ln", "line item", "item no", "行号", "行", "dòng", "số dòng"],
  "description":  ["description", "desc", "item", "item description", "style", "style no", "article", "article no",
                   "product", "品名", "货号", "款号", "品名规格", "mô tả", "tên hàng", "mã hàng"],
  "packages":     ["packages", "package", "pkgs", "ctn", "ctns", "carton", "cartons", "carton qty", "no of ctn",
                   "no of cartons", "qty of ctn", "件数", "箱数", "包装", "箱", "số thùng", "thùng", "số kiện", "kiện"],
  "quantity":     ["quantity", "qty", "pcs", "pieces", "total qty", "total quantity", "qty pcs", "数量", "总数量",
                   "số lượng", "sl", "tổng số lượng"],
  "gross_weight": ["gw", "g w", "gw kgs", "gw kg", "gross weight", "gross weight kgs", "gross wt", "毛重", "毛重kgs",
                   "trọng lượng cả bì", "tổng trọng lượng", "trọng lượng gross"],
  "net_weight":   ["nw", "n w", "nw kgs", "nw kg", "net weight", "net weight kgs", "net wt", "净重",
                   "trọng lượng tịnh", "trọng lượng net"],
  "size":         ["size", "sizes", "measurement", "meas", "measurements", "dimension", "dimensions", "cbm", "carton size",
                   "尺码", "尺寸", "规格", "体积", "kích thước", "kích cỡ", "thể tích"],
}

def match_field(header_text: str) -> tuple[str | None, float]:
    """Return (field_key, score). Normalize header; for each field compute best score over its synonyms:
    1.0 if normalized header == normalized synonym;
    0.85 if header tokens ⊇ synonym tokens (synonym fully contained, e.g. 'gw kgs' contains 'gw');
    0.7 if synonym string is a substring of the header or vice versa and len(synonym) >= 3;
    else 0. Ambiguity rule: '件数' scores 0.6 for packages and 0.5 for quantity (special-case).
    Return the best field if score >= 0.7 else (None, score)."""
def is_headerish(header_text: str) -> bool     # match_field(...)[1] >= 0.7
```

### 3.4 `data/header_detect.py`

```python
@dataclass(slots=True)
class HeaderColumn:
    col: int
    letter: str
    texts: list[str]              # header texts for this column, top row first (e.g. ["包装", "Packages"])
    joined: str                   # " / ".join(texts)         e.g. "包装 / Packages"
    normalized: str               # normalize_header(joined)
    span_cols: int                # merged width of the header cell (Packages = 2)

@dataclass(slots=True)
class HeaderDetection:
    header_rows: list[int]        # 1 or 2 row indices, ascending (e.g. [3, 4])
    data_start_row: int           # max(header_rows) + 1
    columns: list[HeaderColumn]   # ordered by col
    score: float

def score_row(grid: SheetGrid, row: int) -> float:
    """Σ over non-empty cells of row:
       +3 if str and is_headerish(value)
       +1 if str and len(value) <= 30 (and not headerish)
       -2 if int/float/datetime
       -1 if str and len(value) > 40
       -2 if the cell's merged_span[1] >= 4 (wide title block)
       Rows with < 3 non-empty cells score -inf."""
def detect_header(grid: SheetGrid, max_scan_rows: int = 40) -> HeaderDetection:
    """h = argmax score_row over rows 1..min(max_scan_rows, max_row), ties → smallest row.
    Raise HeaderNotFoundError if best score < 6.
    Two-row header: let p = h-1. If p >= 1 and score_row(p) >= 0.5*score_row(h) and
    |cols(p) ∩ cols(h)| / |cols(p)| >= 0.5 (cols = non-empty columns), header_rows = [p, h] else [h].
    Columns = union of non-empty columns across header_rows; texts in row order; a header cell
    that is merged horizontally (span_cols > 1) claims only its top-left column for data."""
```

For the sample: row 4 scores 7×3 = 21, row 3 scores 6×3 = 18 → header_rows [3,4]; columns A("PO"), B("品名 / Description"), C("包装 / Packages", span 2), E, F, G, H.

### 3.5 `data/mapping.py`

```python
@dataclass(slots=True)
class ColumnRef:
    letter: str                   # "C"
    header: str                   # joined header text at mapping time, "包装 / Packages"

@dataclass(slots=True)
class ColumnMapping:
    columns: dict[str, ColumnRef | None]     # key ∈ FIELD_KEYS; None = not mapped
    def missing_required(self) -> list[str]
    def is_complete(self) -> bool

def suggest_mapping(det: HeaderDetection) -> tuple[ColumnMapping, dict[str, float]]:
    """For each column compute match_field(column.joined). Assign each field the highest-scoring column
    (score >= 0.7); a column is used at most once; conflicts resolved by score then leftmost column.
    Returns the mapping and {field: score} for the UI to colour confidence."""
def apply_template_to_detection(tmpl: "Template", det: HeaderDetection) -> ColumnMapping:
    """For each field in tmpl.columns: find a detected column whose normalized header equals the
    template's normalized header → use it; else if a column with the same letter exists → use it;
    else None."""
def validate_mapping(m: ColumnMapping) -> None     # raises MappingIncompleteError(missing=[...])
```

### 3.6 `data/templates.py` — fingerprint and template store

Template JSON file `templates/<fingerprint>.json`:

```json
{
  "version": 1,
  "fingerprint": "3f2a…(sha1 hex)",
  "name": "SUMEC packing list",
  "created_at": "2026-10-18T10:00:00",
  "updated_at": "2026-10-18T10:00:00",
  "sheet_name": "page 1",
  "header_rows": [3, 4],
  "header_tokens": ["包装 packages", "品名 description", "尺码 size", "数量 quantity", "毛重 gw kgs", "净重 nw kgs", "po"],
  "columns": {
    "po":           {"letter": "A", "header": "PO"},
    "line":         null,
    "description":  {"letter": "B", "header": "品名 / Description"},
    "packages":     {"letter": "C", "header": "包装 / Packages"},
    "quantity":     {"letter": "E", "header": "数量 / Quantity"},
    "gross_weight": {"letter": "F", "header": "毛重 / G.W.(KGS)"},
    "net_weight":   {"letter": "G", "header": "净重 / N.W.(KGS)"},
    "size":         {"letter": "H", "header": "尺码 / Size"}
  },
  "factory_id": "8c1d…" ,
  "use_count": 3
}
```

```python
@dataclass(slots=True)
class Template:
    fingerprint: str; name: str; created_at: str; updated_at: str
    sheet_name: str; header_rows: list[int]; header_tokens: list[str]
    columns: dict[str, ColumnRef | None]
    factory_id: str = ""
    use_count: int = 0
    def to_mapping(self) -> ColumnMapping

def compute_fingerprint(det: HeaderDetection) -> tuple[str, list[str]]:
    """header_tokens = sorted({c.normalized for c in det.columns if c.normalized});
    fingerprint = sha1(json.dumps({"tokens": header_tokens, "ncols": len(det.columns)}, ensure_ascii=False)).hexdigest()"""

@dataclass(slots=True)
class TemplateMatch:
    template: Template
    kind: str                     # "exact" | "similar"
    similarity: float             # 1.0 for exact; Jaccard of token sets for similar

class TemplateStore:
    def __init__(self, directory: Path | None = None)   # default paths.templates_dir()
    def list(self) -> list[Template]
    def get(self, fingerprint: str) -> Template | None
    def save(self, t: Template) -> None                 # atomic write, updates updated_at
    def delete(self, fingerprint: str) -> None
    def find(self, det: HeaderDetection) -> TemplateMatch | None:
        """exact fingerprint → kind="exact". Else best Jaccard(token sets) >= 0.75 → kind="similar".
        Else None."""
    def learn(self, det: HeaderDetection, mapping: ColumnMapping, name: str, factory_id: str, sheet_name: str) -> Template
```

GUI contract: `exact` → auto-apply silently (status text "Đã nhận dạng mẫu: {name}"); `similar` → pre-fill mapping and require the user to confirm (status "Mẫu gần giống: {name} — vui lòng kiểm tra"); None → `suggest_mapping` and require confirm. After the user confirms, `learn()` is always called (exact match: `use_count += 1`).

### 3.7 `data/values.py`

```python
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
def parse_decimal(v: object) -> Decimal | None:
    """None/'' → None. int/float → Decimal(str(v)). str: NFKC, remove ',' and all whitespace,
    first NUMBER_RE match → Decimal; no match → None. '1,020     PCS' → 1020; '510 PCS' → 510; '1020.00' → 1020.00"""
def parse_int_exact(v: object) -> int | None     # parse_decimal, must be integral, else None
def parse_po_cell(v: object) -> tuple[str, int | None] | None:
    """Accept int, float (x.0) or str. Extract digit groups: s = re.sub(r'\D', '', str(v)) after dropping a
    trailing '.0'. If a separator pattern r'^(\d{7})\s*[-_/ ]\s*(\d{1,2})$' matches the raw string → (master, line).
    len(s)==7 → (s, None); len(s)==9 → (s[:7], int(s[7:])); otherwise None."""
def parse_line_cell(v: object) -> int | None     # 1..99 else None
def format_weight(d: Decimal) -> str              # quantize(Decimal('0.01'), ROUND_HALF_UP) → f"{x:.2f}"
def to_text(v: object) -> str                     # None→"", float integral→"85", else str(v).strip()
```

### 3.8 `data/rows.py`

```python
@dataclass(slots=True)
class RowExtraction:
    lines: list[POLine]
    skipped: list[tuple[int, str]]        # (row, reason_vi)
    company_text: str                     # best factory-name candidate from title/footer, "" if none
    flags: list[Flag]

def extract_rows(grid: SheetGrid, det: HeaderDetection, mapping: ColumnMapping) -> RowExtraction:
    """For row r in det.data_start_row..grid.max_row:
       po_raw = grid.get(r, col(mapping.po)); parsed = parse_po_cell(po_raw)
       if parsed is None → skipped (reason "Không có PO (dòng tổng/ghi chú)"), continue
       master, line = parsed; if mapping.line is set and parse_line_cell(cell) → line = that value
       if line is None → assigned later by assign_line_numbers (flag line_assigned)
       packages = parse_decimal(...) (None → RowParseError? NO: → POLine with packages=0 and Flag non_integer_units severity error)
       quantity, gross_weight likewise; net_weight optional; description/size via to_text.
       gross_weight 0/None → flag weight_zero.
    Then assign_line_numbers(lines). company_text = detect_company_text(grid)."""
def assign_line_numbers(lines: list[POLine]) -> None:
    """For lines with line == 0 (unassigned): counter per master_po in order of appearance starting at 1,
    skipping values already used by explicitly-numbered lines of the same master. Adds Flag('line_assigned')."""
COMPANY_RE = re.compile(r"(?i)\b(company|co\.?,?\s*ltd|limited|ltd|factory|industr\w*|textile\w*|garment\w*|manufactur\w*|corp\w*|enterprise\w*|trading)\b")
def detect_company_text(grid: SheetGrid) -> str:
    """Split every text blob on newlines; return the first line (stripped) matching COMPANY_RE whose
    length <= 80; prefer blobs from rows above the header (title) over footer. Sample → 'SUMEC TEXTILE COMPANY LIMITED'."""
```

Internal representation: `POLine.line` is `0` while unassigned inside `extract_rows`; `assign_line_numbers` guarantees ≥ 1 on return.

### 3.9 `data/factories.py`

`factories.json`: `{"version": 1, "factories": [FactoryAddress as dict, ...]}`.

```python
class FactoryStore:
    def __init__(self, path: Path | None = None)
    def list(self) -> list[FactoryAddress]
    def get(self, factory_id: str) -> FactoryAddress | None
    def upsert(self, f: FactoryAddress) -> None       # empty id → assign uuid4().hex
    def delete(self, factory_id: str) -> None
    def suggest(self, company_text: str) -> tuple[FactoryAddress | None, float]:
        """score = max over (name + aliases) of jaccard(token_set(normalize_company(x)), token_set(normalize_company(company_text)));
        also 1.0 if normalize_company(x) is a substring of normalize_company(company_text) or vice versa.
        Return best if score >= 0.5."""
def factory_from_excel_footer(text: str) -> FactoryAddress:
    """Best-effort prefill for the 'new factory' dialog: name = first COMPANY_RE line; address1 = text after the
    name on the same line or the next line; country guessed from {china, 中国 → 'CHINA', vietnam, việt nam → 'VIETNAM'}.
    Sample footer line 'SUMEC TEXTILE COMPANY LIMITED 68 Yunlongshan Road,Jianye District,Nanjing,China' →
    name 'SUMEC TEXTILE COMPANY LIMITED', address1 '68 Yunlongshan Road', address2 'Jianye District', city 'Nanjing', country 'CHINA'
    (split the remainder on commas: last = country, second-last = city, first = address1, middle joined = address2)."""
```

Country handling note for WP-B/WP-C: the real site's From-Country select only lists `US`, `CA`, `CN` directly; other countries need the "More.." popup. `FactoryAddress.country` holds the option **text** (`"CHINA"`, `"UNITED STATES"`, `"CANADA"`, `"VIETNAM"` …). The settings dialog lets the user type it freely.

### 3.10 `core/dates.py`

```python
DATE_PATTERNS = [
  (re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})\b"), "dmy_mon"),   # 09-MAR-26
  (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "mdy"),                 # 03/11/2026
  (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
]
def parse_date_token(tok: str) -> date | None       # 2-digit year → 2000+yy
def parse_ship_dates(text: str) -> DateWindow | None:
    """text = whitespace-collapsed page/PDF text.
    Strategy A (inline): m1 = r'Early\s*Ship\s*Date\s*[:\-]?\s*(<date>)' and m2 = r'Late\s*Ship\s*Date\s*[:\-]?\s*(<date>)' → both found → window.
    Strategy B (label block then value block, as in the PDF layout 'Order Date Early Ship Date Late Ship Date 10-JAN-26 09-MAR-26 13-MAR-26'
      or 'Early Ship Date Late Ship Date ... 09-MAR-26 13-MAR-26'): build the ordered list of label hits among
      {'Order Date':0, 'Early Ship Date':1, 'Late Ship Date':2} (case-insensitive); take the date tokens that appear after
      the last of these labels and before the next occurrence of 'Ship Date' or end; map k-th label ↔ k-th date; need both 1 and 2.
    Strategy C: if exactly two dates occur within 60 chars after the substring 'Ship Date' → (first, second).
    Return None otherwise. Validate early <= late else swap."""
def midpoint(w: DateWindow) -> date                 # w.early + timedelta(days=(w.late - w.early).days // 2)   (floor)
def intersect(windows: list[DateWindow]) -> DateWindow | None   # max(early), min(late); None if empty or early > late
def compute_shipping_date(windows: list[DateWindow], today: date) -> ShipDateResult:
    """w = intersect(windows); flags = []
    if w is None: w = windows[0]; flags += [no_date_intersection]
    d = midpoint(w)
    if d < today: d = today if today <= w.late else w.late; flags += [date_in_past]
    return ShipDateResult(d, w if intersect else None, flags)"""
def format_mdy(d: date) -> str                       # "03/11/2026"
```

Examples: Mar 9–13 → Mar 11; Mar 9–12 → Mar 10; Mar 9–9 → Mar 9.

### 3.11 `core/quantities.py`

```python
def compute_carton_plan(quantity: Decimal, packages: Decimal, prepack_units: int | None) -> CartonPlan:
    """packages must be a positive integer else flag non_integer_units (error) and return qty_per_carton=0, cartons_per_site=0.
    units = quantity / packages; if units not integral → flag non_integer_units (error).
    if prepack_units: qpc = units / prepack_units; if not integral → flag non_integer_prepack (error); else qpc=int
    else qpc = int(units).
    cartons_per_site = int(packages)."""
def check_ordered(excel_qty: Decimal, web_ordered: Decimal | None, web_um: str, prepack_units: int | None) -> list[Flag]:
    """web_ordered None → []. ordered_units = web_ordered * prepack_units if prepack_units else web_ordered.
    excel_qty > ordered_units → [qty_over_ordered]; excel_qty < ordered_units → [qty_under_ordered]; equal → []."""
def weight_for_line(line: POLine, mode: str) -> Decimal:
    """'total_gw' → line.gross_weight; 'per_carton_gw' → gross_weight / packages (packages>0 else gross_weight);
    quantized to 0.01 ROUND_HALF_UP."""
```

Example from the docx: Qty Ordered 167 AS with prepack 6 EA, Excel 1002 PCS / 167 CTN → units 6, qpc 1, cartons 167. Without prepack: Ordered 1002 → qpc 6, cartons 167. Sample file row: 510 / 85 → units 6; if the web shows a prepack of 6 → qpc 1, cartons 85.

### 3.12 `data/planner.py`

```python
@dataclass(slots=True)
class PlanOptions:
    grouping: str                 # "per_file" | "per_master_po"
    dry_run: bool
    weight_mode: str

def build_plan(lines: list[POLine], factory: FactoryAddress, opts: PlanOptions,
               source_file: str, sheet_name: str, fingerprint: str, run_id: str | None = None) -> RunPlan:
    """Reject empty lines (PlanError). Duplicate po_line_id → PlanError('PO line trùng lặp: …').
    per_file: one ShipmentPlan with all lines (order preserved).
    per_master_po: one ShipmentPlan per distinct master_po in order of first appearance.
    PlannedLine.weight_kg = weight_for_line(line, opts.weight_mode); weight_text = format_weight(...).
    label = f"Lô {index} ({', '.join(master_pos)})"."""
def plan_summary_rows(plan: RunPlan) -> list[dict]:
    """Flat rows for the review table: shipment_index, po_line_id, master_po, line, description, packages, quantity,
    units_per_carton (quantity/packages or '?'), weight_text, flags_vi (joined)."""
```

### 3.13 `data/results.py`

`runs/<run_id>/results.csv` (UTF-8 with BOM so Excel opens it correctly), header:

```
run_id,excel_file,shipment_index,web_shipment_id,asn_shipment_id,po_line_id,master_po,line,shipping_date,qty_per_carton,cartons_per_site,weight_kg,status,flags
```

```python
class ResultsWriter:
    def __init__(self, run_id: str)                       # creates run_dir(run_id)
    @property
    def csv_path(self) -> Path
    def write(self, plan: RunPlan) -> Path                 # rewrites the whole CSV from the current plan state (idempotent)
    def write_json(self, result: RunResult) -> Path        # run_dir/run.json (dataclasses → dict, Decimal → str, date → iso)
def load_run_history(limit: int = 50) -> list[dict]        # newest first, from run.json files (for the GUI history tab)
```

### 3.14 `data/excel_writeback.py`

```python
def write_back(plan: RunPlan, det: HeaderDetection) -> Path:
    """Copy source Excel to '<stem>_ASN.xlsx' next to the source (overwrite). On the mapped sheet, write header
    'ASN' into the header row (max(header_rows)) at column max_col+1 and, for each PlannedLine with a web_shipment_id,
    the id into that row. Returns the new path. Never modifies the original."""
```

### 3.15 `core/logging_setup.py`

```python
def setup_logging(level: int = logging.INFO) -> Path:
    """RotatingFileHandler logs_dir()/edi_assistant.log (2 MB × 5), format '%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s'.
    Returns the log path. Idempotent."""
```

### 3.16 WP-A public facade (`data/__init__.py`)

Re-exports: `load_grid, list_sheets, detect_header, suggest_mapping, apply_template_to_detection, validate_mapping, extract_rows, TemplateStore, Template, FactoryStore, build_plan, PlanOptions, plan_summary_rows, ResultsWriter, write_back`.

### 3.17 Typical WP-C call sequence (for reference)

```python
grid = load_grid(path, sheet)                    # sheet chosen in GUI (default: first sheet with a detectable header)
det = detect_header(grid)
match = TemplateStore().find(det)
mapping = match.template.to_mapping() if match else suggest_mapping(det)[0]
mapping = apply_template_to_detection(match.template, det) if match else mapping
# ... user confirms in MappingDialog ...
validate_mapping(mapping)
rx = extract_rows(grid, det, mapping)
factory, score = FactoryStore().suggest(rx.company_text)
plan = build_plan(rx.lines, factory, PlanOptions(cfg.flow.grouping, cfg.flow.dry_run, cfg.flow.weight_mode), str(path), sheet, fingerprint)
```

---
## 4. WP-B — automation (`edi_assistant.automation`)

Real-site facts come from `docs/EDI_REAL_STRUCTURE.md` (read it in full before implementing). Where that file says "not inspected", candidates are screenshot-based and marked `verified: false`.

### 4.1 Threading model — `AutomationWorker` (decision and justification)

- One `threading.Thread(name="edi-automation", daemon=True)` is started at app start and lives until app exit. It is the **only** thread that touches `sync_playwright()`, `Browser`, `BrowserContext`, `Page`, `Locator`. Playwright's sync API runs a private asyncio loop driven by greenlets inside the calling thread; its objects raise if used from another thread, and a `QThread` would add nothing but a Qt dependency to a package that must run under plain pytest. The worker therefore has no Qt imports.
- Commands arrive through `queue.Queue[Command]`. The browser is launched lazily on the first command that needs it and stays open across runs (so the user's login session persists in memory and on disk).
- Blocking user interaction: `FlowContext.ask_user(NeedsUser) -> UserResponse` emits the event and blocks on a `queue.Queue` dedicated to that `request_id` (with a 0.5 s poll so abort can interrupt). The GUI thread calls `worker.respond(UserResponse)`.
- Abort: `worker.request_abort()` sets `threading.Event`; `SafeActions` checks it before every action and `ask_user` checks it every poll; either raises `UserAbortError`.
- Playwright's `sync_playwright().start()` is called **inside** the worker thread, never in the GUI thread.

### 4.2 `automation/session.py`

```python
class BrowserSession:
    def __init__(self, cfg: BrowserConfig, site: SiteConfig, profile_dir: Path, sink: EventSink, log: logging.Logger)
    def open(self) -> None:
        """sync_playwright().start(); launch_persistent_context(user_data_dir=profile_dir, channel=cfg.channel,
        headless=cfg.headless, slow_mo=cfg.slow_mo_ms, viewport={...}, accept_downloads=True, args=["--disable-blink-features=AutomationControlled"]).
        If channel launch fails with 'Executable doesn't exist' / 'channel' error → retry with channel=None (bundled chromium);
        if that fails too → BrowserLaunchError(message_vi='Không tìm thấy trình duyệt Edge/Chromium. Hãy dùng nút "Cài trình duyệt".').
        Env PLAYWRIGHT_BROWSERS_PATH is set by WP-C before the worker starts (paths.playwright_browsers_dir()); the session does not set it.
        After launch: self.context.set_default_timeout(cfg.default_timeout_ms); install route block '**/asn.do*' (abort);
        self.page = context.pages[0] or context.new_page(); context.on('page', self._on_new_page); install DialogPolicy on every page."""
    def close(self) -> None
    @property
    def is_open(self) -> bool
    @property
    def page(self) -> Page                 # the "current" page (last opened popup wins until it closes; then back to main)
    def goto(self, path_or_url: str, wait: str = "domcontentloaded") -> None
        # relative path → urljoin(site.effective_base_url(), path); wraps playwright errors in NavigationError
    def title(self) -> str
    def url(self) -> str
    def is_login_page(self) -> bool        # "-- Login" in title or page.locator("input[type=password]").count() > 0
    def screenshot_jpeg(self, path: Path | None = None, quality: int = 55) -> bytes
        # page.screenshot(type='jpeg', quality=quality, full_page=False, scale='css'); also written to path when given
```

Popup handling: `_on_new_page(page)` registers the page as current, installs the dialog policy, and on `page.on("close")` reverts to the previous page. Steps always use `ctx.page` (property) so a popup becomes the active page automatically.

### 4.3 Selectors — `automation/selectors.yaml`, `automation/selectors.py`

#### Candidate schema

```yaml
version: 1
keys:
  <key>:
    description: "<English description shown to AI and in calibrate dialog>"
    page: "<page id, informational: login|inbox|po_detail|shipment|pos|carton|weight>"
    verified: true|false            # true = confirmed on the real site
    candidates:
      - kind: css        css: "#txtWebShipmentId"
      - kind: role       role: "button"  name: "Save"  exact: true
      - kind: label      text: "Shipping Date"  exact: false
      - kind: text       text: "Create New Shipment"  exact: false
      - kind: placeholder text: "mm/dd/yyyy"
      - kind: xpath      xpath: "//tr[.//a[normalize-space()='{po}']]"
      # optional modifiers on any candidate:
      #   within: "<other key>"          scope: resolve that key first (with the same vars) and search inside it
      #   has_text: "{po}"               Playwright locator(has_text=...)
      #   nth: 0                         pick the n-th match (default: must be unique or first visible; see resolver)
      #   note: "..."                    free text
```

Template variables substituted with `str.format_map` on `css/xpath/text/name/has_text`: `{po}` (9-digit PO line id), `{master_po}`, `{line}` (int, e.g. `1`), `{line2}` (`01`), `{item_label}` (`PO5803674LN1`), `{site_no}`, `{shipment_id}`, `{row_key}` (derived numeric id, §4.4), `{vendor}` (SiteConfig.vendor_profile_name). Unknown placeholders raise `ValueError` at load time (validated by `SelectorStore.validate()`).

```python
@dataclass(slots=True)
class SelectorCandidate:
    kind: str; css: str = ""; xpath: str = ""; text: str = ""; role: str = ""; name: str = ""
    exact: bool = False; within: str = ""; has_text: str = ""; nth: int | None = None
    source: str = "bundled"       # "bundled" | "learned" | "ai"
    note: str = ""
    def describe(self) -> str     # e.g. "css=#txtWebShipmentId" / "role=button[name='Save']"
    def to_dict(self) -> dict ; @classmethod def from_dict(cls, d: dict) -> SelectorCandidate

@dataclass(slots=True)
class SelectorKey:
    key: str; description: str; page: str; verified: bool; candidates: list[SelectorCandidate]

class SelectorStore:
    def __init__(self, bundled_path: Path, learned_path: Path)
    def load(self) -> None                       # reads both; learned file may be missing
    def validate(self) -> list[str]              # placeholder/kind errors
    def keys(self) -> list[SelectorKey]          # merged view
    def get(self, key: str) -> SelectorKey       # KeyError if unknown
    def candidates(self, key: str) -> list[SelectorCandidate]
        # learned (newest first) + bundled, de-duplicated by describe()
    def add_learned(self, key: str, cand: SelectorCandidate, source: str) -> None
        # prepends to learned file: keys[key].candidates (with source, learned_at ISO, site_base_url); atomic write
    def remove_learned(self, key: str, describe: str) -> None
    def mark_verified(self, key: str) -> None    # in learned file: keys[key].verified = true (overrides bundled flag)
```

Learned file `selectors.learned.yaml`:
```yaml
version: 1
keys:
  carton.save_button:
    verified: true
    candidates:
      - {kind: css, css: "input[name='SaveCarton']", source: learned, learned_at: "2026-10-20T09:12:00", site: "https://edi.coat.com/vms-gateway/"}
```

Merge rule: for each key, effective `verified = learned.verified if present else bundled.verified`; candidates = learned then bundled. Bundled file is read-only (inside the frozen app).

#### Resolver

```python
class SelectorResolver:
    def __init__(self, store: SelectorStore, log: logging.Logger)
    def build(self, page: Page | Locator, cand: SelectorCandidate, vars: dict[str, str]) -> Locator:
        """kind css → page.locator(css); xpath → page.locator('xpath=' + xpath); text → page.get_by_text(text, exact);
        role → page.get_by_role(role, name=name or None, exact=exact); label → page.get_by_label(text, exact);
        placeholder → page.get_by_placeholder(text). Then .filter(has_text=...) if has_text; .nth(n) if nth is not None.
        `within` → root = self.resolve(page, within, vars); build on root."""
    def resolve(self, page: Page, key: str, vars: dict[str, str] | None = None,
                timeout_ms: int = 4000, require_visible: bool = True) -> tuple[Locator, SelectorCandidate]:
        """Iterate candidates. For each: loc = build(...); deadline per candidate = min(1500, remaining budget);
        poll every 150 ms: n = loc.count(); if n == 0 continue polling; if n >= 1 pick loc (nth given) or
        loc.first when n > 1 (log WARNING 'ambiguous'); if require_visible and not is_visible() keep polling.
        First success → return (locator, cand). Nothing within total timeout → ElementNotFoundError(key=key, tried=[c.describe()...]).
        Total budget = timeout_ms (defaults 4000; steps pass larger values when a navigation is expected)."""
    def try_resolve(self, page, key, vars=None, timeout_ms=1500) -> Locator | None   # no raise
    def exists(self, page, key, vars=None, timeout_ms=1500) -> bool
```

### 4.4 Row-keyed controls — `RowKeyExtractor` (in `selectors.py`)

Real pages key per-row controls by an internal numeric id: Selected Purchase Orders → `complete_shipment_N`, `pack_code_N`, `PO-N`; weight page → `editedSiteWgtquM`, `editedSiteWgtumM`. The 9-digit PO is only visible as row text.

```python
ROW_KEY_PATTERNS = {
  "pos":    re.compile(r"^(?:complete_shipment_|pack_code_|web_sh_packing_type_id_|PO-)(\d+)$"),
  "weight": re.compile(r"^editedSiteWgt(?:qu|um)(\d+)$"),
}
def extract_row_key(row: Locator, page_kind: str) -> str:
    """row.evaluate(JS) returns the list of name/id attributes of input/select elements inside the row;
    first attribute matching ROW_KEY_PATTERNS[page_kind] → group(1). Raise ElementNotFoundError(key=f'{page_kind}.row_key') if none."""
```

Steps use it as: `row = resolve('pos.selected_row', {'po': po})` → `row_key = extract_row_key(row, 'pos')` → `resolve('pos.row_complete_partial_select', {'po': po, 'row_key': row_key})`.

### 4.5 Initial `selectors.yaml` (complete key list; bundled file must contain exactly these keys)

Notation below: `V` verified on the real site, `U` unverified (screenshot-based). Candidates are in priority order. Where a CSS id is listed first it comes from the real DOM.

```yaml
version: 1
keys:
  # ---------- login / profile (V) ----------
  login.password_input:            {page: login, verified: true, description: "Password box on login page (NEVER filled; used only for detection)",
    candidates: [{kind: css, css: "input[type='password']"}]}
  login.profile_vendor_link:       {page: login, verified: true, description: "Vendor name link on Select Profile page",
    candidates: [{kind: role, role: link, name: "{vendor}", exact: true}, {kind: text, text: "{vendor}", exact: true}]}
  login.edi_gateway_button:        {page: login, verified: true, description: "'EDI Gateway' button on View Profile page",
    candidates: [{kind: css, css: "input[type='submit'][value='EDI Gateway']"}, {kind: role, role: button, name: "EDI Gateway"}]}

  # ---------- top navigation (V) ----------
  nav.inbox_tab:                   {page: inbox, verified: true, description: "INBOX tab",
    candidates: [{kind: css, css: "a[href*='inbox.do']"}, {kind: role, role: link, name: "INBOX"}, {kind: text, text: "INBOX", exact: true}]}
  nav.shipments_tab:               {page: inbox, verified: true, description: "SHIPMENTS tab (drafts.do)",
    candidates: [{kind: css, css: "a[href*='drafts.do']"}, {kind: role, role: link, name: "SHIPMENTS"}]}

  # ---------- inbox (V) ----------
  inbox.document_id_input:         {page: inbox, verified: true, description: "Document ID search box",
    candidates: [{kind: css, css: "form[name='filterinbox'] input[name='documentID']"}, {kind: css, css: "input[name='documentID']"}, {kind: label, text: "Document ID"}]}
  inbox.search_button:             {page: inbox, verified: true, description: "Search button of inbox filter",
    candidates: [{kind: css, css: "form[name='filterinbox'] input[type='submit'][value='Search']"}, {kind: role, role: button, name: "Search", exact: true}]}
  inbox.results_table:             {page: inbox, verified: true, description: "Inbox results table (contains 'Document ID' header)",
    candidates: [{kind: xpath, xpath: "//table[.//th[contains(normalize-space(),'Document ID')] or .//td[contains(normalize-space(),'Document ID')]]", nth: -1},
                 {kind: css, css: "table:has(tr.odd), table:has(tr.even)"}]}
  inbox.result_row:                {page: inbox, verified: true, description: "Inbox result row whose Document ID link equals {po} (any row, including stricken)",
    candidates: [{kind: xpath, xpath: "//tr[contains(@class,'odd') or contains(@class,'even')][.//a[contains(@href,'view_order.do')][normalize-space()='{po}']]"},
                 {kind: xpath, xpath: "//tr[.//a[normalize-space()='{po}']]"}]}
  inbox.result_row_active:         {page: inbox, verified: true, description: "Inbox result row for {po} that is NOT replaced (no 'stricken' class, status != REPLACED)",
    candidates: [{kind: xpath, xpath: "//tr[(contains(@class,'odd') or contains(@class,'even')) and not(contains(@class,'stricken'))][.//a[contains(@href,'view_order.do')][normalize-space()='{po}']][not(.//td[normalize-space()='REPLACED'])]"},
                 {kind: xpath, xpath: "//tr[not(contains(@class,'stricken'))][.//a[normalize-space()='{po}']][not(contains(.,'REPLACED'))]"}]}
  inbox.result_link:               {page: inbox, verified: true, description: "Document ID link inside a result row",
    candidates: [{kind: css, css: "a[href*='view_order.do']"}, {kind: role, role: link, name: "{po}", exact: true}]}
  inbox.row_status_cell:           {page: inbox, verified: true, description: "Status cell (6th td) inside a result row",
    candidates: [{kind: css, css: "td:nth-child(6)"}]}

  # ---------- PO detail view_order.do (U) ----------
  po.page_marker:                  {page: po_detail, verified: false, description: "Text that identifies the PO detail page: 'Purchase Order : {po}'",
    candidates: [{kind: text, text: "Purchase Order : {po}"}, {kind: text, text: "{po}", exact: false}]}
  po.create_new_shipment_link:     {page: po_detail, verified: false, description: "'Create New Shipment' link/button on PO detail page",
    candidates: [{kind: role, role: link, name: "Create New Shipment"}, {kind: text, text: "Create New Shipment"},
                 {kind: css, css: "a[href*='new_shipment.do']"}, {kind: role, role: button, name: "Create New Shipment"}]}
  po.pdf_embed:                    {page: po_detail, verified: false, description: "Embedded PDF viewer of the PO (iframe/embed/object)",
    candidates: [{kind: css, css: "iframe[src*='.pdf'], iframe[src*='pdf'], embed[type='application/pdf'], object[type='application/pdf'], iframe"}]}
  po.return_to_list_link:          {page: po_detail, verified: false, description: "'<< Return To Order List' link",
    candidates: [{kind: text, text: "Return To Order List"}, {kind: css, css: "a[href*='inbox.do']"}]}

  # ---------- shipment header new_shipment.do (V) ----------
  ship.form:                       {page: shipment, verified: true, description: "Shipment header form",
    candidates: [{kind: css, css: "form#new_shipment"}, {kind: css, css: "form[name='new_shipment']"}]}
  ship.web_shipment_id:            {page: shipment, verified: true, description: "Web Shipment ID (readonly, filled after Save)",
    candidates: [{kind: css, css: "#txtWebShipmentId"}, {kind: label, text: "Web Shipment ID"}]}
  ship.asn_shipment_id:            {page: shipment, verified: true, description: "ASN Shipment ID",
    candidates: [{kind: css, css: "#txtASNId"}, {kind: label, text: "ASN Shipment ID"}]}
  ship.radio_with_cartons:         {page: shipment, verified: true, description: "Radio 'Shipment With Cartons'",
    candidates: [{kind: css, css: "input[name='CartonRadio'][value='Y']"}, {kind: label, text: "Shipment With Cartons"}]}
  ship.shipping_type:              {page: shipment, verified: true, description: "Shipping Type select (option value 3 = Ship to DC)",
    candidates: [{kind: css, css: "#OptShippingType"}, {kind: label, text: "Shipping Type"}]}
  ship.shipping_date:              {page: shipment, verified: true, description: "Shipping Date text box MM/DD/YYYY",
    candidates: [{kind: css, css: "#txtShippingDate"}, {kind: label, text: "Shipping Date"}]}
  ship.transportation_method:      {page: shipment, verified: true, description: "Transportation Method select (O = Containerized Ocean)",
    candidates: [{kind: css, css: "#OptTransMethod"}, {kind: label, text: "Transportation Method"}]}
  ship.scac_code:                  {page: shipment, verified: true, description: "SCAC Code select (MAEU = MAEU-MAERSK)",
    candidates: [{kind: css, css: "#OptSCACCode"}, {kind: label, text: "SCAC Code"}]}
  ship.carrier:                    {page: shipment, verified: true, description: "Carrier (readonly, auto-filled)",
    candidates: [{kind: css, css: "input[name='txtcarrier']"}, {kind: label, text: "Carrier"}]}
  ship.bill_of_lading:             {page: shipment, verified: true, description: "Bill Of Lading",
    candidates: [{kind: css, css: "input[name='txtBillLading']"}, {kind: label, text: "Bill Of Lading"}]}
  ship.pro_number:                 {page: shipment, verified: true, description: "PRO Number",
    candidates: [{kind: css, css: "input[name='txtPRONumber']"}, {kind: label, text: "PRO Number"}]}
  ship.from_site_no:               {page: shipment, verified: true, description: "FROM Site No select",
    candidates: [{kind: css, css: "select[name='OptSiteNO']"}]}
  ship.from_name:                  {page: shipment, verified: true, description: "FROM Name",            candidates: [{kind: css, css: "#txtFromName"}, {kind: css, css: "input[name='txtFromName']"}]}
  ship.from_address1:              {page: shipment, verified: true, description: "FROM Address 1",       candidates: [{kind: css, css: "#txtFromAddress1"}, {kind: css, css: "input[name='txtFromAddress1']"}]}
  ship.from_address2:              {page: shipment, verified: true, description: "FROM Address 2",       candidates: [{kind: css, css: "input[name='txtFromAddress2']"}]}
  ship.from_city:                  {page: shipment, verified: true, description: "FROM City",            candidates: [{kind: css, css: "#txtFromCity"}, {kind: css, css: "input[name='txtFromCity']"}]}
  ship.from_state:                 {page: shipment, verified: true, description: "FROM State",           candidates: [{kind: css, css: "#txtFromState"}, {kind: css, css: "input[name='txtFromState']"}]}
  ship.from_zip:                   {page: shipment, verified: true, description: "FROM Zip",             candidates: [{kind: css, css: "#txtFromZip"}, {kind: css, css: "input[name='txtFromZip']"}]}
  ship.from_country:               {page: shipment, verified: true, description: "FROM Country select (US/CA/CN only; others via 'More..')",
    candidates: [{kind: css, css: "#txtFromCountry"}, {kind: css, css: "select[name='txtFromCountry']"}]}
  ship.from_country_more_link:     {page: shipment, verified: true, description: "'More..' link next to FROM Country",
    candidates: [{kind: xpath, xpath: "//select[@id='txtFromCountry']/following::a[normalize-space()='More..'][1]"}, {kind: text, text: "More..", exact: true, nth: 1}]}
  ship.to_site_no:                 {page: shipment, verified: true, description: "TO Site No (readonly)",
    candidates: [{kind: css, css: "input[name='optToSiteNo']"}]}
  ship.to_address1:                {page: shipment, verified: true, description: "TO Address 1 (readonly)", candidates: [{kind: css, css: "input[name='txtToAddress1']"}]}
  ship.save_button:                {page: shipment, verified: true, description: "Save button of shipment header",
    candidates: [{kind: css, css: "#saveonly"}, {kind: css, css: "input[type='submit'][value='Save']"}, {kind: role, role: button, name: "Save", exact: true}]}
  ship.selected_pos_button:        {page: shipment, verified: true, description: "'Selected Purchase Orders >>' button",
    candidates: [{kind: css, css: "#submit123"}, {kind: css, css: "input[value*='Selected Purchase Orders']"}, {kind: role, role: button, name: "Selected Purchase Orders >>"}]}
  ship.submit_asn_button:          {page: shipment, verified: true, description: "Submit ASN button — existence check only, NEVER clicked",
    candidates: [{kind: css, css: "input[name='btnSubmitASN']"}, {kind: role, role: button, name: "Submit ASN"}]}
  ship.error_text:                 {page: shipment, verified: false, description: "Server-side validation error message area",
    candidates: [{kind: css, css: ".error, .errors, font[color='red'], span[style*='red'], td.errorMessage"}]}

  # ---------- selected purchase orders selected_pos.do (V except search tab) ----------
  pos.form:                        {page: pos, verified: true, description: "Selected POs form", candidates: [{kind: css, css: "form[name='form1']"}]}
  pos.tab_selected:                {page: pos, verified: true, description: "Tab 'Selected Purchase Orders'",
    candidates: [{kind: role, role: link, name: "Selected Purchase Orders"}, {kind: text, text: "Selected Purchase Orders", exact: true}]}
  pos.tab_search:                  {page: pos, verified: false, description: "Tab 'Search Purchase Orders'",
    candidates: [{kind: role, role: link, name: "Search Purchase Orders"}, {kind: text, text: "Search Purchase Orders", exact: true},
                 {kind: css, css: "a[href*='search_pos'], a[href*='searchPurchase'], a[href*='tab=search']"}]}
  pos.search_po_input:             {page: pos, verified: false, description: "'Purchase Order No' filter box on Search tab",
    candidates: [{kind: label, text: "Purchase Order No"}, {kind: css, css: "input[name*='purchaseOrderNo' i], input[name*='poNo' i], input[name*='orderNo' i]"},
                 {kind: xpath, xpath: "//td[contains(normalize-space(),'Purchase Order No')]/following::input[@type='text'][1]"}]}
  pos.search_button:               {page: pos, verified: false, description: "Search button on Search tab",
    candidates: [{kind: css, css: "input[type='submit'][value='Search'], input[type='button'][value='Search']"}, {kind: role, role: button, name: "Search", exact: true}]}
  pos.search_row:                  {page: pos, verified: false, description: "Search result row containing PO {po}",
    candidates: [{kind: xpath, xpath: "//tr[.//a[normalize-space()='{po}'] or .//td[normalize-space()='{po}']][.//input[@type='checkbox']]"}]}
  pos.search_row_checkbox:         {page: pos, verified: false, description: "Checkbox inside a search result row", candidates: [{kind: css, css: "input[type='checkbox']"}]}
  pos.add_selected_button:         {page: pos, verified: false, description: "'Add Selected' button on Search tab",
    candidates: [{kind: css, css: "input[value='Add Selected']"}, {kind: role, role: button, name: "Add Selected", exact: true}]}
  pos.selected_row:                {page: pos, verified: true, description: "Row of the Selected tab for PO {po} (contains complete_shipment_N select)",
    candidates: [{kind: xpath, xpath: "//tr[.//a[normalize-space()='{po}']][.//select[starts-with(@name,'complete_shipment_')]]"},
                 {kind: xpath, xpath: "//tr[.//a[normalize-space()='{po}'] or .//td[normalize-space()='{po}']][.//select]"}]}
  pos.row_status_text:             {page: pos, verified: true, description: "Status text cell in a selected row (Available/Replaced)", candidates: [{kind: css, css: "td:nth-child(3)"}]}
  pos.row_complete_partial_select: {page: pos, verified: true, description: "Complete/Partial select of row {row_key}",
    candidates: [{kind: css, css: "select[name='complete_shipment_{row_key}']"}, {kind: css, css: "select[name^='complete_shipment_']", within: pos.selected_row}]}
  pos.row_packaging_select:        {page: pos, verified: true, description: "Packaging Code select of row {row_key} (CTN25 default)",
    candidates: [{kind: css, css: "select[name='pack_code_{row_key}']"}, {kind: css, css: "select[name^='pack_code_']", within: pos.selected_row}]}
  pos.row_save_button:             {page: pos, verified: true, description: "Row 'Save' button (saveCarton)",
    candidates: [{kind: css, css: "input[onclick*=\"saveCarton('saveCarton', {row_key}\"]"}, {kind: css, css: "input[value='Save']", within: pos.selected_row}]}
  pos.row_create_carton_button:    {page: pos, verified: true, description: "Row 'Create Carton' button (insertCarton)",
    candidates: [{kind: css, css: "input[onclick*=\"insertCarton('insertCarton', {row_key}\"]"}, {kind: css, css: "input[value='Create Carton']", within: pos.selected_row}]}
  pos.view_detail_button:          {page: pos, verified: true, description: "'View Shipment Orders Detail' button",
    candidates: [{kind: css, css: "input[name='poSiteShipment']"}, {kind: role, role: button, name: "View Shipment Orders Detail"}]}
  pos.back_to_header_button:       {page: pos, verified: true, description: "'<< Back To Shipment Header'",
    candidates: [{kind: css, css: "input[value*='Back To Shipment Header']"}, {kind: role, role: button, name: "<< Back To Shipment Header"}]}
  pos.validate_button:             {page: pos, verified: true, description: "'Validate Shipment' (only if flow.click_validate)",
    candidates: [{kind: css, css: "input[name='validateShipment']"}]}
  pos.page_marker:                 {page: pos, verified: true, description: "Breadcrumb 'Web Shipment ID: NNN >> Selecting Purchase Orders'",
    candidates: [{kind: text, text: "Selecting Purchase Orders"}]}

  # ---------- carton page (U — screenshots image10–16) ----------
  carton.page_marker:              {page: carton, verified: false, description: "Heading 'Create Carton Definition'",
    candidates: [{kind: text, text: "Create Carton Definition"}, {kind: text, text: "Carton Definition"}]}
  carton.carton_name_input:        {page: carton, verified: false, description: "Carton Name text box",
    candidates: [{kind: label, text: "Carton Name"}, {kind: css, css: "input[name*='carton_definition_name' i], input[name*='cartonName' i]"}]}
  carton.packaging_code_select:    {page: carton, verified: false, description: "Packaging Code select next to Carton Name ('Physical Container - Carton')",
    candidates: [{kind: xpath, xpath: "//*[normalize-space()='Packaging Code']/following::select[1]"}, {kind: label, text: "Packaging Code"},
                 {kind: css, css: "select[name*='packaging_code' i], select[name*='pack_code' i]"}]}
  carton.tab_items_search:         {page: carton, verified: false, description: "Tab 'Search Items'",
    candidates: [{kind: role, role: link, name: "Search Items"}, {kind: text, text: "Search Items", exact: true}]}
  carton.tab_items_selected:       {page: carton, verified: false, description: "Tab 'Selected Items'",
    candidates: [{kind: role, role: link, name: "Selected Items"}, {kind: text, text: "Selected Items", exact: true}]}
  carton.items_section:            {page: carton, verified: false, description: "Container of the items table (contains header 'Sku/Upc/Prepack' or 'SKU No')",
    candidates: [{kind: xpath, xpath: "//table[.//th[contains(.,'Sku') or contains(.,'SKU')] or .//td[contains(.,'Sku/Upc/Prepack') or contains(.,'SKU No')]][last()]"}]}
  carton.items_search_row:         {page: carton, verified: false, description: "Search Items result row with a checkbox (PO group row '{item_label}' or first row)",
    candidates: [{kind: xpath, xpath: "//tr[.//input[@type='checkbox']][contains(.,'{item_label}')]"}, {kind: xpath, xpath: "//tr[.//input[@type='checkbox']][.//td[contains(.,'PO{master_po}')]]"},
                 {kind: xpath, xpath: "(//table[.//th[contains(.,'SKU')] or .//td[contains(.,'SKU No')]]//tr[.//input[@type='checkbox']])[1]"}]}
  carton.items_add_selected:       {page: carton, verified: false, description: "'Add Selected' button under Search Items table",
    candidates: [{kind: xpath, xpath: "(//table[.//*[contains(.,'SKU')]]/following::input[@value='Add Selected'])[1]"}, {kind: css, css: "input[value='Add Selected']", nth: 0}]}
  carton.item_po_row:              {page: carton, verified: false, description: "Selected Items row for '{item_label}' (has Qty Per Carton input)",
    candidates: [{kind: xpath, xpath: "//tr[.//input[@type='text']][contains(.,'{item_label}')]"}, {kind: xpath, xpath: "//tr[.//input[@type='text']][contains(.,'PO{master_po}')]"}]}
  carton.item_qty_per_carton_input: {page: carton, verified: false, description: "Qty Per Carton input inside item row",
    candidates: [{kind: css, css: "input[type='text']", within: carton.item_po_row}]}
  carton.item_qty_ordered_cell:    {page: carton, verified: false, description: "Qty Ordered cell inside item row (td immediately before the input's td)",
    candidates: [{kind: xpath, xpath: ".//td[.//input[@type='text']]/preceding-sibling::td[1]", within: carton.item_po_row}]}
  carton.item_um_cell:             {page: carton, verified: false, description: "Unit of Measure cell inside item row (AS/EA, last td)",
    candidates: [{kind: xpath, xpath: ".//td[last()]", within: carton.item_po_row}]}
  carton.item_prepack_row:         {page: carton, verified: false, description: "Prepack sub-row directly after the item row (no checkbox, no input, UM EA)",
    candidates: [{kind: xpath, xpath: "//tr[.//input[@type='text']][contains(.,'{item_label}')]/following-sibling::tr[1][not(.//input)][contains(.,'EA')]"}]}
  carton.tab_sites_search:         {page: carton, verified: false, description: "Tab 'Search Sites'",
    candidates: [{kind: role, role: link, name: "Search Sites"}, {kind: text, text: "Search Sites", exact: true}]}
  carton.sites_search_row:         {page: carton, verified: false, description: "Search Sites result row with checkbox (site {site_no} or first)",
    candidates: [{kind: xpath, xpath: "//tr[.//input[@type='checkbox']][.//td[normalize-space()='{site_no}']]"},
                 {kind: xpath, xpath: "(//table[.//*[contains(.,'Zip Code')]]//tr[.//input[@type='checkbox']])[1]"}]}
  carton.sites_add_selected:       {page: carton, verified: false, description: "'Add Selected' button under Search Sites table",
    candidates: [{kind: xpath, xpath: "(//table[.//*[contains(.,'Zip Code')]]/following::input[@value='Add Selected'])[1]"}, {kind: css, css: "input[value='Add Selected']", nth: -1}]}
  carton.site_row:                 {page: carton, verified: false, description: "Selected Sites row (has Cartons Per Site input)",
    candidates: [{kind: xpath, xpath: "//tr[.//input[@type='text']][.//a[normalize-space()='{site_no}'] or .//td[normalize-space()='{site_no}']]"},
                 {kind: xpath, xpath: "(//table[.//*[contains(.,'Cartons')]]//tr[.//input[@type='text']])[1]"}]}
  carton.site_cartons_per_site_input: {page: carton, verified: false, description: "Cartons Per Site input inside site row",
    candidates: [{kind: css, css: "input[type='text']", within: carton.site_row}]}
  carton.save_button:              {page: carton, verified: false, description: "Bottom 'Save' button of carton page",
    candidates: [{kind: xpath, xpath: "(//input[@type='button' or @type='submit'][@value='Save'])[last()]"}, {kind: role, role: button, name: "Save", exact: true, nth: -1}]}
  carton.back_to_po_button:        {page: carton, verified: false, description: "'<< Back to Purchase Order'",
    candidates: [{kind: css, css: "input[value*='Back to Purchase Order']"}, {kind: role, role: button, name: "<< Back to Purchase Order"}]}

  # ---------- weight page po_site_shipment.do (V) ----------
  weight.form:                     {page: weight, verified: true, description: "Weight page form", candidates: [{kind: css, css: "form[name='po_site_shipment']"}]}
  weight.orderperpage_select:      {page: weight, verified: true, description: "Orders per page select (set to All = 100000)",
    candidates: [{kind: css, css: "form[name='po_site_shipment'] select[name='orderperpage']"}, {kind: css, css: "select[name='orderperpage']"}]}
  weight.row:                      {page: weight, verified: true, description: "Row for PO {po} containing weight input",
    candidates: [{kind: xpath, xpath: "//tr[.//a[normalize-space()='{po}'] or .//td[normalize-space()='{po}']][.//input[starts-with(@name,'editedSiteWgtqu')]]"}]}
  weight.row_weight_input:         {page: weight, verified: true, description: "WEIGHT input for row {row_key}",
    candidates: [{kind: css, css: "input[name='editedSiteWgtqu{row_key}']"}, {kind: css, css: "input[name^='editedSiteWgtqu']", within: weight.row}]}
  weight.row_um_select:            {page: weight, verified: true, description: "WEIGHT UM select for row {row_key}",
    candidates: [{kind: css, css: "select[name='editedSiteWgtum{row_key}']"}, {kind: css, css: "select[name^='editedSiteWgtum']", within: weight.row}]}
  weight.save_button:              {page: weight, verified: true, description: "Save (SaveCarton2)",
    candidates: [{kind: css, css: "input[name='SaveCarton2']"}, {kind: role, role: button, name: "Save", exact: true}]}
  weight.back_button:              {page: weight, verified: true, description: "'<< Back To Select Purchase Order'",
    candidates: [{kind: css, css: "input[name='backtoorders']"}]}
```

`nth: -1` means `.last`. The resolver maps `nth == -1` to `locator.last`.

### 4.6 `automation/actions.py` — `SafeActions`

```python
FORBIDDEN_NAME_IDS = {"btnSubmitASN", "cancelShipment", "btnCancel"}
FORBIDDEN_TEXT_RE = re.compile(r"submit", re.I)

class SafeActions:
    def __init__(self, session: BrowserSession, resolver: SelectorResolver, abort_event: threading.Event,
                 sink: EventSink, log: logging.Logger, flow_cfg: FlowConfig)
    def _check_abort(self) -> None                     # raises UserAbortError
    def _guard_click(self, loc: Locator) -> None:
        """attrs = loc.evaluate('el => ({name: el.name||"", id: el.id||"", value: el.value||"", text: (el.innerText||el.textContent||"").trim(), onclick: (el.getAttribute("onclick")||"")})')
        if attrs.name/id in FORBIDDEN_NAME_IDS or FORBIDDEN_TEXT_RE matches value/text or 'asn.do' in onclick → ForbiddenActionError
        if name == 'validateShipment' and not flow_cfg.click_validate → ForbiddenActionError"""
    def click(self, key: str, vars: dict | None = None, *, timeout_ms: int = 4000, expect_navigation: bool = False) -> None
        # resolve → _guard_click → loc.scroll_into_view_if_needed() → loc.click(); if expect_navigation: page.wait_for_load_state('domcontentloaded')
    def click_locator(self, loc: Locator, *, expect_navigation: bool = False) -> None      # same guards, pre-resolved
    def fill(self, key: str, value: str, vars: dict | None = None, *, dispatch_change: bool = False) -> None
        # loc.fill(value); if dispatch_change: loc.dispatch_event('change')
    def fill_locator(self, loc: Locator, value: str, *, dispatch_change: bool = False) -> None
    def select(self, key: str, *, value: str | None = None, label: str | None = None, label_prefix: str | None = None,
               label_contains: str | None = None, vars: dict | None = None) -> str:
        """Order: value match → exact label → option whose text startswith label_prefix (case-insensitive) → contains.
        Uses loc.locator('option').all_text_contents()/values; select_option(value=...) ; returns chosen option text.
        Raises DataMismatchError(message_vi='Không tìm thấy lựa chọn "{x}" trong danh sách {key}') with ctx options=[...]."""
    def select_locator(self, loc: Locator, **same) -> str
    def check(self, key: str, vars=None) -> None       # loc.check()
    def read_value(self, key: str, vars=None, timeout_ms: int = 4000) -> str    # input_value() for inputs/selects, inner_text() otherwise
    def read_text(self, key: str, vars=None, timeout_ms: int = 4000) -> str
    def exists(self, key: str, vars=None, timeout_ms: int = 1500) -> bool
    def wait_title_contains(self, text: str, timeout_ms: int) -> bool
    def wait_url_contains(self, text: str, timeout_ms: int) -> bool
    def body_text(self) -> str                          # page.locator('body').inner_text()
```

Every action logs `LogEvent(DEBUG, f"{verb} {key} via {cand.describe()}")`.

### 4.7 `automation/dialogs.py`

```python
class DialogPolicy:
    def __init__(self, log, sink)
    def install(self, page: Page) -> None            # page.on("dialog", self._handle)
    def expect_accept(self, pattern: str, timeout_s: float = 20) -> None
        # arm: the next confirm whose message matches pattern (re.I) is accepted; expectation expires after timeout_s
    def pop_last(self) -> tuple[str, str, bool] | None   # (type, message, accepted) of last dialog
    def _handle(self, dialog: Dialog) -> None:
        """alert/beforeunload → accept (log message). prompt → dismiss.
        confirm: if ALWAYS_DISMISS_RE.search(message) → dismiss + log WARNING;
                 elif armed and pattern matches → accept, disarm;
                 else dismiss + log WARNING 'unexpected confirm'. Record in history (max 50)."""
ALWAYS_DISMISS_RE = re.compile(r"submit|transmit|cancel (this|the) shipment|delete|remove", re.I)
```

Flow usage: `ctx.dialogs.expect_accept(r"do you want to add the selected")` immediately before clicking an "Add Selected" button.

### 4.8 `automation/dom_snapshot.py`

```python
@dataclass(slots=True)
class PageSnapshot:
    url: str; title: str; aria: str; dom: str; screenshot_path: str; screenshot_jpeg: bytes

def capture(session: BrowserSession, run_dir: Path, tag: str, with_image: bool = True) -> PageSnapshot:
    """aria = page.locator('body').aria_snapshot() truncated to 12_000 chars (Playwright >= 1.49).
    dom = page.evaluate(SIMPLIFY_JS) truncated to 12_000 chars.
    screenshot → run_dir/'shots'/f'{time:%H%M%S}_{tag}.jpg' (quality 55). Never raises; on failure fields are '' / b''."""
SIMPLIFY_JS = """() => { /* walk document; for each of a,button,input,select,textarea,label,th,h1,h2,h3,[role],tr (only tr containing input/select/a)
 emit one line: '<tag id=".." name=".." type=".." value=".." role=".." text="first 60 chars">' with depth indentation;
 skip hidden (offsetParent === null && tag !== 'option'); mask value of input[type=password] and any text matching /\\S+@\\S+/ as '[redacted]';
 cap 2000 lines */ }"""
```

Redaction: password values and e-mail addresses are masked in `dom`; `aria` is passed through `re.sub(r"\S+@\S+", "[redacted]", aria)`. Screenshots are not altered (they can contain the company name; acceptable).

### 4.9 `automation/healing.py`

```python
class Healer:
    def __init__(self, advisor: VisionAdvisor | None, store: SelectorStore, resolver: SelectorResolver,
                 max_calls: int, vision: bool, sink: EventSink, log)
    calls_used: int
    def can_call(self) -> bool                           # advisor is not None and calls_used < max_calls
    def heal_locator(self, page: Page, key: str, vars: dict, snap: PageSnapshot) -> Locator | None:
        """if not can_call(): return None. Build LocatorRequest (screenshot only if vision). calls_used += 1.
        proposal = advisor.propose_locator(req) (catch AiError → log, return None).
        For each candidate dict (max 3): cand = SelectorCandidate.from_dict(d); cand.source='ai'; loc = resolver.build(page, cand, vars);
        if loc.count() >= 1 and loc.first.is_visible(): store.add_learned(key, cand, 'ai'); sink(LogEvent(INFO,'learned selector ...')); return loc.first
        return None."""
    def explain(self, step_id: str, title_vi: str, err: Exception, snap: PageSnapshot) -> Explanation | None
        # budget-checked like above; returns None when unavailable
    def read_dates(self, snap: PageSnapshot) -> DateWindow | None
        # advisor.read_fields(fields=['early_ship_date','late_ship_date'], hint="PO document; labels 'Early Ship Date' and 'Late Ship Date' with values like 09-MAR-26")
        # parse each value with core.dates.parse_date_token
```

Budget counting is per run (`FlowRunner` constructs one `Healer` per run and copies `calls_used` to `RunResult.ai_calls_used`).

### 4.10 `automation/po_dates.py` — ship-date ladder

```python
def read_po_dates(ctx: "FlowContext", po_line_id: str) -> tuple[DateWindow, str]:
    """Returns (window, source) where source ∈ {'dom','pdf','ai','user'}.
    Rung 1 DOM: text = ctx.actions.body_text(); w = parse_ship_dates(text) → ('dom').
    Rung 2 PDF: loc = resolver.try_resolve(page, 'po.pdf_embed'); src = loc.get_attribute('src') or 'data' attr; also scan
      page.evaluate("[...document.querySelectorAll('a[href],iframe[src],embed[src],object[data]')].map(e=>e.href||e.src||e.data)")
      for URLs containing '.pdf' or 'pdf' or 'Servlet'. For each (max 3): resp = ctx.page.request.get(url) (same cookies);
      if resp.ok and resp.headers.get('content-type','').startswith('application/pdf') or body startswith b'%PDF':
        text = ''.join(p.extract_text() or '' for p in pypdf.PdfReader(io.BytesIO(body)).pages[:3]) → parse_ship_dates → ('pdf').
    Rung 3 AI: snap = capture(...); if ctx.healer.can_call() and vision: w = ctx.healer.read_dates(snap) → ('ai').
    Rung 4 user: resp = ctx.ask_user(NeedsUser(kind='dates_needed', message_vi=f'Không đọc được ngày giao của PO {po}. Hãy xem trang PO trong trình duyệt và nhập Early/Late Ship Date.',
      input_fields=[InputField('early_ship_date','Early Ship Date (vd 09-MAR-26 hoặc 03/09/2026)'), InputField('late_ship_date','Late Ship Date')], options=['continue','abort']))
      parse both with parse_date_token; invalid → ask again (max 3) → PostconditionFailed. Flag dates_manual."""
```

---
### 4.11 Flow — `automation/flow/context.py`, `steps.py`, `runner.py`

#### FlowContext

```python
@dataclass
class FlowContext:
    session: BrowserSession
    actions: SafeActions
    resolver: SelectorResolver
    dialogs: DialogPolicy
    healer: Healer
    config: AppConfig
    plan: RunPlan
    run_dir: Path
    sink: EventSink
    log: logging.Logger
    abort_event: threading.Event
    ask_user: Callable[[NeedsUser], UserResponse]      # provided by the worker
    results: ResultsWriter
    current_shipment: ShipmentPlan | None = None
    current_line: PlannedLine | None = None
    @property
    def page(self) -> Page                               # session.page
    def vars(self, line: PlannedLine | None = None) -> dict[str, str]:
        """{'po','master_po','line','line2','item_label','site_no','shipment_id','vendor'} from current shipment/line."""
    def emit(self, ev: Event) -> None
    def info(self, msg: str) / warn / debug
    def base(self, path: str) -> str                      # urljoin(effective_base_url, path)
```

#### Step base class

```python
class Step:
    id: str                       # "S1.inbox_search"
    title_vi: str
    selector_keys: tuple[str, ...]
    retry_on_fail: bool = True
    def act(self, ctx: FlowContext) -> None: ...        # perform actions
    def check(self, ctx: FlowContext) -> bool: ...      # postcondition, side-effect free, must be cheap (<= 3 s)
```

#### Runner algorithm (`FlowRunner.run(plan) -> RunResult`)

```
emit RunStarted(total_steps = estimated)
S0_EnsureLoggedIn
for shipment in plan.shipments:
    shipment.status = "running"; ctx.current_shipment = shipment
    for master_po in shipment.master_pos:                  # dates once per master PO
        line = first PlannedLine of that master
        run(S1_InboxSearch(line)); run(S2_OpenPODetail(line)); run(S3_ReadDates(line))
    S4_ComputeShipDate (pure; may ask_user on no intersection)
    first = shipment.lines[0]
    if not currently on first master PO's detail page: run(S1(first)); run(S2(first))
    run(S5_CreateNewShipment); run(S6_FillHeaderAndSave)   # dry-run stops inside S6 before Save
    if shipment.status == "dry_run": results.write(plan); continue   # nothing more can be done without a saved shipment
    run(S7_AddPurchaseOrders)                                # all lines
    for line in shipment.lines: run(S8_CreateCarton(line)); run(S8b_SetPartial(line))
    run(S9_EnterWeights)                                     # all lines
    run(S10_FinishShipment)
    shipment.status = "done"; results.write(plan)
emit RunFinished(RunResult)
```

`run(step)`:
```
emit StepStarted
attempt = 0
loop:
    try:
        step.act(ctx)
        if step.check(ctx): emit StepFinished(ok); return
        raise PostconditionFailed(step.id)
    except UserAbortError: raise
    except StepSkipped: emit StepFinished(skipped); return
    except (ElementNotFoundError, PostconditionFailed, DataMismatchError, NavigationError, PlaywrightTimeoutError, PlaywrightError) as e:
        if session.is_login_page(): handle_login(ctx) ; continue         # S0 logic, then retry step
        snap = capture(session, run_dir, step.id)
        if isinstance(e, ElementNotFoundError) and attempt == 0:
            loc = healer.heal_locator(page, e.ctx['key'], vars, snap)     # self-healing (AI, budgeted)
            if loc is not None: attempt += 1; continue                     # re-run step; learned candidate now first
        explanation = healer.explain(step.id, step.title_vi, e, snap)      # may be None
        resp = ctx.ask_user(NeedsUser(kind='step_failed', step_id=step.id, screenshot_path=snap.screenshot_path,
                 message_vi=f'Bước "{step.title_vi}" thất bại: {e.message_vi or e}. Bạn có thể thao tác thủ công trong trình duyệt rồi bấm Tiếp tục.',
                 ai_explanation_vi=(explanation.explanation_vi + '\n' + explanation.user_action_vi) if explanation else ''))
        if resp.action == 'abort': raise UserAbortError
        if resp.action == 'skip': emit StepFinished(skipped, detail=str(e)); mark line/shipment flag; return
        # continue:
        if step.check(ctx): emit StepFinished(ok, detail='manual'); return
        attempt += 1   # re-run act()
```

Unrecoverable exceptions (anything else) → `RunResult.status='failed'`, `error=str(e)`, `RunFinished` emitted, browser left open. Every step must be **idempotent on retry** (it checks state before acting).

Note on `unverified_selector`: when `resolve()` succeeds through a candidate of a key with `verified: false`, the runner logs INFO only. There is no pause — calibrate mode is a separate command.

#### Steps (exact)

**S0 `S0.ensure_logged_in`** — "Kiểm tra đăng nhập"
- act: `session.goto("gateway/inbox.do")`. If title contains `-- Login` or `login.password_input` exists → `ask_user(NeedsUser(kind='login_required', options=['continue','abort'], message_vi='Vui lòng đăng nhập vào EDI Gateway trong cửa sổ trình duyệt (công cụ không bao giờ nhập mật khẩu). Sau khi đăng nhập xong hãy bấm Tiếp tục.'))`. After continue: if title contains `Select Profile` → click `login.profile_vendor_link` (expect_navigation); if title contains `View Profile` → click `login.edi_gateway_button` (expect_navigation). If still not inbox → `goto("gateway/inbox.do")` once more.
- check: title contains `EDI Gateway Inbox` **or** `inbox.document_id_input` exists.
- Used also as `handle_login` when any step detects the login page mid-run.

**S1 `S1.inbox_search`** — "Tìm PO {po} trong Inbox"
- data: `line.po_line.po_line_id`
- act: if not on inbox (`inbox.document_id_input` not present) → `goto("gateway/inbox.do")`. `fill('inbox.document_id_input', po)`; `click('inbox.search_button', expect_navigation=True)`.
- check: `exists('inbox.result_row', {'po'})` within 6 s. If results table exists but no row → `DataMismatchError(message_vi=f'Không tìm thấy PO {po} trong Inbox. Kiểm tra số PO và số dòng (01, 02…).')`.

**S2 `S2.open_po_detail`** — "Mở chi tiết PO {po}"
- act: `row = resolve('inbox.result_row_active', {'po'}, timeout 6 s)`; if ElementNotFound but `inbox.result_row` exists → all versions replaced → `DataMismatchError(message_vi=f'PO {po} chỉ còn phiên bản REPLACED (bị thay thế). Hãy kiểm tra PO mới.')`. `link = row.locator(css of inbox.result_link)`; `click_locator(link, expect_navigation=True)`.
- check: URL contains `view_order.do` **or** `po.page_marker` exists **or** `po.create_new_shipment_link` exists (any, 8 s).

**S3 `S3.read_dates`** — "Đọc ngày giao (Early/Late Ship Date)"
- act: `w, source = read_po_dates(ctx, po)`; `shipment.po_windows[master_po] = w`; log INFO `dates {po} {w} via {source}`.
- check: `master_po in shipment.po_windows`.

**S4 `S4.compute_ship_date`** — "Tính ngày giao"
- act: `res = compute_shipping_date(list(po_windows.values()), date.today())`; if `no_date_intersection` in flags → `ask_user(kind='no_date_intersection', options=['continue','abort'], message_vi='Các PO trong lô có khoảng ngày giao không giao nhau. Sẽ dùng điểm giữa của PO đầu tiên ({d}). Tiếp tục?')`. `shipment.shipping_date = res.shipping_date; shipment.date_result = res; shipment.flags += res.flags`.
- check: `shipment.shipping_date is not None`.

**S5 `S5.create_new_shipment`** — "Bấm Create New Shipment"
- precondition: on PO detail page of `shipment.lines[0]`.
- act: `click('po.create_new_shipment_link', expect_navigation=True)`. Fallback if the key cannot be resolved even after healing: `goto("gateway/new_shipment.do")` (the inbox `[New Shipment]` link is generic, `EDI_REAL_STRUCTURE.md` §1) and log WARNING.
- check: `exists('ship.form')` and `exists('ship.shipping_type')` (8 s).

**S6 `S6.fill_header_save`** — "Điền thông tin lô hàng và Lưu"
- act (all via `vars`):
  1. `check('ship.radio_with_cartons')`.
  2. `select('ship.shipping_type', value='3', label=cfg.flow.shipping_type)`.
  3. `fill('ship.shipping_date', format_mdy(shipment.shipping_date), dispatch_change=True)`.
  4. `select('ship.transportation_method', value='O', label=cfg.flow.transportation_method)`.
  5. `select('ship.scac_code', value=cfg.flow.scac_code, label_prefix=cfg.flow.scac_code)`; then wait ≤ 3 s for `read_value('ship.carrier')` non-empty (log WARNING if still empty; not fatal).
  6. `fill('ship.bill_of_lading', cfg.flow.bill_of_lading)`; `fill('ship.pro_number', cfg.flow.pro_number)`.
  7. FROM: if `factory.site_no` → `select('ship.from_site_no', label=factory.site_no)` else leave. `fill` name/address1/address2/city/state/zip.
  8. Country: `select('ship.from_country', label=factory.country, label_prefix=factory.country[:5])`; on `DataMismatchError`: `ask_user(kind='country_not_in_list', options=['continue','abort'], message_vi=f'Quốc gia "{country}" không có trong danh sách. Hãy bấm "More.." trong trình duyệt và chọn quốc gia, rồi bấm Tiếp tục.')`; after continue verify `read_value('ship.from_country')` non-empty.
  9. If `plan.dry_run`: `ask_user(kind='dry_run_stop', options=['continue','abort'], message_vi='Chế độ chạy thử: đã điền form nhưng KHÔNG lưu. Bấm Tiếp tục để kết thúc lô này.')`; set `shipment.status='dry_run'`; raise `StepSkipped`.
  10. `click('ship.save_button', expect_navigation=True)`.
  11. Capture: `wid = read_value('ship.web_shipment_id')`; if empty → look for `Web Shipment ID: (\d+)` in body text; also `re.search(r'shipment_id=(\d+)', url)`. `aid = read_value('ship.asn_shipment_id') or wid`. Set `shipment.web_shipment_id/asn_shipment_id`; `to_site_no = read_value('ship.to_site_no')` (best effort). `emit ShipmentCreated`. `results.write(plan)`.
- check: `shipment.web_shipment_id` matches `^\d{3,}$` **and** `exists('ship.submit_asn_button')` (page is a saved shipment). If `ship.error_text` has visible text → `PostconditionFailed(message_vi='Trang web báo lỗi: ' + text)`.
- Runner special-case: when the user chooses *continue* after a failure here and the page already shows a Web Shipment ID, the check passes and ids are captured by `check()` (check must call the same capture routine, idempotent).

**S7 `S7.add_purchase_orders`** — "Thêm các PO vào lô hàng"
- act: if not `exists('pos.page_marker')`: `click('ship.selected_pos_button', expect_navigation=True)` (from header page; this also saves). For each `line` in `shipment.lines` with status `pending`:
  - if `exists('pos.selected_row', {'po'})` → `line.status='added'`; continue (idempotent).
  - `click('pos.tab_search')`; `fill('pos.search_po_input', po)`; `click('pos.search_button', expect_navigation=True)`;
  - `row = resolve('pos.search_row', {'po'}, 6 s)`; `cb = row.locator("input[type='checkbox']").first`; `cb.check()`;
  - `dialogs.expect_accept(r'do you want to add the selected')`; `click('pos.add_selected_button', expect_navigation=True)`;
  - if not `exists('pos.selected_row', {'po'}, 6 s)` → `click('pos.tab_selected')` and re-check → else `PostconditionFailed(message_vi=f'PO {po} chưa xuất hiện trong danh sách đã chọn')`. `line.status='added'`.
  - Replaced detection: `read_text('pos.row_status_text', within row)`; if `Replaced` → `ask_user(kind='po_replaced', message_vi=f'PO {po} đã bị thay thế (Replaced). Hãy xử lý thủ công theo quy trình "PO replaced" rồi bấm Tiếp tục, hoặc Bỏ qua dòng này.')`; skip → `line.status='skipped'`.
- check: every non-skipped line has `pos.selected_row`.

**S8 `S8.create_carton[{po}]`** — "Tạo thùng cho PO {po}"
- act:
  1. Ensure on Selected POs page (`pos.page_marker`), tab selected. `row = resolve('pos.selected_row')`; `row_key = extract_row_key(row,'pos')`.
  2. `click('pos.row_create_carton_button', {'row_key'}, expect_navigation=True)`.
  3. Expect `carton.page_marker` (8 s).
  4. Items: if not `exists('carton.item_po_row', vars)`: `click('carton.tab_items_search')` (ignore if absent); `row = resolve('carton.items_search_row')`; check its checkbox; `dialogs.expect_accept(r'do you want to add the selected')`; `click('carton.items_add_selected', expect_navigation=True)`; require `carton.item_po_row` (8 s).
  5. Sites: if not `exists('carton.site_row', vars)`: `click('carton.tab_sites_search')` (ignore if absent); `row = resolve('carton.sites_search_row')`; check checkbox; `expect_accept`; `click('carton.sites_add_selected', expect_navigation=True)`; require `carton.site_row`.
  6. Read web data: `ordered = parse_decimal(read_text('carton.item_qty_ordered_cell'))`; `um = read_text('carton.item_um_cell').strip()`; prepack: `prepack_units = None`; if `exists('carton.item_prepack_row')`: text = its inner_text; `m = re.search(r'(\d+)\s*EA\b', text)` → `prepack_units = int(m.group(1))`; else if `um.upper() == 'AS'` and no sub-row → `prepack_units` stays None but log WARNING.
  7. `carton = compute_carton_plan(line.quantity, line.packages, prepack_units)`; `line.carton = carton; line.web_qty_ordered = ordered; line.web_um = um`. If any `error` flag → `resp = ask_user(kind='non_integer_carton', input_fields=[InputField('qty_per_carton','Qty Per Carton', default=str(carton.qty_per_carton)), InputField('cartons_per_site','Cartons Per Site', default=str(carton.cartons_per_site))], message_vi=f'Số lượng {qty} / {pkgs} thùng không chia hết (prepack {N}). Nhập tay hoặc Bỏ qua.')`; continue → use typed ints; skip → `StepSkipped`.
  8. `flags = check_ordered(line.quantity, ordered, um, prepack_units)`; if `qty_over_ordered` and `cfg.flow.pause_on_qty_warning` → `ask_user(kind='qty_mismatch', message_vi=f'Số lượng Excel ({qty}) lớn hơn số đặt hàng trên web ({ordered_units}). Tiếp tục nhập, Bỏ qua dòng, hay Dừng?')`.
  9. `select('carton.packaging_code_select', label=cfg.flow.packaging_code_carton, label_contains='Physical Container')`.
  10. `fill('carton.item_qty_per_carton_input', str(qpc), dispatch_change=True)`; `fill('carton.site_cartons_per_site_input', str(cps), dispatch_change=True)`.
  11. `click('carton.save_button', expect_navigation=True)`. Postcondition inside act: inputs re-read equal the typed values (page may reload) and no `ship.error_text` visible.
  12. `click('carton.back_to_po_button', expect_navigation=True)`; require `pos.page_marker`.
  13. `line.status='carton_done'`.
- check: `line.status in ('carton_done','skipped')` and `exists('pos.page_marker')`.

**S8b `S8b.set_partial[{po}]`** — "Đổi Complete → Partial cho PO {po}"
- act: `row = resolve('pos.selected_row')`; `row_key`; `select('pos.row_complete_partial_select', label=cfg.flow.complete_partial)`; `click('pos.row_save_button', expect_navigation=True)`.
- check: after reload `read_value('pos.row_complete_partial_select') == 'Partial'` (option value or text).

**S9 `S9.enter_weights`** — "Nhập trọng lượng"
- act: from Selected POs page `click('pos.view_detail_button', expect_navigation=True)`; require `weight.form`. If `len(lines) > 10` and `weight.orderperpage_select` exists → `select(value='100000', label='All')` and wait for reload. For each non-skipped line: `row = resolve('weight.row')`; `row_key = extract_row_key(row,'weight')`; `fill('weight.row_weight_input', line.weight_text, dispatch_change=True)`; `select('weight.row_um_select', label=cfg.flow.weight_um)` (dispatch change). Then `click('weight.save_button', expect_navigation=True)`. Re-read each input; mismatch → `PostconditionFailed`. `line.status='weight_done'`.
- check: all non-skipped lines `weight_done`.

**S10 `S10.finish_shipment`** — "Hoàn tất lô (chờ người dùng kiểm tra)"
- act: `click('weight.back_button', expect_navigation=True)` if on weight page; if `cfg.flow.click_validate`: `click('pos.validate_button', expect_navigation=True)`. `results.write(plan)`; if `cfg.flow.write_back_excel`: WP-A `write_back` is **not** called here (needs HeaderDetection) — the worker emits `RunFinished` and WP-C calls `write_back`. Emit `NeedsUser(kind='finished_review', options=['continue'], message_vi=f'Lô {idx}: Web Shipment ID {wid} đã tạo xong. Hãy kiểm tra trong trình duyệt và tự bấm Submit ASN khi sẵn sàng.')` **only when there are more shipments to process**; the last shipment finishes without a blocking prompt (the GUI shows the notification).
- check: True.

Estimated `total_steps` = 1 + Σ per shipment (3·|masters| + 2 + 2 + 1 + 2·|lines| + 2).

### 4.12 Commands and worker — `automation/commands.py`, `automation/worker.py`

```python
@dataclass(slots=True) class Command: pass
@dataclass(slots=True) class OpenBrowser(Command): navigate_home: bool = True
@dataclass(slots=True) class CloseBrowser(Command): pass
@dataclass(slots=True) class NavigateTo(Command): path: str = "gateway/inbox.do"
@dataclass(slots=True) class RunPlanCommand(Command): plan: RunPlan
@dataclass(slots=True) class Highlight(Command): key: str; vars: dict[str, str] = field(default_factory=dict)
@dataclass(slots=True) class Pick(Command): key: str
@dataclass(slots=True) class CancelPick(Command): pass
@dataclass(slots=True) class TestKey(Command): key: str; vars: dict[str, str] = field(default_factory=dict)   # emits LogEvent with resolve result
@dataclass(slots=True) class OpenInspector(Command): pass          # page.pause()
@dataclass(slots=True) class ReloadSelectors(Command): pass
@dataclass(slots=True) class Shutdown(Command): pass

class AutomationWorker:
    def __init__(self, config: AppConfig, sink: EventSink, advisor: VisionAdvisor | None,
                 selectors: SelectorStore | None = None, profile_dir: Path | None = None)
    def start(self) -> None
    def stop(self, timeout_s: float = 10) -> None            # submit(Shutdown()); join
    def submit(self, cmd: Command) -> None
    def respond(self, resp: UserResponse) -> None
    def request_abort(self) -> None
    def update_config(self, config: AppConfig) -> None       # thread-safe swap; applies on next command
    def set_advisor(self, advisor: VisionAdvisor | None) -> None
    @property
    def is_running(self) -> bool                             # a RunPlanCommand is executing
    @property
    def is_browser_open(self) -> bool
```

Loop: `while True: cmd = queue.get(); if Shutdown: close; break; dispatch in try/except Exception → emit LogEvent(ERROR) + for RunPlanCommand emit RunFinished(failed)`. `ask_user` implementation: `self._pending[request_id] = queue.Queue(1)`; emit event; poll `get(timeout=0.5)` until response or abort. `respond()` puts into the matching queue (unknown id → ignored, logged).

`BrowserState` events are emitted after open/close and after each `RunFinished`.

### 4.13 Calibrate mode — `automation/calibrate.py`, `picker.js`

```python
class Calibrator:
    def __init__(self, session: BrowserSession, store: SelectorStore, resolver: SelectorResolver, sink: EventSink, log)
    def highlight(self, key: str, vars: dict) -> bool:
        """resolve with 2 s budget; on success evaluate JS to set outline '3px solid #ff3b30' + scrollIntoView for 4 s (setTimeout restore);
        emit LogEvent(INFO, 'highlight ok via ...') / (WARNING, 'not found'). Returns found."""
    def pick(self, key: str) -> None:
        """Inject picker.js (page.add_script_tag(content=...) or evaluate); it installs a capture-phase click handler and hover outline.
        Expose binding once per page: page.expose_binding('__ediPicked', self._on_picked) (guard against double expose).
        On click the JS calls window.__ediPicked({candidates:[...]}) and removes itself. Pick is cancelled by CancelPick → evaluate window.__ediPickerCancel().
        Worker keeps processing other commands while a pick is armed (no blocking)."""
    def _on_picked(self, source, payload: dict) -> None:
        """Candidates are generated by picker.js in priority order:
          1. css '#id' if id unique and not numeric-only
          2. css 'tag[name="..."]' if name unique
          3. role+name (button/link/textbox with accessible name)
          4. css 'input[value="..."]' for buttons
          5. xpath by nearest label text: //*[normalize-space()='Label']/following::input[1]
          6. absolute css path (nth-child chain, ≤ 6 levels)
        Store best as learned (source='learned'), mark_verified(key), emit CalibrationResult(key, candidate, saved=True)."""
    def open_inspector(self) -> None            # page.pause() (blocks the worker thread until the inspector is closed — documented)
```

`picker.js` must also show a small fixed banner: "Bấm vào phần tử cho: {key} — Esc để huỷ".

---
## 5. WP-B — Mock EDI Gateway (`edi_assistant.mock_edi`)

Purpose: run the full flow headless in CI and let the user rehearse. Stdlib only (`http.server.ThreadingHTTPServer`, `urllib.parse`, `html`). It replicates the **real** URL paths, page titles, form/field names and the JS `confirm()` behaviour recorded in `docs/EDI_REAL_STRUCTURE.md`; for uninspected pages it replicates the screenshots.

### 5.1 Server API

```python
@dataclass
class MockOptions:
    port: int = 8765
    require_login: bool = True        # first visit shows login page; "Go" with any password logs in
    dates_in_pdf: bool = False        # True: PO detail shows dates ONLY inside an embedded PDF (iframe to /gateway/order_pdf.do)
    prepack_pos: set[str] = field(default_factory=set)   # 9-digit POs whose item has a prepack sub-row (N = 6)
    country_options: tuple[str, ...] = ("US", "CA", "CN")

class MockServer:
    def __init__(self, options: MockOptions | None = None, state: "MockState | None" = None)
    def start(self) -> str            # starts in a daemon thread; returns base url "http://127.0.0.1:{port}/vms-gateway/"
    def stop(self) -> None
    @property
    def state(self) -> MockState
```

`python -m edi_assistant.mock_edi --port 8765 [--no-login] [--dates-in-pdf] [--seed-excel PATH]` prints the base URL and serves until Ctrl-C. `--seed-excel` adds orders for every PO found in that Excel (via WP-A `extract_rows`? **No** — WP-B must not depend on `data`; it uses a simple regex over `openpyxl` cell values for 7/9-digit numbers and creates lines 01 and 02 per master PO).

### 5.2 State (`state.py`)

```python
@dataclass
class MockOrder:
    po_line_id: str            # "580367401"
    order_id: int              # internal id used in view_order.do?order_id=
    status: str                # "ACKNOWLEDGED" | "SUBMITTED" | "REPLACED"
    early: str = "09-MAR-26"
    late: str = "13-MAR-26"
    qty_ordered: int = 510     # in AS when prepack, else units
    prepack: int | None = None # 6 → item row UM "AS", sub-row "6 EA"
    site_no: str = "512"
    site_addr: tuple[str, str, str, str] = ("570 EAST MILL STREET", "SAN BERNARDINO", "CA", "92408")
    versions: int = 2          # number of inbox rows: versions-1 REPLACED (stricken) + 1 active

@dataclass
class MockShipment:
    shipment_id: int
    header: dict[str, str]     # raw posted form fields
    pos: dict[str, dict]       # po_line_id -> {"po_header_id": int, "complete_partial": "Complete", "pack_code": "CTN25", "status": "Available"}
    cartons: dict[str, dict]   # po_line_id -> {"cart_def_id": int, "items_added": bool, "sites_added": bool, "packaging_code": "", "qty_per_carton": "", "cartons_per_site": "", "saved": bool}
    weights: dict[str, dict]   # po_line_id -> {"weight": "", "um": "KG", "site_wgt_id": int}

@dataclass
class MockState:
    logged_in: bool
    profile_selected: bool
    orders: dict[str, MockOrder]
    shipments: dict[int, MockShipment]
    next_shipment_id: int = 792872
    next_po_header_id: int = 1001
    next_cart_def_id: int = 4263755
    next_site_wgt_id: int = 501
    submit_called: bool = False
    submit_attempts: int = 0
    log: list[str]             # one line per state-changing request
    def seed_default(self) -> None   # POs 580367401, 580367301 (and 580367402 REPLACED-only for tests), 668254501 with prepack 6 / qty 167 AS
    def snapshot(self) -> dict       # JSON-able, served at /__state
    def reset(self) -> None
```

### 5.3 Routes (all under `/vms-gateway/`; GET unless noted; `<title>` exactly as listed)

| Route | Title | Behaviour |
|---|---|---|
| `/` | — | 302 → `login.do` if `require_login and not logged_in` else `gateway/inbox.do` |
| `login.do` | `Vendor Management Suite -- Login` | form: `input[name=userid]` prefilled `Grayson@shyftglobal.com`, `input[type=password][name=password]`, `input[type=submit][value=Go]`. POST → `logged_in=True` → 302 `login.do?profile` |
| `login.do?profile` | `Vendor Management Suite -- Select Profile` | table with link text `SHYFT GLOBAL LLC` → `vendor.do?vendor_id=1&profile`; banner text "DC addresses have been changed... CA=512, NJ=053, GA=934" |
| `vendor.do` | `Vendor Management Suite -- View Profile` | `<form action="gateway/inbox.do"><input type="submit" value="EDI Gateway"></form>`; sets `profile_selected` |
| `gateway/inbox.do`, `gateway/filter_inbox.do` | `Vendor Management Suite -- EDI Gateway Inbox` | tabs `<a href="inbox.do">INBOX</a> <a href="outbox.do">OUTBOX</a> <a href="drafts.do">SHIPMENTS</a>`; form `name=filterinbox action=filter_inbox.do method=GET` with the 9 filter checkboxes, `input[name=documentID]`, `start_date`, `end_date`, `input[type=submit][value=Search]`, `input[name=reset][value=Reset]`, `select[name=orderperpage]`. Results table id `inboxTable` with `<th>` headers `#, Read, Type, Document ID, Transmission Date, Status, Shipment Status, Turn Around`; rows `tr.odd/tr.even`, replaced versions get class `stricken` + CSS `tr.stricken{text-decoration:line-through}`; Document ID cell `<a href="view_order.do?order_id=N&orderNo=PO">PO</a>`; status cell text; Turn Around `[<a href="new_shipment.do">New Shipment</a>]`. Without `documentID` → all orders; with → exact match on `po_line_id` (nothing for 7 digits, like the real site) |
| `gateway/view_order.do?order_id=N&orderNo=PO` | `Vendor Management Suite -- View Order` | header line `850 - Purchase Order : <b>PO</b> \| ACKNOWLEDGED \| Not Shipped`; links `<< Return To Order List` (inbox.do), `Create New Shipment` (`new_shipment.do?orderNo=PO`). Body: if `not dates_in_pdf` → `<div id="poSummary">` with table cells `Order Date 10-JAN-26`, `Early Ship Date 09-MAR-26`, `Late Ship Date 13-MAR-26`, `Destination SAN BERNARDINO, CA WAREHOUSE 570 EAST MILL STREET SAN BERNARDINO CA 92408`; if `dates_in_pdf` → `<iframe src="order_pdf.do?order_id=N" width="800" height="600"></iframe>` only. Marks order read. |
| `gateway/order_pdf.do?order_id=N` | — | `application/pdf` generated by `minipdf.make_pdf(lines)` with lines `["Bill To Burlington Merchandising Corp.", "Order Date Early Ship Date Late Ship Date", "10-JAN-26 09-MAR-26 13-MAR-26", "Destination ..."]` |
| `gateway/drafts.do` | `BCF EDI Gateway -- Drafts` | table of shipments: link `new_shipment.do?readyForLabels=N&shipment_id=ID&ReadOnly=false`, Create Date, Status CREATED, State text |
| `gateway/new_shipment.do` (GET) | `Vendor Management Suite -- Shipment` | form `name=new_shipment id=new_shipment method=POST action=new_shipment.do onsubmit="return checkform(this)"`. Hidden `action, shipment_id, Dirty_Flag, AddUpdate`. Fields exactly as §4.5 ids/names: `#txtWebShipmentId` (readonly, value = id or ""), `#txtASNId`, `input[name=CartonRadio][value=Y]` + `[value=N]`, `#OptShippingType` (0 Select One, 1 Pack by store and ship to DC, 2 Drop ship to the stores, 3 Ship to DC, 4 Direct to customer), `#OptTransMethod` (""=Select One, O=Containerized Ocean, S=Ocean, A=Air, M=Motor (Common Carrier), LT=LTL), `#txtShippingDate`, `#OptSCACCode` (""=Select One, MAEU=MAEU-MAERSK, UNKN=UNKN-UNKNOWN, CMDU=CMDU-CMA CGM) with inline `onchange="setCarrier()"` that sets `txtcarrier` to the text after `-`, `input[name=txtcarrier]` readonly, `txtBillLading`, `txtPRONumber`, `chkShipment`, `select[name=OptSiteNO]` ("" Select One, "Add New Address"), `txtSiteNO`, `#txtFromName`, `#txtFromAddress1`, `txtFromAddress2`, `#txtFromCity`, `#txtFromState`, `#txtFromZip`, `select#txtFromCountry` with options from `country_options` (values `US,CA,CN`, texts `UNITED STATES, CANADA, CHINA`) + `<a href="#" onclick="alert('More countries popup (mock)')">More..</a>`, TO readonly `optToSiteNo, txtToName, txtToAddress1, txtToAddress2, txtToCity, txtToState, txtToZip, txtToCountryUnHidden` (filled from the order when `orderNo` given or after save). Buttons: `<input type=button value="<< Back To Drafts">`, `input[name=btnCancel][value='Clear Values']`, `#submit123` submit `value="Selected Purchase Orders >>"` (sets `AddUpdate=Update&next=pos`), `#saveonly` submit `value=Save`, `#cancelShipment` button `onclick="if(confirm('Do you want to cancel this shipment?')) location='cancel_shipment.do'"`, `input[name=label][disabled]`, `input[name=validateShipment][value=Validate]`, `input[name=btnSubmitASN][value='Submit ASN']` `onclick="document.location.href='asn.do?shipment_id=ID'"` (disabled when no id). Required-field check `checkform` mirrors the real asterisks (name, address1, city, state, zip, shipping type, date, transport, SCAC). |
| `gateway/new_shipment.do` (POST) | — | validates required fields (missing → re-render with `<span class="error">Please enter Name</span>`), creates/updates `MockShipment`, assigns `shipment_id` on first save; 302 → `new_shipment.do?readyForLabels=N&shipment_id=ID&ReadOnly=false` or, if `next=pos`, → `selected_pos.do?shipment_id=ID` |
| `gateway/selected_pos.do?shipment_id=ID[&tab=search][&poNo=..]` | `BCF EDI Gateway -- Selected Purchase Orders` | breadcrumb `Web Shipment ID: <a>ID</a> >> Selecting Purchase Orders`; tab links `Selected Purchase Orders` (`?shipment_id=ID`), `Search Purchase Orders` (`?shipment_id=ID&tab=search`). Search tab: form GET with `input[name=purchaseOrderNo]` labelled "Purchase Order No", `select[name=status]`, `input[type=submit][value=Search]`, `Reset`; results table headers `All None / Purchase Order No / Status` with rows `<input type=checkbox name=selPo value=PO>` `<a>PO</a>` `Available`; form POST `selected_pos_add.do` with `<input type=submit value="Add Selected" onclick="return confirm('Do you want to add the selected Purchase Orders ?')">` and `Cancel`. Selected tab: form `name=form1` with hidden fields listed in §4 of the real-structure doc; per PO row (poHeaderId N): `<input type=checkbox name="PO-N">`, `<a>PO</a>`, status cell (`Available` or `Replaced`), `select[name=complete_shipment_N]` (Complete/Partial), `select[name=web_sh_packing_type_id_N]` (6 = Customized quantities and cartons, disabled), `select[name=pack_code_N][id=pack_code]` (CTN25 = Corrugated or Solid Carton, …), `<input type=button value=Save onclick="saveCarton('saveCarton', N, 'PO', 'Y')">`, `<input type=button value="Create Carton" onclick="insertCarton('insertCarton', N, 'PO', 'Y')">`. JS `saveCarton` POSTs `selected_pos_save.do` (fields `poHeaderID`, `complete_partial`, `packaging_code`); `insertCarton` navigates to `carton.do?shipment_id=ID&po=PO`. Bottom: `<< Back To Shipment Header`, `input[name=poSiteShipment][value='View Shipment Orders Detail']` → `po_site_shipment.do?shipment_id=ID`, `input[name=validateShipment][value='Validate Shipment']`, `input[name=btnSubmitASN][value='Submit ASN']` (same onclick as header). |
| `gateway/selected_pos_add.do` (POST) | — | adds each `selPo` (status from order: `Replaced` if order.status == REPLACED else `Available`); 302 → selected tab |
| `gateway/selected_pos_save.do` (POST) | — | stores complete_partial/pack_code; 302 → selected tab |
| `gateway/carton.do?shipment_id=ID&po=PO[&itab=search][&stab=search]` | `BCF EDI Gateway -- Carton Definition` | heading `Create Carton Definition : Customized quantities and cartons`, breadcrumb `Web Shipment ID: ID >> Purchase Order: PO >> Carton Definition: CID`. Items block: tabs `Selected Items` / `Search Items` (`&itab=search`). Search Items table headers `All None, SKU No, UPC, Style, Color, Size, UM, Ordered, Shipped`; group row text `PO{master}LN{line}` (e.g. `PO5803674LN1`) with `<input type=checkbox name=selItem value=1>`, sub-row SKU `46602776 RCS310DUC2 …`; buttons form POST `carton_items_add.do` with `Add Selected` `onclick="return confirm('Do you want to add the selected Items ?')"`. Selected Items (after items_added): `Carton Name <input name=carton_definition_name value="CARTON 1">`, `Packaging Code <select name=packaging_code>` (""=Select One, `PCC`=Physical Container - Carton, `PLT`=Pallet, `BAG`=Bag), `Save`, `Undo`; table headers `All None, Sku/Upc/Prepack, Style, Color/Size, Qty Ordered, Qty Per Carton, Unit of Measure`; row: checkbox, `<a>PO{master}LN{line}</a>`, style, color, `<td>{qty_ordered}</td>`, `<td><input type=text name=qty_per_carton_1 size=5></td>`, `<td>{AS or EA}</td>`; if prepack: next `<tr class="prepack">` with cells `46602776 RCS310DUC2`, `TEALIIIIIIA0/QTY`, `<td>6</td>`, `<td></td>`, `<td>EA</td>` (no inputs). Sites block: tabs `Selected Sites` / `Search Sites` (`&stab=search`); Search Sites table headers `All None, Site, Address, City, State, Zip Code`, row checkbox `selSite value=512`; `Add Selected` with confirm `Do you want to add the selected Sites ?` → POST `carton_sites_add.do`. Selected Sites table headers `All None, State, City, Site No, Site Name/Address, Cartons Per Site`; row with `<a>512</a>` and `<input type=text name=cartons_per_site_512>`. Bottom buttons: `<< Back to Purchase Order` (→ selected_pos.do), `Auto populate Qty (Carton & Site)`, `Auto populate Qty (Site)`, `Save` (POST `carton_save.do` with packaging_code, qty_per_carton_*, cartons_per_site_*), `Undo`. |
| `gateway/carton_items_add.do`, `carton_sites_add.do`, `carton_save.do` (POST) | — | update carton dict; `carton_save.do` validates: packaging_code non-empty and both numbers > 0 else re-render with `<span class="error">`; also error if `qty_per_carton * cartons_per_site > qty_ordered * (prepack or 1)` ("Quantity exceeds ordered") ; 302 back to `carton.do` |
| `gateway/po_site_shipment.do?shipment_id=ID[&orderperpage=…]` | `Vendor Management Suite -- Create User` (sic) | form `name=po_site_shipment method=POST action=po_site_shipment_save.do`; `select[name=commonunit]` (Select One/KG/LB), `select[name=orderperpage]` (10,15,20,25,100000=All; only first N rows rendered unless All), link `Set Weight for all PO's`; table headers `PO #, SITE, ADDRESS, CITY, STATE, LADING QUANTITY, WEIGHT, WEIGHT UM`; per row (M = site_wgt_id): `<a>PO</a>`, `512`, address…, lading qty, `<input type=text name=editedSiteWgtquM id=editedSiteWgtM onchange="setHiddenOnChange(M)">`, `<select name=editedSiteWgtumM>` (KG/LB); buttons `input[name=backtoorders][value='<< Back To Select Purchase Order']`, `input[name=SaveCarton2][value=Save]`. |
| `gateway/po_site_shipment_save.do` (POST) | — | stores weights; 302 back |
| `gateway/asn.do?shipment_id=ID` | `SUBMITTED` | **sets `submit_called=True`, `submit_attempts += 1`**, returns a page saying "ASN SUBMITTED (MOCK)". The automation's route block must prevent this request from ever being made. |
| `gateway/cancel_shipment.do` | — | deletes shipment (never reached in tests) |
| `__state` | — | JSON `state.snapshot()` |
| `__reset` (POST) | — | `state.reset(); seed_default()` |

All pages share a header with the `INBOX / OUTBOX / SHIPMENTS` tabs and vendor name `SHYFT GLOBAL LLC`. Pages must be valid HTML with `<label for=...>` where the real site has visible labels (so label-based fallbacks work).

### 5.4 `minipdf.py`

```python
def make_pdf(lines: list[str]) -> bytes
    """Single-page uncompressed PDF (Helvetica 11pt, one text line per entry, y from 760 down by 16) with a correct xref table,
    so pypdf.PdfReader(...).pages[0].extract_text() returns the lines (joined with newlines). ASCII only; escape ( ) \\."""
```

---
## 6. WP-C — desktop app (`edi_assistant.app`)

PySide6 6.7+. All user-visible strings live in `app/strings_vi.py` as module constants (`BTN_START = "Bắt đầu nhập liệu"` …). No string literals in Vietnamese elsewhere in `app/` except `strings_vi.py` and `README_VI.md`.

### 6.1 `app/main.py`

```python
def main(argv: list[str] | None = None) -> int:
    """1. os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(paths.playwright_browsers_dir()))  — BEFORE importing playwright anywhere.
       2. setup_logging(); cfg = load_config()
       3. app = QApplication; app.setQuitOnLastWindowClosed(False); app.setApplicationName(APP_DISPLAY_NAME)
       4. SingleInstance('EDIAssistant-{username}'): if another instance is running → send 'SHOW' and return 0.
       5. advisor = build_advisor(cfg.ai); worker = AutomationWorker(cfg, bridge.sink, advisor); worker.start()
       6. win = MainWindow(cfg, worker, bridge); tray = TrayIcon(win); if not cfg.notify.start_minimized: win.show()
       7. app.exec(); worker.stop(); save_config(cfg); return code"""
```

`app/single_instance.py`: `class SingleInstance(QObject)` using `QLocalServer`/`QLocalSocket`; signal `show_requested`. `app/autostart.py`: `set_start_with_windows(enabled: bool) -> None` / `is_start_with_windows() -> bool` using `winreg` HKCU `Software\Microsoft\Windows\CurrentVersion\Run`, value name `EDIAssistant`, data `"<sys.executable>" --minimized` when frozen, no-op on non-Windows (guarded by `sys.platform == "win32"`). Works in portable and installed mode because it always points to the current exe path and is refreshed on every start when enabled.

### 6.2 `app/worker_bridge.py`

```python
class WorkerBridge(QObject):
    event_received = Signal(object)          # every Event (for the log view)
    run_started = Signal(object); step_started = Signal(object); step_finished = Signal(object)
    progress = Signal(object); log = Signal(object); needs_user = Signal(object)
    shipment_created = Signal(object); browser_state = Signal(object); calibration = Signal(object); run_finished = Signal(object)
    def sink(self, ev: Event) -> None        # called from worker thread: self.event_received.emit(ev) + typed signal (Qt queues cross-thread)
```

Qt detail: `WorkerBridge` is created in the GUI thread; emitting a signal from the worker thread on a QObject living in the GUI thread results in a queued delivery — no `QMetaObject.invokeMethod` needed. Dataclass payloads are passed as `object`.

### 6.3 `MainWindow` (`app/main_window.py`)

Layout (single window, min 1100×700, tabs):

- Tab "Nhập liệu" (main):
  1. Group "Tệp Excel": path field + "Chọn tệp…", sheet combo, status label (template recognized / similar / new), button "Sửa ánh xạ cột…" (MappingDialog).
  2. Group "Nhà máy (địa chỉ gửi)": combo of factories + "Thêm/Sửa…" (FactoryDialog); auto-selected by `FactoryStore.suggest(company_text)` with label "Gợi ý từ tệp: {company_text}".
  3. Group "Tuỳ chọn": radio "Một lô cho cả tệp" / "Mỗi PO chính một lô"; checkbox "Chạy thử (không lưu)"; checkbox "Ghi ASN vào bản sao Excel".
  4. `PlanTable` (review): columns Lô, PO dòng, PO chính, Dòng, Mô tả, Thùng, Số lượng, SL/thùng, Trọng lượng (KG), Cảnh báo. Rows with error flags are red; the Start button is disabled while any error flag exists.
  5. Buttons: "Mở trình duyệt", "Bắt đầu nhập liệu", "Dừng" (abort), "Tạm dừng" not provided (pauses are event-driven).
  6. `StepsView` (list with icons ✓ ✗ ↷ ●) + progress bar + current message.
- Tab "Nhật ký": `LogView` (QPlainTextEdit, tail, level filter).
- Tab "Lịch sử": table from `load_run_history()` with buttons "Mở thư mục", "Mở CSV".
- Menu: Tệp (Mở Excel, Thoát), Công cụ (Cài đặt…, Hiệu chỉnh bộ chọn…, Mở Playwright Inspector, Cài trình duyệt Chromium…, Mở thư mục dữ liệu), Trợ giúp (Hướng dẫn = opens README_VI.md, Giới thiệu).

Behaviours:
- Choosing a file runs the §3.17 sequence in the GUI thread (fast; files are small). Errors → QMessageBox with `message_vi`.
- "Bắt đầu nhập liệu": `validate_mapping`, `build_plan`, `TemplateStore.learn(...)`, `FactoryStore.upsert`, then `worker.submit(RunPlanCommand(plan))`. Keeps `det` (HeaderDetection) for write-back.
- `needs_user` → `PauseDialog` (modal to the main window but **not** blocking the worker beyond its own wait); the window is raised and a notification is shown (`notifications.notify(title, text, sound=True)`). Dialog result → `worker.respond(UserResponse(...))`.
- `run_finished` → if `write_back_excel` and result has ids → `write_back(plan, det)`; notification "Hoàn tất: {n} lô, Web Shipment ID: {ids}. Hãy kiểm tra và bấm Submit ASN thủ công."; steps view shows result; history refreshed.
- Close button → hide to tray (tray tooltip "EDI Assistant đang chạy"); tray menu: Hiện cửa sổ, Mở trình duyệt, Thoát. Exit asks for confirmation if a run is active.

### 6.4 Dialogs

- `MappingDialog(det: HeaderDetection, mapping: ColumnMapping, scores: dict[str, float], preview_rows: list[dict[int, object]])`: table with one row per field (`FIELD_KEYS`; required marked `*`), a combo of detected columns (`"C — 包装 / Packages"`) plus "(không dùng)"; a preview of the first 5 data rows; confidence colouring (≥0.85 green, ≥0.7 yellow, else none). Template name field. `result() -> tuple[ColumnMapping, str]`.
- `FactoryDialog(store: FactoryStore, prefill: FactoryAddress | None)`: list + form (Tên, Địa chỉ 1, Địa chỉ 2, Thành phố, Tỉnh/Bang, Mã bưu điện, Quốc gia (editable combo: CHINA, VIETNAM, UNITED STATES, CANADA, INDIA, BANGLADESH, CAMBODIA, INDONESIA), Site No, Tên khác (aliases, comma separated)). `selected() -> FactoryAddress | None`.
- `SettingsDialog(cfg: AppConfig)`: tabs "Trang web" (base_url, use_mock, mock_url, vendor_profile_name), "Trình duyệt" (channel combo msedge/chrome/chromium, headless, slow_mo, timeout), "Quy trình" (all FlowConfig fields, with explanations), "AI" (enabled, preset combo from `AI_PRESETS` → fills provider/base_url/model, api_key (password echo), model, vision, max_calls_per_run, button "Kiểm tra kết nối" which calls `advisor.explain_error` with a tiny request and shows the result/error), "Thông báo" (sound, balloon, start minimized, start with Windows). OK → `save_config`, `worker.update_config`, `worker.set_advisor(build_advisor(...))`.
- `PauseDialog(ev: NeedsUser)`: shows `message_vi`, `ai_explanation_vi` (collapsible), screenshot thumbnail (click → open full), input fields if any, buttons per `options` (continue = "Tiếp tục", skip = "Bỏ qua bước", abort = "Dừng"). Returns `UserResponse`.
- `CalibrateDialog(store: SelectorStore, worker)`: table of all keys (key, page, verified ✓/✗, #learned, description); filter by page; buttons "Tô sáng" (Highlight), "Chọn trên trang" (Pick; shows "Đang chờ bạn bấm vào phần tử…" until `CalibrationResult`), "Kiểm tra" (TestKey), "Xoá đã học" (remove_learned), "Mở Inspector", "Mở trang…" (NavigateTo with quick links: Inbox, New Shipment, Drafts). Vars panel: PO (9 digits), site no, row key — passed to Highlight/TestKey. Unverified keys sorted first and highlighted.

### 6.5 Notifications (`app/notifications.py`)

```python
def notify(tray: QSystemTrayIcon | None, title: str, text: str, *, sound: bool, balloon: bool, icon=QSystemTrayIcon.Information) -> None:
    """balloon → tray.showMessage(title, text, icon, 10000) (Windows 10/11 renders it as a toast).
    sound → if sys.platform == 'win32': winsound.PlaySound(str(resource('notify.wav')), SND_FILENAME | SND_ASYNC) else QApplication.beep()."""
```

### 6.6 Browser install (`app/browser_install.py`)

```python
def chromium_available() -> bool        # any directory matching 'chromium-*' under paths.playwright_browsers_dir() with an executable inside
def edge_available() -> bool            # Windows: registry/known paths of msedge.exe; macOS: /Applications/Microsoft Edge.app; else False
def install_chromium(parent: QWidget) -> bool:
    """Runs the Playwright driver CLI in a QProcess with env PLAYWRIGHT_BROWSERS_PATH set:
       cmd = [sys.executable, '-m', 'playwright', 'install', 'chromium'] in dev;
       frozen: from playwright._impl._driver import compute_driver_executable → (node_exe, cli_js) → [node_exe, cli_js, 'install', 'chromium'].
       Shows a QProgressDialog 'Đang tải Chromium (~150 MB)…' streaming stdout lines; returns True on exit code 0."""
```

Startup check (in `MainWindow` after show): if `cfg.browser.channel == 'msedge' and not edge_available() and not chromium_available()` → offer install dialog.

### 6.7 AI clients (`app/ai/`)

`app/ai/__init__.py`:
```python
def build_advisor(cfg: AiConfig) -> VisionAdvisor | None   # None when not enabled or api_key empty (except ollama/localhost → allowed without key)
```

Common helpers in `app/ai/prompts.py` (verbatim templates below) and a shared `_parse_json(text) -> dict | None` that strips ``` fences and finds the first `{...}` block.

`OpenAICompatAdvisor(cfg)` — `POST {base_url}/chat/completions`, headers `Authorization: Bearer {api_key}`, body:
```json
{"model": cfg.model, "temperature": 0, "max_tokens": cfg.max_tokens,
 "messages": [{"role": "system", "content": SYSTEM},
              {"role": "user", "content": [{"type": "text", "text": USER_TEXT},
                                           {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}]}]}
```
(image part omitted when no screenshot / vision off; content becomes a plain string). Response text = `choices[0].message.content`. Non-2xx → `AiError(provider='openai_compat', status=...)`.

`AnthropicAdvisor(cfg)` — `POST {base_url}/v1/messages`, headers `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`, body:
```json
{"model": cfg.model, "max_tokens": cfg.max_tokens, "system": SYSTEM,
 "messages": [{"role": "user", "content": [
    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}},
    {"type": "text", "text": USER_TEXT}]}]}
```
No `temperature` (current Claude models reject non-default sampling parameters); no assistant prefill. Response text = concatenation of `content[*].text` for blocks with `type == "text"`. Non-2xx → `AiError(provider='anthropic', status=...)`. Default models: `claude-haiku-5-5` (cheap default), `claude-sonnet-5-5` (preset "anthropic_sonnet").

Both use `httpx.Client(timeout=cfg.timeout_s)`, one request per call, no retries except one retry on 429/5xx after 2 s.

### 6.8 Prompt templates (`app/ai/prompts.py`, verbatim)

```python
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

SYSTEM_EXPLAIN = """Bạn là trợ lý cho nhân viên vận hành (nói tiếng Việt) đang dùng công cụ tự động nhập ASN trên cổng EDI Gateway của Burlington.
Một bước tự động vừa thất bại. Hãy nhìn thông tin trang (và ảnh chụp nếu có) và giải thích NGẮN GỌN bằng tiếng Việt chuyện gì đang xảy ra và người dùng nên làm gì trong trình duyệt.
Chỉ trả về một đối tượng JSON đúng dạng:
{"explanation_vi":"...tối đa 3 câu...","likely_cause":"session_expired|validation_error|layout_changed|popup|network|unknown","user_action_vi":"...1-2 câu hướng dẫn thao tác..."}
Không bao giờ khuyên bấm "Submit ASN"."""

USER_EXPLAIN = """Bước: {step_id} — {step_title_vi}
Lỗi kỹ thuật: {error_text}
URL: {page_url}
--- ACCESSIBILITY SNAPSHOT ---
{aria_snapshot}
--- DOM ---
{dom_excerpt}"""

SYSTEM_READ_FIELDS = """You read values from a screenshot of a purchase-order document. Return ONLY JSON: {"values":{"<field>":"<exact text as printed or empty string>"},"confidence":0.0}. Copy dates exactly as printed (e.g. 09-MAR-26)."""
USER_READ_FIELDS = """Fields to read: {fields}
Hint: {hint}"""
```

### 6.9 Cost control & redaction (implemented across WP-B/WP-C)

- AI is called only: (a) after a locator failure for a key (once per step attempt), (b) to explain a failure before pausing, (c) as rung 3 of the date ladder. Never in the happy path.
- `AiConfig.max_calls_per_run` (default 8) enforced by `Healer`; `max_tokens` 800; screenshots JPEG q=55 at the 1280×900 viewport (~80–150 KB); aria/DOM truncated to 12 k chars each.
- Redaction: password values and e-mail addresses masked (§4.8); API keys never logged; prompts logged at DEBUG without the image.
- When `vision` is off, requests contain no image and `supports_vision=False` makes `Healer.read_dates` skip rung 3.

### 6.10 README_VI.md (WP-C) — required sections

1. Giới thiệu & cảnh báo an toàn (công cụ không bao giờ bấm Submit ASN; không nhập mật khẩu).
2. Cài đặt: bản portable (giải nén, chạy `EDI Assistant.exe`) và bản cài đặt (`EDI-Assistant-Setup-x.y.z.exe`); yêu cầu Microsoft Edge; cài Chromium dự phòng.
3. Lần đầu: đăng nhập EDI Gateway trong trình duyệt tích hợp; thêm nhà máy.
4. Quy trình hằng ngày: chọn Excel → kiểm tra ánh xạ → kiểm tra bảng → Bắt đầu → xử lý hộp thoại tạm dừng → nhận thông báo → kiểm tra & Submit thủ công.
5. Chế độ chạy thử; chế độ mock (`python -m edi_assistant.mock_edi`).
6. Hiệu chỉnh bộ chọn (calibrate) khi trang web thay đổi.
7. Cấu hình AI (tuỳ chọn) và chi phí.
8. Vị trí dữ liệu (`%APPDATA%\EDI Assistant` hoặc thư mục `data` cạnh exe), nhật ký, kết quả CSV.
9. Khắc phục sự cố (bảng lỗi → cách xử lý).

---

## 7. Packaging & distribution (WP-C)

### 7.1 Outputs (same PyInstaller build)

1. **Primary:** `dist/EDI-Assistant-portable-{version}.zip` — contents: `EDI Assistant/` one-folder build + `portable.flag` + `README_VI.md`. Unzip anywhere, run `EDI Assistant.exe`; all data under `EDI Assistant/data/`.
2. **Secondary:** `dist/EDI-Assistant-Setup-{version}.exe` — Inno Setup, per-user.

### 7.2 PyInstaller (`packaging/edi_assistant.spec`)

- Entry `edi_assistant/__main__.py`, `name='EDI Assistant'`, `console=False`, `icon='edi_assistant/app/resources/app.ico'`, `version='packaging/version_info.txt'` (generated from `__version__` by the build script), one-folder (`COLLECT`), `upx=False`.
- `datas`: `edi_assistant/automation/selectors.yaml`, `edi_assistant/automation/picker.js`, `edi_assistant/app/resources/*`, `README_VI.md`.
- `hiddenimports`: `edi_assistant.mock_edi`, `pypdf`, `winsound`.
- Playwright: `packaging/hooks/hook-playwright.py` using `collect_data_files('playwright', include_py_files=False)` **plus** the driver directory `playwright/driver/**` (node executable + `package/`) via `collect_data_files('playwright', subdir='driver')` and `hookspath=['packaging/hooks']`. Verify after build that `dist/EDI Assistant/_internal/playwright/driver/node.exe` and `.../driver/package/cli.js` exist (build script asserts this). Browsers are **not** bundled: Edge channel is default; chromium is downloaded on demand into `paths.playwright_browsers_dir()` (§6.6).
- PySide6: exclude `QtWebEngine*`, `Qt3D*`, `QtQuick*`, `QtMultimedia*`, `QtPdf*` via `excludes` to keep the folder ≈ 150 MB.

### 7.3 `packaging/build_windows.ps1`

Steps (fail fast, `$ErrorActionPreference='Stop'`): `python -m venv .venv` (if missing) → `.venv\Scripts\pip install -e .[dev]` → read `__version__` → write `version_info.txt` → `pyinstaller packaging/edi_assistant.spec --clean --noconfirm` → assert driver files → copy `portable.flag` + README into `dist/EDI Assistant/` → `Compress-Archive` → if `iscc.exe` on PATH: `iscc /DMyAppVersion=$ver installer/edi_assistant.iss` → print artifact paths. Parameters: `-SkipInstaller`, `-Version`.

### 7.4 `installer/edi_assistant.iss`

- `AppId={{B5B7B8D2-6C1B-4F4C-9E7B-EDIASSIST0001}`, `AppName=EDI Assistant`, `AppVersion={#MyAppVersion}`, `DefaultDirName={localappdata}\Programs\EDI Assistant`, `PrivilegesRequired=lowest`, `OutputBaseFilename=EDI-Assistant-Setup-{#MyAppVersion}`, `ArchitecturesInstallIn64BitMode=x64compatible`, `SetupIconFile`, `UninstallDisplayIcon`.
- `[Files]` `dist\EDI Assistant\*` recursesubdirs (without `portable.flag`).
- `[Icons]` Start Menu + optional desktop (`Tasks: desktopicon`).
- `[Tasks]` `desktopicon`, `autostart` ("Khởi động cùng Windows").
- `[Registry]` when `autostart`: HKCU `Software\Microsoft\Windows\CurrentVersion\Run`, `EDIAssistant` = `"{app}\EDI Assistant.exe" --minimized`, `uninsdeletevalue`.
- `[UninstallDelete]` nothing in `%APPDATA%`; `[Code]` `CurUninstallStepChanged(usPostUninstall)`: `MsgBox('Xoá dữ liệu người dùng (cấu hình, mẫu, nhà máy) trong %APPDATA%\EDI Assistant và %LOCALAPPDATA%\EDI Assistant?', mbConfirmation, MB_YESNO)` → `DelTree` both if Yes.
- Languages: default + Vietnamese messages for the custom strings (keep `Languages` default English; custom messages in Vietnamese via `[CustomMessages]`).

### 7.5 CI — `.github/workflows/build-windows.yml`

`on: [push (tags v*), workflow_dispatch]`, `runs-on: windows-latest`, steps: checkout → `actions/setup-python@v5` (3.12) → `choco install innosetup -y --no-progress` → `pwsh packaging/build_windows.ps1` → `actions/upload-artifact@v4` with `dist/*.zip` and `dist/*.exe` → on tag: `softprops/action-gh-release@v2` attaching both.

### 7.6 Runtime flags

`EDI Assistant.exe --minimized` (start in tray), `--mock` (force `site.use_mock=True` for this session and auto-start the mock server in-process on a free port), `--data-dir PATH` (overrides `EDI_ASSISTANT_DATA_DIR`).

---

## 8. Testing plan, acceptance criteria, integration order

### 8.1 WP-A (`tests/data/`)

- `test_excel_sample.py`: on the sample file: `detect_header` → `header_rows == [3,4]`, 7 columns, Packages span 2; `suggest_mapping` maps all 7 fields with score ≥ 0.85; `extract_rows` → 2 lines (`580367401`, `580367301` after `assign_line_numbers`), `packages == 85`, `quantity == 510`, `gross_weight == Decimal('1020.00')`, row 7 and 8 skipped; `company_text == 'SUMEC TEXTILE COMPANY LIMITED'`.
- `test_values.py`: all examples in §3.7 incl. `'1,020     PCS'`, `5803674.0`, `'580367401'`, `'5803674-02'`.
- `test_templates.py`: learn → find exact; rename a header slightly → similar ≥ 0.75; store roundtrip JSON equals schema in §3.6.
- `test_dates.py`: strategies A/B/C with the PDF-like text `"Order Date Early Ship Date Late Ship Date 10-JAN-26 09-MAR-26 13-MAR-26"`; midpoint examples; intersection/no-intersection; past-date rule.
- `test_quantities.py`: 1002/167 with prepack 6 → (1,167); without → (6,167); 500/85 → error flag; `check_ordered` cases.
- `test_planner.py`: per_file vs per_master_po; duplicate line error; weight modes.
- `test_factories.py`: suggest by partial name ("SUMEC TEXTILE" vs saved "Sumec Textile Co., Ltd") ≥ 0.5; footer parsing example.
- `test_paths_config.py`: portable detection via tmp dir with `portable.flag` (monkeypatch `exe_dir`), config roundtrip with unknown keys.

Acceptance: `pytest tests/data` green on macOS and Windows; no imports of Qt/Playwright in `core`/`data`.

### 8.2 WP-B (`tests/automation/`)

- `conftest.py`: fixtures `mock_server` (random free port, `MockOptions(require_login=False)`), `mock_server_login`, `mock_server_pdf` (`dates_in_pdf=True`), `tmp_data_dir` (sets `EDI_ASSISTANT_DATA_DIR`), `selectors_store`.
- `test_selectors.py`: YAML validates (all keys, no unknown placeholders, exactly the key list of §4.5); merge order learned→bundled; resolver fallback order using a static HTML page (`page.set_content`).
- `test_dialogs.py`: unexpected confirm dismissed; armed accept works; "submit" confirm always dismissed.
- `test_actions_guard.py`: clicking `input[name=btnSubmitASN]` raises `ForbiddenActionError`; route block aborts `asn.do`.
- `test_mock_pages.py`: every route renders, titles exact, field names present (parse with `html.parser`).
- `test_e2e_mock.py` (marker `e2e`, headless chromium): plan with 2 lines (`580367401`, `580367301`), one shipment, factory CHINA → `FlowRunner.run` with a scripted `ask_user` that answers `continue` for `finished_review`/`dry_run_stop` and fails the test for anything else. Assert mock state: header fields (`OptShippingType=3`, `txtShippingDate=03/11/2026`, `OptTransMethod=O`, `OptSCACCode=MAEU`, carrier `MAERSK`, BOL/PRO `Unknown`, From fields), both POs added, `complete_partial == Partial`, carton `packaging_code == PCC`, `qty_per_carton == 6`, `cartons_per_site == 85`, weights `1020.00`/`KG`, `submit_called is False`, `RunResult.status == 'done'`, `web_shipment_id` numeric, results.csv has 2 rows. Variants: `dates_in_pdf=True` (rung 2 used — assert log source `pdf`); prepack PO `668254501` (qty 1002/167 → qpc 1, cps 167); login required (scripted `ask_user` logs in by filling the mock password itself via a *separate* page — the tool code must not); `dry_run=True` (no shipment in mock state); replaced-only PO → `DataMismatchError` → `step_failed` → scripted `skip`.
- `test_healing.py`: fake `VisionAdvisor` returning a CSS candidate; break a bundled key (monkeypatch) → healer learns it; budget exhaustion returns None.
- `test_calibrate.py`: picker JS generates expected candidates for an element with id/name (page.set_content).

Acceptance: e2e green headless on macOS and Windows CI; the run against the mock finishes in < 90 s.

### 8.3 WP-C (`tests/app/`)

- `test_bridge.py`: `sink` from a worker thread → signal received in GUI thread (pytest-qt `qtbot.waitSignal`).
- `test_mapping_dialog.py`: dialog pre-fills from scores; result mapping correct.
- `test_settings_dialog.py`: preset selection fills fields; roundtrip to `AppConfig`.
- `test_ai_clients.py`: `httpx.MockTransport` for both providers: request body shape (image block present/absent, no `temperature` for Anthropic), JSON parsing with fences, non-2xx → `AiError`, garbage → `None`.
- `test_pause_dialog.py`: options → buttons; input fields → values.
- Manual acceptance (Windows): portable zip runs from Desktop with no install; data created under `EDI Assistant/data/`; second launch focuses the first; tray notification + sound appear at run end; installer installs per-user, creates shortcuts, uninstall keeps data when "No".

### 8.4 Integration order

1. **Day 0 (hour 1):** WP-A commits `pyproject.toml`, `__init__.py`, and `core/*` contracts verbatim. WP-B commits `selectors.yaml` skeleton with the exact key list. WP-C commits `strings_vi.py` skeleton.
2. **Milestone 1:** WP-A `data` complete with tests; WP-B mock server + selectors + session + actions with tests; WP-C window shell + settings + bridge against a `FakeWorker`.
3. **Milestone 2:** WP-B `FlowRunner` e2e green on mock. WP-C swaps `FakeWorker` for `AutomationWorker` with `--mock`. First integrated run: GUI → mock.
4. **Milestone 3:** AI clients wired; healing test with a real provider key (manual); calibrate dialog end-to-end on mock.
5. **Milestone 4:** Windows build (portable + installer) via CI; manual test on a Windows 11 machine with Edge; README_VI finalised.
6. **Milestone 5 (with the user):** calibrate the unverified keys on the real site (PO detail, Search POs tab, Carton page) in dry-run; then first real dry-run; then first real run on one PO.

---

## 9. Open risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Unverified real selectors (PO detail, Search POs tab, Carton page) | Flow pauses often on first real use | Label/text candidates from screenshots; calibrate dialog sorts unverified keys first; self-healing; every step idempotent so the user can finish a step manually and press Continue. Milestone 5 budget reserved. |
| PO detail dates inside a PDF viewer (Chrome/Edge PDF plugin) | DOM regex finds nothing | Ladder §4.10 (PDF fetch with session cookies + pypdf → AI vision → manual input). Mock covers the PDF variant. |
| Row controls keyed by internal ids | Static selectors impossible | `RowKeyExtractor` derives `N`/`M` from any control inside the row located by PO text. |
| Dialogs: `confirm()` vs new windows/popups (e.g. "More.." countries, displayIds) | Flow stalls | `DialogPolicy` dismiss-by-default + armed accept; `context.on('page')` adopts popups as current page; country not in list → explicit `needs_user`. |
| Session timeout mid-run | Steps fail on login page | Every failure path checks `is_login_page()` → `login_required` pause → S0 logic → retry step. The tool never types the password. |
| "Selected Purchase Orders >>" also saves the header | Double save | S7 only clicks it when not already on the POs page; S6 saves explicitly first and captures the id. |
| Shipping date validation (`validateShippingDate`, "cannot be in the past") | Save rejected | `compute_shipping_date` clamps to today; `ship.error_text` postcondition surfaces server messages; pause lets the user fix the date. |
| Weight page paging (>10 lines) | Rows not found | `orderperpage=All` selected first when > 10 lines. |
| Opening `view_order.do` marks the PO as read | Side effect | Accepted (documented in README). Dry-run also opens PO pages. |
| Edge not installed / corporate policy blocks persistent profile | Browser launch fails | Fallback to bundled chromium download into local data dir; clear Vietnamese error with the install button. |
| AI cost/leak | Unexpected spend / data exposure | Budget per run, failure-only calls, redaction, AI off by default, provider/base_url user-controlled (local Ollama possible). |
| Weight semantics (docx says master-carton weight, user says total G.W.) | Wrong weights | `flow.weight_mode` default `total_gw` per the binding decision; `per_carton_gw` available in settings. |
| PyInstaller + Playwright driver | Frozen app cannot launch browser | Explicit hook bundling `driver/node.exe` + `package/`; build script asserts; `PLAYWRIGHT_BROWSERS_PATH` set before import. |
| Portable folder on a read-only location | Cannot write data | On write failure to `<exe_dir>/data`, `paths.user_data_dir()` falls back to `%APPDATA%` and logs a warning (implement in `user_data_dir`: test-write a temp file). |

---

## 10. PO-tracker input (v2) — delta spec

Status: **binding delta** on top of §2–§9 and REVIEW.md §5–§7. Everything here is *additive*: no existing field, function
signature, selector key, event name or test is removed; defaults keep the old packing-list behaviour byte-for-byte unless
a profile says otherwise. Implementers apply this section without re-deriving anything from the workbook.

### 10.0 What changed and why (summary of decisions)

| # | Decision | Rationale |
|---|---|---|
| D1 | Input **profiles**: `po_tracker` (new default when detected) and `packing_list` (existing). Auto-detected from the header fingerprint, manual override in the mapping dialog, stored in the template. | Both files must keep working; the tracker has no cartons/total-weight columns, the packing list has no dates/pack/ASN columns. |
| D2 | The tracker row is **mapped onto the existing `POLine` numbers**: `quantity = Order Units (J)`, `packages = J / Pack (Q)` (must be an integer), `gross_weight = Gross Weight/Carton (T)` with a new weight mode `per_carton_as_is`. New fields hold the raw tracker values. | `compute_carton_plan(quantity, packages, prepack)` then yields exactly the user's rule (`qpc = Q`, `cps = J/Q`) and every consumer (planner, results.csv, S8, S9, plan table) keeps working with minimal edits. |
| D3 | Ship window per line from Excel (`M`/`N`); planner pre-fills `ShipmentPlan.po_windows` and marks `dates_source="excel"`. `S3` becomes a **non-blocking cross-check** in that case (DOM/PDF rungs only, warn on mismatch). `S1`/`S2` stay because `Create New Shipment` lives on the PO detail page. | User rule: Excel dates are authoritative; the web ladder must never block when Excel dates exist. |
| D4 | Carton numbers are **reconciled at runtime** on the carton page with `core/quantities.decide_carton(...)`: web `Qty Ordered == J` → `qpc=Q, cps=J/Q`; `== J/Q` → `qpc=1, cps=J/Q`; anything else → pause with details. Invariant checked before Save: `qpc × cps == web Qty Ordered` (in the web's unit). | User's procedure rule. |
| D5 | **One shipment per master PO** for the tracker profile (grouping forced, radio disabled). The runner's existing per-shipment loop + `Pacer.before_shipment` is kept; **per-shipment failure isolation** is added. | A run may contain several shipments; one bad PO must not kill the others. |
| D6 | Lines whose `ASN #` (F) is non-empty are **unselected by default** (`already_has_asn`); the plan table gets per-line checkboxes that toggle per master PO. | Tracker is a living document re-run many times. |
| D7 | **Factory per run** (no factory column): combo pre-selects `ui.last_factory_id`; saved at Start. | User rule. |
| D8 | **Write-back** goes into column F (`ASN #`) of a timestamped **copy** `<stem>_ASN_<YYYYMMDD-HHMMSS>.xlsx` next to the original (fallback `runs/<run_id>/`), written on every `ShipmentCreated` and at `RunFinished`, one cell per line row. Column AB `Submit ASN # (w/ Date)` is never written. The packing-list profile keeps `<stem>_ASN.xlsx` + appended `ASN` column (existing tests untouched). | Never modify the original; the user pastes ASNs into the master tracker after submitting. |
| D9 | Mock gets `MockState.seed_tracker()` with the nine tracker POs (one prepack variant) and dates equal to the Excel windows. | Deterministic multi-shipment e2e. |

### 10.1 The workbook (verified with openpyxl, formulas and `data_only`)

File `docs/Copy of 6102 - Q4 Pet Beds Current - MDDP-PO tracker-1009 - 副本.xlsx`, single sheet **`'Vendor '`** (note the trailing
space), dimensions `A1:AL35`, `freeze_panes="A2"`, **`auto_filter.ref == "A1:AL10"`**.

Header row 1 (exact texts, some with trailing spaces):
`A Container | B Shyft SO # | C Shyft PO # | D Master PO # | E Line # | F ASN # | G Model # | H 'Styles Description ' | I Color |
J Order Units | K Order Price ($) | L Order Cost (Units x Cost) | M EDI PO Start Ship | N EDI PO End Ship | O X-Factory Date |
P EDI Units | Q Pack | R Transfer PO (w/ Dates) | S Pre Price Stickers (w/ Date) | T Gross Weight/Carton(kg) | U Maersk Confirmation # |
V UCC Label (w/ Date) | W 'Shipping Marks (w/ Dates) ' | X Hang Tags (w/ Dates) | Y 'Saliling Date (MM/DD/YYYY) ' | Z 'Estimate Arrival Date (MM/DD/YYYY) ' |
AA Bill of Lading | AB Submit ASN # (w/ Date) | AC Invoice (w/ Date) | AD Seal # | AE ISF (Y/N) | AF CI (w/ Link) | AG PL | AH Shipment Reference # |
AI Port ETA | AJ Paid | AK Notes | AL PDF Source (for traceability)`

Data rows 2–10 (9 lines, 7 master POs):

| row | A | D | E | F | G | J | M | N | Q | T |
|---|---|---|---|---|---|---|---|---|---|---|
| 2 | Container 9 | 5820678 | '01' | **872295** (int) | PMLB015KL | 1428 | '30-NOV-26' | '04-DEC-26' | 6 | 12 |
| 3 | *(merged A2:A3)* | *(merged D2:D3)* | '02' | `''` | PMLB016OG | 960 | '30-NOV-26' | '04-DEC-26' | 6 | 10 |
| 4 | Container 10 | 5820680 | '01' | `''` | PMRT010BC | 1650 | '30-NOV-26' | '04-DEC-26' | 6 | 8 |
| 5 | *(merged)* | *(merged D4:D5)* | '02' | `''` | PMLB016OG | 714 | '30-NOV-26' | '04-DEC-26' | 6 | 7 |
| 6 | Container 13 | 5820682 | '01' | `''` | PMCR005WGR | 1518 | '30-NOV-26' | '04-DEC-26' | 6 | 10 |
| 7 | Container 14 | 5820677 | '01' | `''` | PMCR004BC | 2388 | '09-NOV-26' | '13-NOV-26' | 6 | 12 |
| 8 | *(merged)* | *(merged D7:D8)* | '02' | `''` | PMCR005WGR | 330 | '09-NOV-26' | '13-NOV-26' | 6 | 9 |
| 9 | Container 15 | 5820679 | '01' | `''` | PMSC090OGR | 948 | '30-NOV-26' | '04-DEC-26' | 6 | 8 |
| 10 | Container 16 | 5820684 | '01' | `''` | PMSC090OGR | 948 | '30-NOV-26' | '04-DEC-26' | 6 | 6 |

Facts the implementation must handle:
- Merged ranges: `A2:A3 B2:B3 C2:C3 D2:D3`, `A4:A5 … D4:D5`, `A7:A8 … D7:D8` (identity columns), `O2:O3 O4:O5 O7:O8`, and **`R2:R10`, `S2:S10`** (two columns merged over *all* data rows — irrelevant columns, but they prove that "merged" must not be treated as "same PO"). Rows 6, 9, 10 are single-row masters (no merge).
- `D` is an `int` (5820678); `E` is text `'01'`; `F2` is `int 872295`; every other `F` is the **empty string `''`**, not `None`; `M`/`N` are text `DD-MON-YY`; `O` is a `datetime`; `L` is a formula `=J2*K2` (loads as the formula string without `data_only`).
- Row 11 is completely empty. Rows 16–17 are a **second mini-table** (`D16 'Master PO #', E16 'EDI PO Start Ship', F16 'EDI PO End Ship', G16 'X-Factory Date'`; `D17 5820677, E17 '09-NOV-26', F17 '13-NOV-26'`, merged `D17:D18 … G17:G18`). It must never be read as data.
- Baseline of the **current** code on this file (recorded 2026-10-18, before this delta): `detect_header` → `header_rows=[1]`, 38 columns (OK); `suggest_mapping` → `po=C (Shyft PO #)`, `line=E`, `description=H`, `packages=T (Gross Weight/Carton)`, `net_weight=AB (Submit ASN #)`, `quantity=None`, `gross_weight=None` → `MappingIncompleteError`. Row scores: row 1 = 57, row 16 = 10, row 11 = −inf. So header detection needs no change; synonyms, profile-aware required fields and the extractor do.
- All `J / Q` are integers: 238, 160, 275, 119, 253, 398, 55, 158, 158.
- Windows: `30-NOV-26..04-DEC-26` → midpoint `2026-12-02`; `09-NOV-26..13-NOV-26` → `2026-11-11`.

### 10.2 Data model (`core/models.py`) — additive

```python
FIELD_KEYS: tuple[str, ...] = ("po", "line", "description", "packages", "quantity", "gross_weight", "net_weight", "size",
                               # v2 (tracker)
                               "asn", "model_no", "start_ship", "end_ship", "pack", "gw_per_carton", "container")
REQUIRED_FIELDS = ("po", "packages", "quantity", "gross_weight")            # unchanged = packing_list requirements
PROFILES: tuple[str, ...] = ("packing_list", "po_tracker")
REQUIRED_BY_PROFILE: dict[str, tuple[str, ...]] = {
    "packing_list": REQUIRED_FIELDS,
    "po_tracker":   ("po", "line", "quantity", "pack", "gw_per_carton", "start_ship", "end_ship"),   # "asn" optional but strongly suggested
}
OPTIONAL_BY_PROFILE = {"packing_list": ("line", "description", "net_weight", "size"),
                       "po_tracker": ("asn", "model_no", "description", "container")}

@dataclass(slots=True)
class POLine:                      # existing fields unchanged; new fields appended WITH defaults
    ...
    # v2 additive
    line_no_text: str = ""         # raw 'Line #' cell text ('01'); informational
    model_no: str = ""             # G 'Model #'
    order_units: Decimal | None = None   # J as read (== quantity for the tracker profile)
    pack_qty: Decimal | None = None      # Q 'Pack' (units per carton)
    gw_per_carton: Decimal | None = None # T as read, KG per carton
    start_ship: date | None = None       # M
    end_ship: date | None = None         # N
    existing_asn: str = ""               # F as text; "" when empty/whitespace
    container: str = ""                  # A (inherited through merges)
    source_row: int = 0                  # == excel_row (alias kept for the tracker write-back; set equal in both profiles)
    selected: bool = True                # plan selection (UI checkbox); default = not existing_asn for the tracker profile
    @property
    def window(self) -> DateWindow | None: ...   # DateWindow(start_ship, end_ship) if both set (swapped if reversed) else None

@dataclass(slots=True)
class ShipmentPlan:
    ...
    # v2 additive
    container: str = ""                  # first non-empty container of its lines (label only)
    dates_source: str = "web"            # "excel" (po_windows pre-filled by the planner) | "web" (S3 ladder as before)
    planned_ship_date: date | None = None  # preview computed by the planner when dates_source == "excel"; S4 recomputes at run time
    writeback_done: bool = False         # GUI bookkeeping (set after a successful incremental write-back)

@dataclass(slots=True)
class RunPlan:
    ...
    profile: str = "packing_list"        # v2
    qty_strict: bool = False             # v2: True for po_tracker → any qpc*cps != web Qty Ordered pauses (not only "over")

@dataclass(slots=True)
class CartonPlan:
    ...
    web_rule: str = ""                   # v2: "" | "units" (web == quantity) | "packs" (web == packages) | "prepack" | "unknown" | "mismatch"
```

Consumers to update (every place that constructs or reads these):
- `data/rows.py::extract_rows` (sets `source_row = excel_row`, `selected = True`), new `data/tracker_rows.py` (all new fields).
- `data/planner.py` (selection filter, grouping, weight mode, windows, `planned_ship_date`, `profile`, `qty_strict`, label with container).
- `data/results.py::HEADER` — append **at the end** `container, model_no, excel_asn, profile` (test `test_results_csv` only checks the prefix and row count → still green). `write_json` is generic (`asdict`) → new fields serialise automatically; `load_run_history` unchanged.
- `automation/flow/steps.py` S3/S4/S8/S10 (see §10.5), `flow/runner.py` (isolation), `flow/context.py::vars` adds `model_no` and `container` keys (harmless extra placeholders).
- `app/widgets/plan_table.py`, `app/main_window.py`, `app/dialogs/mapping_dialog.py` (§10.7).
- `tests/automation/wpb_helpers.py::make_line` keeps working (defaults); add `make_tracker_line` helper there.
- `mock_edi` does not import `core.models` (unchanged rule).

### 10.3 Mapping, synonyms, profile detection, extraction

#### 10.3.1 `data/synonyms.py`

Add the new keys and strengthen the existing ones (normalised with `normalize_header`, so `'Gross Weight/Carton(kg)'` →
`'gross weight carton kg'`, `'Master PO #'` → `'master po'`, `'ASN #'` → `'asn'`, `'Line #'` → `'line'`):

```python
SYNONYMS.update({
  "po":           SYNONYMS["po"] + ["master po", "master po no", "master po number", "burlington po", "customer po"],
  "quantity":     SYNONYMS["quantity"] + ["order units", "ordered units", "order qty", "ordered qty", "units ordered"],
  "asn":          ["asn", "asn no", "asn number", "asn id", "web shipment id", "số asn", "mã asn"],
  "model_no":     ["model", "model no", "model number", "vendor style", "sku", "sku no", "型号", "mã model"],
  "start_ship":   ["edi po start ship", "start ship", "start ship date", "early ship date", "early ship", "ship window start",
                   "ngày bắt đầu giao"],
  "end_ship":     ["edi po end ship", "end ship", "end ship date", "late ship date", "late ship", "ship window end",
                   "ngày kết thúc giao"],
  "pack":         ["pack", "pack qty", "pack size", "inner pack", "qty per carton", "units per carton", "pcs per carton",
                   "pcs ctn", "装箱数", "sl mỗi thùng"],
  "gw_per_carton":["gross weight carton kg", "gross weight carton", "gw carton", "gw per carton", "gross weight per carton",
                   "carton gross weight", "gw ctn", "毛重 每箱", "trọng lượng mỗi thùng"],
  "container":    ["container", "container no", "container number", "cntr", "柜号", "số container"],
})
# Negative tokens: a header containing any of these tokens can never map to that field (score forced to 0).
NEGATIVE_TOKENS: dict[str, tuple[str, ...]] = {
    "asn": ("submit",),            # 'Submit ASN # (w/ Date)' (AB) must never be mapped/written
    "po": ("transfer", "start", "end", "shyft"),   # 'Transfer PO (w/ Dates)', 'EDI PO Start/End Ship', 'Shyft PO #'
    "packages": ("weight", "gross"),               # 'Gross Weight/Carton(kg)' is not a carton count
    "quantity": ("edi",),                          # 'EDI Units' (P) exists but J is authoritative
}
```

Scoring change in `field_scores` (keeps every §3.3 example green):
- apply `NEGATIVE_TOKENS` first (token set intersection → 0 for that field);
- the 0.7 substring rule now requires the synonym to contain **no space** or be ≥ 5 chars (kills `'n w' ⊂ 'asn w date'`);
- rest unchanged. Expected scores on the tracker headers after the change: `D master po → po 1.0`, `C shyft po → po 0.0`,
  `E line → line 1.0`, `F asn → asn 1.0`, `AB → asn 0.0, net_weight 0.0`, `G model → model_no 1.0`, `H styles description → description 0.85`,
  `J order units → quantity 1.0`, `M → start_ship 1.0`, `N → end_ship 1.0`, `Q pack → pack 1.0 (packages 0.7, loses)`,
  `T gross weight carton kg → gw_per_carton 1.0 (gross_weight 0.85, packages 0)`, `A container → container 1.0`.
  Add these as `tests/data/test_synonyms_tracker.py`.

#### 10.3.2 `data/mapping.py`

```python
@dataclass(slots=True)
class ColumnMapping:
    columns: dict[str, ColumnRef | None]
    profile: str = "packing_list"                        # v2
    def required(self) -> tuple[str, ...]: return REQUIRED_BY_PROFILE[self.profile]
    def missing_required(self) -> list[str]: return [k for k in self.required() if self.columns.get(k) is None]
    # is_complete unchanged (uses missing_required)

def suggest_mapping(det, profile: str | None = None) -> tuple[ColumnMapping, dict[str, float]]:
    """Unchanged algorithm; afterwards mapping.profile = profile or detect_profile(det, scores)[0]."""
def apply_template_to_detection(tmpl, det) -> ColumnMapping:   # also copies tmpl.profile
def validate_mapping(m) -> None                                 # unchanged; message lists the profile's required fields
```

#### 10.3.3 `data/profiles.py` (new)

```python
TRACKER_SIGNATURE = ("pack", "gw_per_carton", "start_ship", "end_ship", "asn")

def detect_profile(det: HeaderDetection, scores: dict[str, float] | None = None) -> tuple[str, float]:
    """scores = suggest_mapping scores (computed if None, without recursion: use the raw per-column field_scores).
    hits = #{k in TRACKER_SIGNATURE : scores[k] >= 0.85} + (1 if the column mapped to 'po' has normalized header starting with 'master po')
    return ("po_tracker", hits/6) if hits >= 3 else ("packing_list", 1 - hits/6)."""
def profile_label(profile: str) -> str          # "PO tracker" | "Packing list" (English; UI translates via strings)
def default_weight_mode(profile: str, cfg_flow) -> str:
    return cfg_flow.tracker_weight_mode if profile == "po_tracker" else cfg_flow.weight_mode
def forced_grouping(profile: str, requested: str) -> str:
    return "per_master_po" if profile == "po_tracker" else requested
```
On the tracker: hits = 6 → `("po_tracker", 1.0)`; on the packing-list sample: hits = 0 → `("packing_list", 1.0)`.

#### 10.3.4 `data/templates.py`

`Template.profile: str = "packing_list"` (JSON key `"profile"`, missing → `"packing_list"`, `version` stays 1).
`learn(...)` stores `mapping.profile`; `to_mapping()` restores it. `compute_fingerprint` unchanged (the tracker's 38
normalised headers give a distinct fingerprint).

#### 10.3.5 `data/excel_reader.py` — additive grid facts

```python
@dataclass(slots=True)
class SheetGrid:
    ...
    merged_parent: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)  # child (r,c) -> top-left (r0,c0)
    auto_filter_ref: str = ""                                                           # e.g. "A1:AL10"
    def get_merged(self, row, col) -> object:
        """value of the merged range covering (row,col) when (row,col) is a child; else get(row,col)."""
    def is_blank(self, row, cols: Iterable[int] | None = None) -> bool:
        """True when every cell in `cols` (default: all) is None or a str that is empty after strip()."""
    def filter_last_row(self) -> int | None:     # max_row of auto_filter_ref if it parses, else None
```
`load_grid` fills `merged_parent` from `ws.merged_cells.ranges` and `auto_filter_ref = ws.auto_filter.ref or ""`.
`text_blobs()` unchanged. Existing callers unaffected.

#### 10.3.6 `data/values.py`

```python
def parse_date_cell(v: object) -> date | None:
    """datetime/date → .date(); str → strip, try parse_date_token (DD-MON-YY/YYYY, MM/DD/YYYY, YYYY-MM-DD), then
    '%d-%b-%y', '%d-%b-%Y', '%m/%d/%y', '%d/%m/%Y' (last only if month > 12 in the mdy reading); numbers → None (openpyxl already
    converts dated number formats). '30-NOV-26' → date(2026,11,30)."""
def parse_text_or_blank(v: object) -> str      # None/''/whitespace → ""; int/float integral → digits; else str(v).strip()
```

#### 10.3.7 `data/tracker_rows.py` (new) — `extract_tracker_rows(grid, det, mapping) -> RowExtraction`

`rows.extract_rows` dispatches: `if mapping.profile == "po_tracker": return extract_tracker_rows(grid, det, mapping)`
(single added line; the packing-list branch is untouched).

Algorithm (exact):

```
validate_mapping(mapping)                                   # profile-aware required set
cols  = {key: col_index(ref.letter) for key, ref in mapping.columns.items() if ref}
hdr   = max(det.header_rows); first = det.data_start_row
last_hint = grid.filter_last_row()                          # 10 for the sample; None when no auto-filter
header_norms = {normalize_header(c.joined) for c in det.columns}
identity_cols = [cols[k] for k in ("container", "po") if k in cols]   # merged-inheritance only for these (+ 'Shyft SO/PO' are not mapped)
prev_master = ""; prev_container = ""
lines = []; skipped = []; flags = []
for r in range(first, grid.max_row + 1):
    # --- end-of-table detection (in this order)
    if grid.is_blank(r, cols.values()) and grid.is_blank(r, identity_cols): break          # first fully blank row ends the table
    if last_hint and r > last_hint: break                                                   # respect auto-filter ref
    # header-text row inside the data (second table): any mapped cell equals a header text → stop
    if any(normalize_header(grid.get(r, c)) in header_norms for c in cols.values() if isinstance(grid.get(r, c), str)): break
    # --- identity with merged inheritance
    po_raw = grid.get_merged(r, cols["po"])                 # D2 for row 3 through merged_parent
    if po_raw is None or (isinstance(po_raw, str) and not po_raw.strip()):
        if prev_master:                                     # forward-fill (no merge, blank cell under a master)
            po_raw = prev_master; inherited = True
    parsed = parse_po_cell(po_raw)
    if parsed is None: skipped.append((r, "No master PO")); flags.append(Flag("totals_row_skipped", f"Skipped Excel row {r} (no PO)", "info")); continue
    master, _ = parsed                                      # a 9-digit D would carry the line; the tracker uses E
    line = parse_line_cell(grid.get(r, cols["line"]))
    if line is None: pl.flags += Flag("line_missing", f"Row {r}: Line # unreadable", "error")   # keep the row, red
    container = parse_text_or_blank(grid.get_merged(r, cols["container"])) if "container" in cols else ""
    if not container and master == prev_master: container = prev_container
    # --- numbers
    J = parse_decimal(get(cols["quantity"])); Q = parse_decimal(get(cols["pack"])); T = parse_decimal(get(cols["gw_per_carton"]))
    errors: J None/<=0 → Flag("non_integer_units", "Order Units unreadable", error); Q None/<=0 → Flag("pack_invalid", error)
    cartons = J / Q if both ok else Decimal(0);  if cartons not integral → Flag("non_integer_units", f"Order Units {J} not divisible by Pack {Q}", error)
    T None or <= 0 → Flag("weight_zero", warning) and T = Decimal(0)
    # --- dates
    start = parse_date_cell(get(cols["start_ship"])); end = parse_date_cell(get(cols["end_ship"]))
    if start is None or end is None: Flag("dates_missing_excel", f"Row {r}: ship window missing/unreadable", "warning")  # S3 ladder will run for this master
    if start and end and start > end: swap + Flag("dates_swapped", info)
    # --- asn / selection
    asn = parse_text_or_blank(get(cols["asn"])) if "asn" in cols else ""      # 872295 → "872295", '' → ""
    pl = POLine(master_po=master, line=line or 0, excel_row=r, description=to_text(H), packages=cartons, quantity=J or 0,
                gross_weight=T, raw=raw, model_no=to_text(G), order_units=J, pack_qty=Q, gw_per_carton=T,
                start_ship=start, end_ship=end, existing_asn=asn, container=container, source_row=r,
                line_no_text=to_text(E), selected=(asn == ""))
    if asn: pl.flags.append(Flag("already_has_asn", f"Row {r} already has ASN {asn}", "info"))
    if inherited: pl.flags.append(Flag("master_po_inherited", f"Row {r}: master PO {master} inherited from the row above", "info"))
    lines.append(pl); prev_master, prev_container = master, container
# no assign_line_numbers for this profile (line is explicit); duplicates of (master,line) → Flag("duplicate_line", error) on both rows
return RowExtraction(lines, skipped, company_text="", flags)      # no factory text in a tracker
```

Expected on the sample: 9 lines, ids `582067801, 582067802, 582068001, 582068002, 582068201, 582067701, 582067702, 582067901, 582068401`;
`lines[0].existing_asn == "872295"` and `selected is False`; `lines[1].container == "Container 9"`, `master_po == "5820678"`;
`lines[0].packages == 238`, `quantity == 1428`, `gross_weight == 12`, `start_ship == date(2026,11,30)`, `end_ship == date(2026,12,4)`;
no line from rows ≥ 11; `skipped == []`; loop stops at row 11 (blank) before ever seeing row 16.

New flag codes (add to §2.7 table): `already_has_asn` info · `master_po_inherited` info · `pack_invalid` error · `line_missing` error ·
`duplicate_line` error · `dates_missing_excel` warning · `dates_swapped` info · `dates_mismatch_web` warning · `web_qty_unknown` warning ·
`web_counts_packs` info · `qty_mismatch_web` error · `model_mismatch_web` warning · `shipment_failed` error · `not_selected` info.

### 10.4 Planner & quantities

#### 10.4.1 `data/planner.py`

```python
@dataclass(slots=True)
class PlanOptions:
    grouping: str
    dry_run: bool
    weight_mode: str
    profile: str = "packing_list"           # v2
    tracker_weight_mode: str = "per_carton_as_is"   # v2 (from FlowConfig)
    today: date | None = None               # v2: preview clock (tests); None → date.today()

def build_plan(lines, factory, opts, source_file, sheet_name, fingerprint, run_id=None) -> RunPlan:
    sel = [l for l in lines if l.selected]
    if not sel: raise PlanError("No PO lines selected", message_vi="No PO lines selected (all lines already have an ASN?)")
    duplicates check on sel (unchanged)
    grouping = forced_grouping(opts.profile, opts.grouping)
    mode = default_weight_mode(opts.profile, opts)        # "per_carton_as_is" for the tracker
    chunks = per master (order of first appearance) | per file
    for each chunk → _shipment(i, chunk, factory, mode):
        sh.container = first non-empty container; sh.label = f"Shipment {i} ({', '.join(masters)}{', ' + container if container else ''})"
        windows = [l.window for l in chunk if l.window]
        if len(windows) == len(chunk):                     # every line has Excel dates
            sh.dates_source = "excel"
            for master in masters: ws = [l.window for l in chunk if l.master_po == master]; sh.po_windows[master] = intersect(ws) or ws[0]
                 (if intersect(ws) is None → sh.flags += Flag("no_date_intersection", ... lines of the same master, warning))
            res = compute_shipping_date(list(sh.po_windows.values()), opts.today or date.today())
            sh.planned_ship_date = res.shipping_date
            sh.flags += [f for f in res.flags if f.code not in {g.code for g in sh.flags}]   # no duplicate no_date_intersection
        else: sh.dates_source = "web"                      # S1–S3 ladder exactly as today
    plan.profile = opts.profile; plan.qty_strict = (opts.profile == "po_tracker"); plan.grouping = grouping
```

`weight_for_line(line, mode)` in `core/quantities.py` gains `mode == "per_carton_as_is"` → `line.gross_weight` quantised to 0.01
(no division). `FlowConfig.weight_mode` keeps its two values for the packing-list profile; new `FlowConfig.tracker_weight_mode: str = "per_carton_as_is"`
(allowed: `per_carton_as_is` | `total_gw` — the latter only if a future tracker carries totals). Sample: `T=12` → `weight_text "12.00"`.

`plan_summary_rows(plan, all_lines: list[POLine] | None = None) -> list[dict]`: unchanged keys plus `selected` (bool), `container`,
`model_no`, `existing_asn`, `ship_date` (`format_mdy(sh.planned_ship_date)` or `""`), `status_text` (`"already has ASN {asn}"` |
`"not selected"` | `""`). When `all_lines` is given, lines not in the plan are appended in Excel order with `shipment_index == ""`
so the review table can show (and re-tick) them.

#### 10.4.2 `core/quantities.py` — runtime decision

```python
def decide_carton(quantity: Decimal, packages: Decimal, web_ordered: Decimal | None, web_um: str,
                  prepack_units: int | None) -> CartonPlan:
    """Pure. Called by S8 after the carton page has been read. quantity/packages come from POLine
    (tracker: J and J/Q; packing list: Quantity and Packages).
    base = compute_carton_plan(quantity, packages, prepack_units)
    if any error flag in base: base.web_rule = "mismatch"; return base             # non-integer math, unchanged pause path
    if web_ordered is None: base.web_rule = "unknown"; base.flags += [Flag("web_qty_unknown", "Could not read Qty Ordered on the carton page")]; return base
    units_on_web = web_ordered * (prepack_units or 1)
    if units_on_web == quantity:                       # rule A (web counts units) — also the classic prepack case (158 AS × 6 EA == 948)
        base.web_rule = "prepack" if prepack_units else "units"; return base       # qpc = Q (or Q/N), cps = J/Q
    if web_ordered == packages:                        # rule B (web counts packs/cartons, no usable prepack row)
        base.qty_per_carton = 1; base.cartons_per_site = int(packages)
        base.prepack_units = prepack_units or int(base.units_per_carton); base.web_rule = "packs"
        base.flags += [Flag("web_counts_packs", f"Qty Ordered {web_ordered} {web_um} equals the carton count; Qty Per Carton set to 1", "info")]
        return base
    base.web_rule = "mismatch"
    base.flags += check_ordered(quantity, web_ordered, web_um, prepack_units)     # qty_over_ordered / qty_under_ordered as before
    base.flags += [Flag("qty_mismatch_web", f"Qty Per Carton {base.qty_per_carton} × Cartons {base.cartons_per_site} ≠ Qty Ordered {web_ordered} {web_um}", "error")]
    return base

def carton_matches_web(plan: CartonPlan, web_ordered: Decimal | None) -> bool:
    """Invariant from the user's procedure: qpc × cps == web Qty Ordered (in the web's own unit). None → False."""
```
Unit tests (`tests/data/test_quantities.py`, add): `(1428, 238, 1428, 'EA', None)` → `(6, 238, 'units')`; `(1428, 238, 238, 'EA', None)` → `(1, 238, 'packs')`;
`(948, 158, 158, 'AS', 6)` → `(1, 158, 'prepack')`; `(1428, 238, 1400, 'EA', None)` → `web_rule 'mismatch'` with `qty_over_ordered` + `qty_mismatch_web`;
`(1428, 238, None, '', None)` → `'unknown'`; `(1002, 167, 167, 'AS', 6)` → `(1, 167, 'prepack')` (existing docx example still passes through `compute_carton_plan`).

### 10.5 Flow changes (`automation/flow/steps.py`, `runner.py`, `context.py`)

Unchanged: S0, S1, S2, S5, S6, S7, S8b, S9 (S9 already types `line.weight_text`, which the planner now computes per profile), all
safety guards, the dry-run hard stop, `Pacer`.

**S3 `S3.read_dates`** — new behaviour when `ctx.current_shipment.dates_source == "excel"` (`steps.py::S3ReadDates.act`, line ~173):
```
if sh.dates_source == "excel":
    excel_w = sh.po_windows[self.master]
    w = None
    try: w = parse_ship_dates(_collapse(ctx.actions.body_text()))          # rung 1 only …
    except PlaywrightError: pass
    if w is None: w = po_dates._read_pdf(ctx)                               # … and rung 2; NO AI, NO user prompt, ≤ 10 s total
    if w is None: ctx.info(f"dates {self.po}: web dates not readable; using Excel {excel_w.early}..{excel_w.late}")
    elif (w.early, w.late) != (excel_w.early, excel_w.late):
        sh.flags.append(Flag("dates_mismatch_web", f"PO {self.po}: web window {w.early}..{w.late} differs from Excel {excel_w.early}..{excel_w.late}; Excel used"))
        ctx.warn(...)                                                       # never blocks, never overwrites po_windows
    else: ctx.info(f"dates {self.po} confirmed on web")
    return
# else: existing ladder (read_po_dates) unchanged
```
`check()` stays `self.master in sh.po_windows` (true by construction). `po_dates.py` exposes `_read_pdf` as `read_pdf_window(ctx)` (rename alias; keep `_read_pdf`).

**S4** unchanged (it recomputes from `sh.po_windows` with `ctx.today()`; past-date policy applies; for the tracker the result equals
`planned_ship_date` unless the clock moved).

**S8 `S8.create_carton`** — replace lines 442–468 (from `plan = compute_carton_plan(...)` to the `qty_mismatch` ask) by:
```
plan = decide_carton(pl.quantity, pl.packages, ordered, um, prepack)
qpc, cps = plan.qty_per_carton, plan.cartons_per_site
line.carton, line.web_qty_ordered, line.web_um = plan, ordered, um
if any(f.severity == "error" and f.code in ("non_integer_units", "non_integer_prepack") for f in plan.flags):
    (existing non_integer_carton ask with two inputs; skip → StepSkipped)          # unchanged
need_pause = (plan.web_rule in ("unknown", "mismatch")) and (ctx.plan.qty_strict or plan.web_rule == "unknown"
              or any(f.code == "qty_over_ordered" for f in plan.flags))
if need_pause and cfg.pause_on_qty_warning:
    resp = ctx.ask("qty_mismatch",
        f"PO {self.po}: Excel Order Units {pl.order_units or pl.quantity}, Pack {pl.pack_qty or plan.units_per_carton} → Cartons {pl.packages}; "
        f"web Qty Ordered {ordered} {um}" + (f", prepack {prepack} EA" if prepack else "") +
        ". Qty Per Carton × Cartons Per Site must equal Qty Ordered. Enter the values to use, Skip this line, or Abort.",
        options=["continue", "skip", "abort"],
        input_fields=[InputField("qty_per_carton", "Qty Per Carton", default=str(qpc)), InputField("cartons_per_site", "Cartons Per Site", default=str(cps))], step_id=self.id)
    skip → line.status = "skipped"; raise StepSkipped ; continue → qpc, cps = ints from resp (invalid → PostconditionFailed as today); plan.qty_per_carton, plan.cartons_per_site = qpc, cps
pl.flags += plan.flags
# optional cross-check of Model # (never blocks)
if pl.model_no:
    row_txt = ctx.resolver.try_resolve(ctx.page, "carton.item_po_row", v, NEG); txt = row_txt.inner_text() if row_txt else ""
    if txt and pl.model_no.upper() not in txt.upper(): pl.flags.append(Flag("model_mismatch_web", f"Model {pl.model_no} not shown in the item row", "warning")); ctx.warn(...)
```
Steps 9–13 of S8 (packaging code, fills, Save, verify, back) unchanged. `check_ordered` is no longer called directly by S8 (it is inside `decide_carton`).

**S10 `S10.finish_shipment`** — the between-shipments `finished_review` pause is kept but now gated by new `FlowConfig.review_between_shipments: bool = True`.
When `False`, S10 logs `INFO "shipment {idx} done: Web Shipment ID {wid}"` and emits no `NeedsUser` (the GUI still gets `ShipmentCreated`
and does the incremental write-back). Default `True` keeps today's behaviour and tests.

**Runner — multi-shipment loop with per-shipment isolation** (`runner.py::FlowRunner.run`, lines 192–197 become):
```
self.run_step(S.S0EnsureLoggedIn())
n = len(plan.shipments)
for i, sh in enumerate(plan.shipments):
    if ctx.pacer is not None: ctx.pacer.before_shipment(i)          # between_shipments_s + max_shipments_per_hour (unchanged)
    try:
        self._run_shipment(sh, is_last=(i == n - 1))
    except UserAbortError: raise
    except ForbiddenActionError: raise                               # safety: never continue after a guard trip
    except SiteBlockedError: raise                                   # already surfaced by _handle_block; if it escapes, stop
    except Exception as e:                                           # PostconditionFailed "too many attempts", PlaywrightError, bugs …
        ctx.log.exception("shipment %s failed", sh.index)
        sh.status = "failed"; sh.flags.append(Flag("shipment_failed", str(e), "error"))
        for ln in sh.lines:
            if ln.status in ("pending", "added", "carton_done"): ln.status, ln.error = "failed", str(e)
        ctx.results.write(plan)
        if i < n - 1:
            ctx.ask("shipment_failed",
                    f"Shipment {sh.index} ({sh.label}) failed: {getattr(e, 'message_vi', '') or e}. The browser is left as is. "
                    "Continue with the next shipment, or Abort the run?", options=["continue", "abort"], step_id="shipment")
```
`RunResult.status` logic unchanged (`partial` when some shipments are `done`). `estimate_steps` unchanged.
`_run_shipment` unchanged except: after `S6`, when `sh.dates_source == "excel"` nothing else differs; the `first_of`/`S1–S3` loop stays
(one master per tracker shipment → exactly one S1/S2/S3 before S5).

New `NeedsUser.kind` values: `shipment_failed` (options continue/abort). `qty_mismatch` now may carry `input_fields` (PauseDialog already renders them).

`context.py::vars()` adds `"model_no"` and `"container"` (empty strings when absent). No selector key changes.

### 10.6 Write-back (`data/excel_writeback.py`)

```python
def writeback_path_for(plan: RunPlan) -> Path:
    """packing_list: <src.stem>_ASN.xlsx next to the source (unchanged).
    po_tracker:   <src.stem>_ASN_<YYYYMMDD-HHMMSS>.xlsx next to the source, timestamp = plan.run_id[:15];
                  if the source directory is not writable (os.access or a failed probe write) → paths.run_dir(plan.run_id)/<same name>."""

def write_back(plan: RunPlan, det: HeaderDetection, mapping: ColumnMapping | None = None, *,
               ids: dict[int, str] | None = None, dst: Path | None = None) -> Path:
    """Idempotent: copies the ORIGINAL to dst (default writeback_path_for(plan)) every time, then writes ids.
    ids: shipment_index -> web_shipment_id (GUI passes the ids it received via ShipmentCreated). Per shipment the id used is
         ids.get(sh.index) or sh.web_shipment_id — an empty/None ids dict therefore behaves exactly like today (existing tests unchanged).
    Column resolution:
      1. mapping and mapping.columns['asn'] → that column letter (tracker: 'F');
      2. else a header cell in row max(det.header_rows) whose normalize_header(...) == 'asn' (exact, so 'submit asn w date' never matches);
      3. else append: header 'ASN' at max_column+1 (packing-list behaviour, unchanged).
    Rows: for every shipment with an id, for every PlannedLine with status not in ('skipped','failed'): ws.cell(row=line.source_row or excel_row, column=col).
      Each LINE ROW is written (F is never merged in the tracker; merges exist only in A–D/O/R/S). Value: int(id) when id.isdigit() else str (F2 holds an int).
      Never touch any other cell. Never write a column whose header contains 'submit'.
    Workbook is loaded WITHOUT data_only (formulas such as L '=J2*K2' survive); keep the openpyxl note: shapes/images/drawings may be dropped,
      column widths/merges/filters are preserved. Original never opened for writing (assert in tests by hashing it before/after)."""
```
GUI wiring (§10.7): `MainWindow` keeps `self._writeback_ids: dict[int,str]` filled from `ShipmentCreated`; on each such event (and on
`RunFinished`) it calls `write_back(self.run_plan, self.det, self.mapping, ids=self._writeback_ids, dst=self._writeback_path)` where
`_writeback_path = writeback_path_for(plan)` is fixed at Start. Dry runs never write back (unchanged rule).

### 10.7 UI (WP-C) changes

Files: `app/main_window.py`, `app/widgets/plan_table.py`, `app/dialogs/mapping_dialog.py`, `app/dialogs/settings_dialog.py`,
`app/strings_en.py`, `app/strings_vi.py` (identical key sets — `tests/app/test_strings.py` enforces it).

1. **Profile indicator + override (MappingDialog)**: a combo `S.MAPPING_PROFILE` with `PROFILES` labels at the top (default = `mapping.profile`);
   changing it updates the `*` markers (required set) and re-runs `suggest_mapping(det, profile)` to refill combos (user edits after that are kept
   only if the user changes the profile again). Field rows are ordered: required for the current profile first, then optional, then the rest
   (greyed). `result()` returns a `ColumnMapping` with `profile` set. `FIELD_LABELS` gains the 7 new keys.
   Template status line shows the profile: `S.STATUS_PROFILE = "Format: {profile}"` appended to the existing status text.
2. **Plan table** (`PlanTable`): column 0 becomes a checkbox column (`Qt.ItemIsUserCheckable`), columns:
   `☐ | Shipment | PO line | Master PO | Line | Container | Model # | Description | Cartons | Qty/carton | Order units | Weight (KG) | Ship date | Status | Warnings`.
   `set_plan(plan, all_lines)` uses `plan_summary_rows(plan, all_lines)`; rows of unselected lines are greyed (`#eeeeee`) with status
   `S.PLAN_STATUS_HAS_ASN.format(asn=…)` or `S.PLAN_STATUS_UNSELECTED`; rows of the same shipment share an alternating background;
   error rows red / warning rows yellow as today. Signal `selection_changed(master_po: str, checked: bool)`: toggling any row toggles **every
   row of that master PO** (a shipment contains all selected lines of its master). `has_errors()` counts only **selected** rows.
   Lines with an error flag and `existing_asn == ""` start **checked** (so the red row blocks Start until the user unticks it or fixes Excel).
3. **MainWindow**: keeps `self.rx.lines` as the source of truth for `selected`; `_on_selection_changed` sets `ln.selected` for the master and
   calls `_rebuild_plan()` (which calls `build_plan` on the full list; the planner filters). Grouping radios: when `mapping.profile == "po_tracker"`
   force `rb_master` checked and disable both radios (tooltip `S.OPT_GROUPING_FORCED`). Factory group hint: when `rx.company_text == ""` show
   `S.LBL_FACTORY_PICK_RUN` ("This file has no factory column — choose the ship-from factory for this run"); `_reload_factories` already
   pre-selects `cfg.ui.last_factory_id`; `start_run` additionally calls `save_config(self.cfg)` after `_sync_cfg_from_options()` so the last
   factory survives a crash. Start is refused with `S.ERR_NO_SELECTION` when no line is selected.
   `start_run` passes `PlanOptions(grouping, dry_run, cfg.flow.weight_mode, profile=self.mapping.profile, tracker_weight_mode=cfg.flow.tracker_weight_mode)`;
   stores `self._writeback_path = writeback_path_for(plan)`, clears `self._writeback_ids`.
   `_connect_bridge`: `b.shipment_created.connect(self._on_shipment_created)` → store id, incremental `write_back` (guarded by `cfg.flow.write_back_excel`
   and `not plan.dry_run`), log `S.LOG_WRITEBACK`. `_on_run_finished`: final `write_back(...)` with the same `dst`; the notification lists ids per shipment.
   History tab: unchanged.
4. **SettingsDialog → Workflow tab**: add `S.SET_TRACKER_WEIGHT` combo (`per_carton_as_is` = `S.SET_WEIGHT_PER_CARTON_AS_IS`, `total_gw`),
   `S.SET_REVIEW_BETWEEN` checkbox (`review_between_shipments`); `result_config()` maps both. Help text for the existing weight combo now says
   "packing-list files only".
5. **PauseDialog**: no code change; `PAUSE_TITLE` gets `"shipment_failed"`.
6. **Strings** (add to both `strings_en.py` and `strings_vi.py`; English shown, Vietnamese in parentheses):
   `MAPPING_PROFILE = "File format:"` (Định dạng tệp:) · `PROFILE_LABELS = {"po_tracker": "PO tracker", "packing_list": "Packing list"}` ·
   `STATUS_PROFILE = "Format: {profile}"` · `PLAN_COLUMNS` (new tuple, 15 entries as above) · `PLAN_STATUS_HAS_ASN = "already has ASN {asn}"` (đã có ASN {asn}) ·
   `PLAN_STATUS_UNSELECTED = "not selected"` (không chọn) · `OPT_GROUPING_FORCED = "PO-tracker files always create one shipment per master PO"` ·
   `LBL_FACTORY_PICK_RUN = "This file has no factory column - choose the ship-from factory for this run"` · `ERR_NO_SELECTION = "No PO line is selected."` ·
   `SET_TRACKER_WEIGHT = "Weight for PO-tracker files"` · `SET_WEIGHT_PER_CARTON_AS_IS = "Gross weight per carton, as in the file"` ·
   `SET_REVIEW_BETWEEN = "Pause for review between shipments"` · `NOTIFY_SHIPMENT_DONE = "Shipment {idx} created: Web Shipment ID {wid} (written to {path})"` ·
   `FIELD_LABELS` += `asn: "ASN #"`, `model_no: "Model #"`, `start_ship: "EDI PO Start Ship"`, `end_ship: "EDI PO End Ship"`, `pack: "Pack (units per carton)"`,
   `gw_per_carton: "Gross weight per carton (kg)"`, `container: "Container"` · `PAUSE_TITLE["shipment_failed"] = "Shipment failed"`.

### 10.8 Config additions (`core/config.py`) — all with defaults, old YAML loads unchanged

```python
class FlowConfig:
    ...
    tracker_weight_mode: str = "per_carton_as_is"     # "per_carton_as_is" | "total_gw"
    review_between_shipments: bool = True            # S10 finished_review pause between shipments
class UiConfig:
    ...
    last_profile: str = ""                            # informational; the mapping dialog default still comes from detection/template
```

### 10.9 Mock site + tests

#### Mock (`mock_edi/state.py`, `server.py`, `__main__.py`)

```python
TRACKER_SEED = [  # (po_line_id, qty_ordered, early, late, prepack)
  ("582067801", 1428, "30-NOV-26", "04-DEC-26", None), ("582067802", 960, "30-NOV-26", "04-DEC-26", None),
  ("582068001", 1650, "30-NOV-26", "04-DEC-26", None), ("582068002", 714, "30-NOV-26", "04-DEC-26", None),
  ("582068201", 1518, "30-NOV-26", "04-DEC-26", None), ("582067701", 2388, "09-NOV-26", "13-NOV-26", None),
  ("582067702", 330, "09-NOV-26", "13-NOV-26", None), ("582067901", 948, "30-NOV-26", "04-DEC-26", None),
  ("582068401", 158, "30-NOV-26", "04-DEC-26", 6),          # prepack variant: 158 AS with a "6 EA" sub-row (= 948 units)
]
def MockState.seed_tracker(self) -> None      # add_order(...) for each; statuses ACKNOWLEDGED/SUBMITTED alternating; versions=1
MockOptions.seed_tracker: bool = False        # MockServer.__init__ calls state.seed_tracker() when True (after seed_default)
MockOrder.ordered_in_packs: bool = False      # when True the carton page shows qty_ordered == cartons with UM "EA" and no prepack row (rule B); used by one unit test
```
`__main__.py --seed-tracker` flag. `carton_save.do` validation (`nq*nc > qty_ordered*(prepack or 1)`) already accepts 6×238=1428, 1×158=158.
`view_order.do` prints the seeded early/late → S3 cross-check confirms Excel dates (no mismatch flag in the happy path).

#### Tests (new; existing 174 stay green — the only existing assertions touched are none; `test_writeback`/`_ASN.xlsx` expectations are preserved by D8)

`tests/data/`
- `test_tracker_sample.py` (uses the real tracker file; `pytest.skip` if missing): `detect_header → header_rows [1], data_start 2`; `detect_profile → ("po_tracker", 1.0)`;
  `suggest_mapping` → `po D, line E, asn F, model_no G, description H, quantity J, start_ship M, end_ship N, pack Q, gw_per_carton T, container A`, none of `net_weight/packages/size`
  mapped, and **AB is not mapped to anything**; `extract_rows` → 9 lines in Excel order with the ids of §10.3.7; `lines[0].existing_asn == "872295"`, `selected False`;
  `lines[1].container == "Container 9"`; `packages == 238` on line 0, `160` on line 1, `158` on the last two; `gross_weight == 12` on line 0; windows as in §10.1;
  no line with `excel_row >= 11`; `rx.skipped == []`; `rx.company_text == ""`.
  Planner with `PlanOptions("per_file", False, "total_gw", profile="po_tracker", today=date(2026,10,18))`: `plan.grouping == "per_master_po"`, **7 shipments**, **8 lines**
  (`582067801` absent), shipment for `5820678` has exactly `[582067802]`, `planned_ship_date` = `2026-12-02` for all masters except `5820677` → `2026-11-11`,
  `dates_source == "excel"` everywhere, `weight_text == "12.00"` for 582067701, `"10.00"` for 582067802; `plan_summary_rows(plan, rx.lines)` has 9 rows, the first with
  `shipment_index == ""` and `status_text == "already has ASN 872295"`. Selecting line 0 (`selected=True`) → 7 shipments, 9 lines, `5820678` shipment has 2 lines.
- `test_tracker_edge_cases.py` (synthetic workbooks built with openpyxl in `tmp_path`): blank-row stop + secondary table ignored; auto-filter ref respected when no blank
  row separates the tables; header-text row inside data stops the table; forward-fill without merges (`master_po_inherited` flag); `F` with whitespace → `existing_asn == ""`;
  `J/Q` non-integer → `non_integer_units` error flag, line kept; duplicate `(master,line)` → `duplicate_line`; dates as `datetime` cells; missing dates → `dates_missing_excel`
  and `dates_source == "web"` for that shipment; `'5820678-01'` style D with no E column → still parsed (line from `parse_po_cell`).
- `test_synonyms_tracker.py` (§10.3.1 scores), `test_quantities.py` additions (§10.4.2), `test_profiles.py` (both samples), `test_templates.py` addition (profile roundtrip).
- `test_writeback_tracker.py`: plan from the real tracker with ids `{1:"900001", 2:"900002"}` → file name matches `_ASN_\d{8}-\d{6}\.xlsx$` and sits next to the source;
  `ws["F3"] == 900001` (shipment 1 = 5820678, line row 3), `ws["F4"] == 900002` and `ws["F5"] == 900002` (5820680 lines), `ws["F2"] == 872295` unchanged, `ws["AB2"] == ""`,
  `ws["L2"] == "=J2*K2"` (formula preserved), merged ranges and `auto_filter.ref` unchanged, **original file hash unchanged**, calling `write_back` twice with the same `dst`
  gives the same content (idempotent), `ids` override beats `sh.web_shipment_id`. Also: `writeback_path_for` falls back to `run_dir` when the source dir is read-only (monkeypatch `os.access`).

`tests/automation/`
- `wpb_helpers.py`: `make_tracker_plan(server) -> RunPlan` builds the plan from the **real tracker** through the data layer (`load_grid → detect_header → suggest_mapping →
  extract_rows → build_plan(profile="po_tracker", today=TODAY_TRACKER)`) with the SUMEC test factory; `TODAY_TRACKER = date(2026,10,18)` injected via `ctx.today`.
- `test_e2e_tracker.py` (marker `e2e`, `MockOptions(require_login=False, seed_tracker=True)`): scripted `ask_user` answers `continue` to `finished_review` and fails on
  anything else. Assert: `RunResult.status == "done"`, 7 shipments with distinct numeric ids, mock state: each shipment contains exactly its master's lines; header
  `txtShippingDate == "12/02/2026"` for all but `5820677` → `"11/11/2026"`; cartons `582067802 → ("6","160")`, `582067701 → ("6","398")`, `582068401 → ("1","158")` with
  packaging `PCC`; weights `"10.00"`, `"12.00"`, `"6.00"` KG respectively; `complete_partial == "Partial"` everywhere; `submit_called is False`; `results.csv` has 8 rows;
  no `dates_mismatch_web` flag; `ShipmentCreated` emitted 7 times with increasing `shipment_index`; the run finishes in < 240 s headless.
  Variants: (a) `review_between_shipments=False` → zero `finished_review` asks; (b) pacing on with `between_shipments_s=[1,1]`, `max_shipments_per_hour=0` → `pacer.slept_ms ≥ 6000`;
  (c) dates mismatch: mutate order `582068201` early/late to `01-DEC-26..05-DEC-26` → shipment still `done`, flag `dates_mismatch_web` present, header date still `12/02/2026`;
  (d) rule-B order (`ordered_in_packs=True` on `582067901`, qty_ordered 158) → cartons `("1","158")`, flag `web_counts_packs`; (e) mismatch (`qty_ordered=1400` on `582067802`)
  → `qty_mismatch` ask with two input fields; scripted answer `continue` with `{"qty_per_carton":"6","cartons_per_site":"160"}` → the mock accepts it
  (6×160 = 960 ≤ 1400) → shipment `done` with the `qty_mismatch_web` flag; scripted `skip` instead → the line is skipped and, because it was the shipment's only line,
  S9 is skipped (`any carton_done` is false) and S10 runs — assert explicitly that the shipment status is `done` and the mock has no carton for that PO.
- `test_runner_isolation.py`: monkeypatch `S.S6FillHeaderSave.act` to raise `RuntimeError("boom")` only for `shipment_index == 2` → shipments 1 and 3 `done`, 2 `failed` with
  `shipment_failed` flag, `RunResult.status == "partial"`, exactly one `shipment_failed` ask (options `["continue","abort"]`); answering `abort` → status `aborted`, shipment 3 `aborted`.
  Also: `ForbiddenActionError` raised inside shipment 1 → whole run `failed`, shipment 2 never started (safety preserved).
- `test_mock_pages.py` addition: `seed_tracker` renders all nine POs in the inbox; prepack row for `582068401`.

`tests/app/`
- `test_plan_table.py`: checkbox default states from the tracker (`582067801` unchecked, others checked); clicking one line of `5820680` unticks both of its lines;
  `has_errors()` ignores unticked error rows; greyed status text.
- `test_main_window_tracker.py` (FakeWorker): load the tracker → status shows `Format: PO tracker`, radios disabled with `rb_master` checked, factory combo pre-selects
  `cfg.ui.last_factory_id`, Start refused with `ERR_NO_SELECTION` when everything is unticked, Start builds a plan with 7 shipments, `cfg.ui.last_factory_id` saved;
  `ShipmentCreated(1, "900001")` through the bridge → `_ASN_<ts>.xlsx` exists with `F3 == 900001`; `RunFinished` rewrites the same file (no second copy).
- `test_mapping_dialog.py` addition: profile combo present, switching to `packing_list` re-marks `packages/gross_weight` as required and blocks accept on the tracker.
- `test_strings.py` unchanged (will fail until both language files have the new keys — intended).

### 10.10 Skill update notes (`skills/burlington-asn/`, separate implementer — package P2)

- `SKILL.md`: add triggers "PO tracker", "MDDP", "tracker excel", "Q4 Pet Beds", "nhập tracker lên EDI", "làm ASN từ tracker". New input-format section:
  tracker columns (§10.1), rules D2–D8 in prose: PO line id = Master PO + Line #; **one shipment per master PO**; ship date = midpoint of the intersection of the lines'
  `EDI PO Start/End Ship` windows (Excel is authoritative, the PO page is a cross-check only); Qty Per Carton = Pack, Cartons Per Site = Order Units / Pack, verified against
  the web `Qty Ordered` (== Order Units → Pack per carton; == Order Units/Pack → 1 per carton; else stop); weight per PO line = `Gross Weight/Carton(kg)` as-is 2 dp KG (NOT a total);
  rows with an `ASN #` are skipped unless the user says otherwise; factory must be asked per run (no factory column); after each shipment the ASN is written into
  column `ASN #` of a **copy** (`<name>_ASN_<timestamp>.xlsx`), never into `Submit ASN # (w/ Date)` and never into the original. Keep the packing-list path as "format B".
- `scripts/parse_packing_list.py`: add profile auto-detection (header row containing `master po`, `line`, `pack`, `gross weight/carton`) and a tracker branch that emits the
  same `lines[]` shape plus `line_suffix` from `Line #`, `order_units`, `pack`, `cartons = order_units/pack`, `gross_weight_per_carton`, `start_ship`/`end_ship` (ISO), `existing_asn`,
  `container`, `model_no`; stop at the first blank row / auto-filter end; inherit merged A–D; add `--include-with-asn`. Output `profile` field. Keep all current flags/blocking.
  Alternatively a new `scripts/parse_po_tracker.py` with the same JSON contract if the maintainer prefers (document in `excel_mapping.md`).
- `scripts/plan_shipment.py`: when parsed lines carry `start_ship`/`end_ship`, `--dates` becomes optional (Excel wins; `--dates` only adds a `WEB_DATES_DIFFER` warning);
  default grouping `--per-master` when `profile == "po_tracker"`; `qty_per_carton = pack`, `cartons_per_site = cartons`; `--ordered DOC=Q` applies the A/B rule and marks
  BLOCKING on mismatch; weight = `gross_weight_per_carton`.
- New `scripts/write_asn.py FILE.xlsx --asn 582067802=900001 ...` → writes column `ASN #` on the matching `Master PO`+`Line #` rows of a timestamped copy (openpyxl, no `data_only`).
- `references/procedure.md`: Step 0 (tracker parse + factory question + skip-ASN rows), Step 2 (dates are a cross-check; still open the PO page because `Create New Shipment`
  is there), Step 3 (plan table adds Container/Model/Ship window), Step 6 (Qty Ordered A/B rule and the `qpc × cps == Qty Ordered` check before Save), Step 7 (per-carton weight),
  Step 8 (run `write_asn.py`, report the copy path). `references/excel_mapping.md`: tracker field list, merged-cell and secondary-table notes.
- `README.md` / `README_VI.md`: new section "PO tracker files" (profile auto-detect, checkboxes, factory per run, copy naming).

### 10.11 Implementation order, package split, acceptance

**Order**
1. (P1, first hour) contracts: `core/models.py` fields, `core/config.py` keys, `data/profiles.py`, `PlanOptions` fields, `decide_carton` signature, `write_back` signature,
   `plan_summary_rows(plan, all_lines)` keys, `MockOptions.seed_tracker` — commit so P2 can code against them.
2. (P1) synonyms + mapping profile + `tracker_rows.py` + `excel_reader` additions + tests on the real tracker (`test_tracker_sample.py` green).
3. (P1) planner + quantities + write-back + results columns; then flow (S3 cross-check, S8 decide, S10 gate, runner isolation); mock seed; e2e tracker tests.
4. (P2, parallel from step 1) strings, mapping dialog profile, plan table checkboxes, main window wiring, settings; app tests with FakeWorker; skill files; READMEs.
5. Integration: extend `tests/test_integration_app.py` with a second test `test_gui_to_mock_tracker_run` (real GUI stack, tracker file, `seed_tracker=True`, PauseDialog
   auto-continue, assert 7 ids, `_ASN_<ts>.xlsx` with F3..F10 filled, original hash unchanged).

**Package split (no file overlap)**

| | P1 — data, flow, mock, tests | P2 — app UI, skill, docs |
|---|---|---|
| Files owned | `core/models.py`, `core/config.py`, `core/quantities.py`, `core/dates.py` (no change expected), `data/*` (incl. new `profiles.py`, `tracker_rows.py`), `automation/flow/steps.py`, `automation/flow/runner.py`, `automation/flow/context.py`, `automation/po_dates.py`, `mock_edi/*`, `tests/data/*`, `tests/automation/*`, `tests/test_integration_app.py` | `app/**` (`main_window.py`, `widgets/plan_table.py`, `dialogs/mapping_dialog.py`, `dialogs/settings_dialog.py`, `strings_en.py`, `strings_vi.py`), `tests/app/*`, `skills/burlington-asn/**`, `README.md`, `README_VI.md` |
| Must not touch | anything under `app/`, `skills/`, READMEs | anything under `core/`, `data/`, `automation/`, `mock_edi/`, `tests/data`, `tests/automation` |
| Hand-off | step 1 contracts committed first; P2 stubs nothing — it imports the committed names | P2 may add `FakeWorker` emission helpers in `tests/app/conftest.py` only |

**Acceptance criteria**
- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` green: all 174 existing tests unchanged in outcome, plus the new ones of §10.9 (≥ 35 new tests).
- Real tracker parses to the §10.1/§10.3.7 numbers; `582067801` is unselected by default; 7 shipments / 8 lines by default; ship dates `12/02/2026` and `11/11/2026`
  with `today=2026-10-18`; weights `12.00/10.00/8.00/7.00/10.00/12.00/9.00/8.00/6.00`; cartons `238/160/275/119/253/398/55/158/158` with `qpc 6` (prepack variant `1/158`).
- Headless e2e against the mock: multi-shipment run `done`, `submit_called False`, pacing honoured when enabled, one failing shipment yields `partial` and the others `done`.
- Write-back copy exists next to the original with the timestamped name, `F` filled per line row, `AB` untouched, formulas intact, original hash unchanged, no write on dry run.
- Packing-list sample still runs through the GUI integration test unchanged (`_ASN.xlsx`, 2 rows, qpc 6 / cps 85, 1020.00 KG).
- No new Qt/Playwright import in `core`/`data`; `mock_edi` still stdlib-only; safety guards and the dry-run hard stop untouched (`tests/automation/test_actions_guard.py`,
  `test_dry_run_skipped_header_step_never_persists` unchanged and green).
