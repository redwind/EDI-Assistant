"""All English UI strings (module-level constants). Same keys and placeholders as strings_vi.py."""

APP_TITLE = "EDI Assistant"
ABOUT_TEXT = ("{name} {version}\n\nA helper for entering ASNs on EDI Gateway.\n"
              "The tool NEVER clicks Submit ASN - you review everything and click Submit yourself.")

# --- buttons
BTN_START = "Start entry"
BTN_ABORT = "Abort"
BTN_CONTINUE = "Continue"
BTN_SKIP = "Skip step"
BTN_REVIEWED = "Got it"
BTN_CANCEL = "Cancel"
BTN_CHOOSE = "Choose"
BTN_CHOOSE_FILE = "Choose file…"
BTN_EDIT_MAPPING = "Edit column mapping…"
BTN_EDIT_FACTORY = "Add/Edit…"
BTN_OPEN_BROWSER = "Open browser"
BTN_OPEN_FOLDER = "Open folder"
BTN_OPEN_CSV = "Open CSV"
BTN_NEW = "New"
BTN_SAVE = "Save"
BTN_DELETE = "Delete"
BTN_TEST_CONNECTION = "Test connection"

# --- main window
TAB_MAIN = "Entry"
TAB_LOG = "Log"
TAB_HISTORY = "History"
GRP_EXCEL = "Excel file"
GRP_FACTORY = "Factory (ship-from address)"
GRP_OPTIONS = "Options"
LBL_SHEET = "Sheet:"
LBL_FACTORY_HINT = "Hint from file: {text}"
FACTORY_NONE = "(choose a factory)"
OPT_PER_FILE = "One shipment for the whole file"
OPT_PER_MASTER_PO = "One shipment per master PO"
OPT_DRY_RUN = "Dry run (do not save)"
OPT_WRITE_BACK = "Write ASN into a copy of the Excel file"
STATUS_NO_FILE = "No file selected"
STATUS_NO_HEADER = "Header row not found"
STATUS_TEMPLATE_EXACT = "Template recognized: {name}"
STATUS_TEMPLATE_SIMILAR = "Similar template: {name} - please check"
STATUS_TEMPLATE_NEW = "New template - please check the column mapping"
STATUS_MAPPING_CONFIRMED = "Column mapping confirmed"
DLG_CHOOSE_EXCEL = "Choose the packing list Excel file"
FILTER_EXCEL = "Excel (*.xlsx *.xlsm);;All files (*)"
PLAN_COLUMNS = ("", "Shipment", "PO line", "Master PO", "Line", "Container", "Model #", "Description", "Cartons",
                "Qty/carton", "Order units", "Weight (KG)", "Ship date", "Status", "Warnings")
HISTORY_COLUMNS = ("Run ID", "Started", "Status", "Shipments", "Web Shipment ID")
LOG_LEVEL = "Log level:"
LOG_WRITEBACK = "ASN written to: {path}"
LOG_WRITEBACK_FAIL = "Could not write the ASN into Excel: {err}"

# --- menus
MENU_FILE = "File"
MENU_OPEN_EXCEL = "Open Excel"
MENU_EXIT = "Exit"
MENU_TOOLS = "Tools"
MENU_SETTINGS = "Settings…"
MENU_CALIBRATE = "Calibrate selectors…"
MENU_INSPECTOR = "Open Playwright Inspector"
MENU_INSTALL_CHROMIUM = "Install Chromium browser…"
MENU_OPEN_DATA = "Open data folder"
MENU_HELP = "Help"
MENU_GUIDE = "User guide"
MENU_ABOUT = "About"

# --- tray / notifications
TRAY_TOOLTIP = "EDI Assistant is running"
TRAY_SHOW = "Show window"
TRAY_OPEN_BROWSER = "Open browser"
TRAY_QUIT = "Quit"
NOTIFY_FILLED_DONE = "Entry finished - please review and click Submit yourself"
NOTIFY_NEEDS_USER = "Your attention is needed"
NOTIFY_RUN_DONE = "Done: {n} shipment(s), Web Shipment ID: {ids}. Please review and click Submit ASN manually."
NOTIFY_DRY_RUN_DONE = "Dry run finished (nothing was saved on the portal)."
NOTIFY_RUN_ABORTED = "Stopped as requested."
NOTIFY_RUN_FAILED = "The run failed: {err}"
CONFIRM_QUIT_RUNNING = "An entry run is in progress. Quitting now will stop it. Are you sure you want to quit?"

# --- errors
ERR_NO_SHEETS = "The Excel file has no sheets."
ERR_NO_FACTORY = "Please choose a factory (ship-from address) before starting."
ERR_GUIDE_MISSING = "User guide file README.md not found."

# --- browser install
ASK_INSTALL_CHROMIUM = ("Microsoft Edge or Chromium was not found. Download a fallback Chromium (~150 MB) now?")
INSTALL_CHROMIUM_TITLE = "Install Chromium"
INSTALL_CHROMIUM_PROGRESS = "Downloading Chromium (~150 MB)…"
INSTALL_CHROMIUM_OK = "Chromium installed."
INSTALL_CHROMIUM_FAIL = "Chromium installation failed. See the Log tab or try again."

# --- mapping dialog
MAPPING_TITLE = "Excel column mapping"
MAPPING_HINT = "Choose the Excel column for each field (* is required)."
MAPPING_COL_FIELD = "Field"
MAPPING_COL_COLUMN = "Excel column"
MAPPING_COL_CONF = "Confidence"
MAPPING_UNUSED = "(not used)"
MAPPING_PREVIEW = "Preview of the headers and the first 5 data rows"
MAPPING_TEMPLATE_NAME = "Template name:"
MAPPING_REMEMBER = "Remember this layout for next time"
MAPPING_MISSING = "Required fields are still missing: {fields}"
FIELD_LABELS = {
    "po": "PO number", "line": "Line number", "description": "Description", "packages": "Cartons",
    "quantity": "Quantity", "gross_weight": "Gross weight (G.W.)", "net_weight": "Net weight (N.W.)",
    "size": "Size",
    "asn": "ASN #", "model_no": "Model #", "start_ship": "EDI PO Start Ship", "end_ship": "EDI PO End Ship",
    "pack": "Pack (units per carton)", "gw_per_carton": "Gross weight per carton (kg)", "container": "Container",
    "edi_units": "EDI Units (used when Order Units is empty)", "factory": "Factory name",
}

# --- factory dialog
FACTORY_TITLE = "Factory list"
FACTORY_NAME = "Name"
FACTORY_ADDR1 = "Address 1"
FACTORY_ADDR2 = "Address 2"
FACTORY_CITY = "City"
FACTORY_STATE = "State/Province"
FACTORY_ZIP = "Postal code"
FACTORY_COUNTRY = "Country"
FACTORY_SITE_NO = "Site No"
FACTORY_ALIASES = "Other names (comma-separated)"
FACTORY_NEED_NAME = "Please enter a name and address 1."
FACTORY_CONFIRM_DELETE = "Delete this factory?"

# --- pause dialog
PAUSE_TITLE_DEFAULT = "Your attention is needed"
PAUSE_TITLE = {
    "login_required": "Login required",
    "finished_review": "Entry finished",
    "dry_run_stop": "Dry run stop",
    "step_failed": "Step failed",
    "po_replaced": "PO has been replaced",
    "qty_mismatch": "Quantity mismatch",
    "non_integer_carton": "Cartons do not divide evenly",
    "dates_needed": "Ship dates needed",
    "no_date_intersection": "Ship date windows do not overlap",
    "country_not_in_list": "Country not in the list",
    "unverified_selector": "Unverified element",
    "confirm": "Confirm",
    "site_blocked": "The site may be blocking us",
    "date_in_past": "Ship date is in the past",
    "shipment_failed": "Shipment failed",
}
PAUSE_AI_EXPLANATION = "AI explanation"
PAUSE_OPEN_SCREENSHOT = "Click to open the full image"

# --- settings dialog
SETTINGS_TITLE = "Settings"
TAB_SITE = "Website"
TAB_BROWSER = "Browser"
TAB_FLOW = "Workflow"
TAB_AI = "AI"
TAB_NOTIFY = "Notifications"
TAB_PACE = "Pace"
SET_BASE_URL = "EDI Gateway address"
SET_USE_MOCK = "Use the mock site for practice"
SET_MOCK_URL = "Mock site address"
SET_VENDOR = "Vendor profile name"
SET_CHANNEL = "Browser"
SET_HEADLESS = "Run hidden (no browser window)"
SET_SLOW_MO = "Slow down every action (ms)"
SET_TIMEOUT = "Default timeout (ms)"
SET_GROUPING = "Shipment grouping"
SET_DRY_RUN = "Dry run (save nothing on the portal)"
SET_WEIGHT_MODE = "Weight entry mode"
SET_WEIGHT_TOTAL = "Total gross weight of the line"
SET_WEIGHT_PER_CARTON = "Weight per carton (total / cartons)"
SET_WEIGHT_HELP = "Packing-list files only. Default is the line's total G.W. Choose 'per carton' if the portal expects a weight per carton."
SET_SHIPPING_TYPE = "Shipping Type"
SET_TRANSPORT = "Transportation Method"
SET_SCAC = "SCAC code"
SET_BOL = "Bill of Lading"
SET_PRO = "PRO Number"
SET_PACK_CODE = "Packaging Code (carton)"
SET_COMPLETE_PARTIAL = "Complete / Partial"
SET_WEIGHT_UM = "Weight unit"
SET_CLICK_VALIDATE = "Click 'Validate Shipment' after entry (not recommended)"
SET_CLICK_VALIDATE_HELP = "The tool never clicks Submit ASN, even with this option on."
SET_WRITE_BACK = "Write ASN into a copy of the Excel file"
SET_PAUSE_QTY = "Pause when the Excel quantity differs from the ordered quantity"
SET_PAST_DATE = "When the ship date is in the past"
SET_PAST_DATE_CLAMP = "Use today automatically"
SET_PAST_DATE_ASK = "Ask me"
SET_AI_ENABLED = "Enable the AI assistant (optional, billed by the provider)"
SET_AI_PRESET = "Provider preset"
SET_AI_PROVIDER = "API type"
SET_AI_BASE_URL = "Base URL"
SET_AI_KEY = "API key"
SET_AI_MODEL = "Model"
SET_AI_VISION = "Send screenshots to the AI (vision)"
SET_AI_MAX_CALLS = "Maximum AI calls per run"
PRESET_LABELS = {
    "custom": "(custom)", "anthropic": "Anthropic - Claude Haiku", "anthropic_sonnet": "Anthropic - Claude Sonnet",
    "openai": "OpenAI", "gemini": "Google Gemini", "deepseek": "DeepSeek", "qwen": "Qwen (Alibaba)",
    "openrouter": "OpenRouter", "ollama": "Ollama (local)",
}
TEST_RUNNING = "Testing…"
TEST_NO_KEY = "Missing API key (or no provider selected)."
TEST_OK = "Connection successful. Reply: {text}"
TEST_BAD_REPLY = "Connected, but the reply was not in the expected format - try another model."
TEST_FAIL = "Connection failed: {text}"
SET_SOUND = "Play a sound when attention is needed / when finished"
SET_BALLOON = "Show notifications in the system tray"
SET_START_MIN = "Start minimized to the tray"
SET_START_WIN = "Start with Windows"

# --- calibrate dialog
CALIB_TITLE = "Calibrate selectors"
CALIB_COLUMNS = ("Key", "Page", "Verified", "Learned", "Description")
CALIB_ALL_PAGES = "(all)"
CALIB_PAGE_FILTER = "Filter by page:"
CALIB_VARS = "Substitution variables"
CALIB_VAR_PO = "PO (9 digits)"
CALIB_VAR_SITE = "Site No"
CALIB_VAR_ROWKEY = "Row key"
CALIB_HIGHLIGHT = "Highlight"
CALIB_PICK = "Pick on page"
CALIB_CANCEL_PICK = "Cancel pick"
CALIB_TEST = "Test"
CALIB_FORGET = "Forget learned"
CALIB_INSPECTOR = "Open Inspector"
CALIB_LINK_INBOX = "Inbox"
CALIB_LINK_NEW_SHIPMENT = "New Shipment"
CALIB_LINK_DRAFTS = "Drafts"
CALIB_OPEN_PAGE = "Open page:"
CALIB_WAITING = "Waiting for you to click the element…"
CALIB_CANCELLED = "Pick cancelled."
CALIB_SAVED = "Selector saved for {key}."

# --- AI errors / test
AI_ERR_NETWORK = "Cannot reach the AI service."
AI_ERR_HTTP = "The AI service returned an error (HTTP {status})."
TEST_STEP_TITLE = "Connection test"

# --- settings: language + human pace
SET_LANGUAGE = "Interface language"
SET_LANGUAGE_HELP = "Takes effect after restarting the application."
LANGUAGE_LABELS = {"en": "English", "vi": "Tiếng Việt"}
GRP_PACE = "Human pace (anti-blocking, more reliable)"
SET_PACE_ENABLED = "Enable human-pace mode"
SET_PACE_HELP = ("Adds random delays between actions, types text key by key and pauses between shipments "
                 "so the website is less likely to flag the session.")
SET_PACE_ACTION = "Delay between actions (ms)"
SET_PACE_NAV = "Extra delay after each page load (ms)"
SET_PACE_TYPE = "Delay per typed character (ms)"
SET_PACE_MAX_HOUR = "Max shipments per hour (0 = unlimited)"
SET_PACE_BETWEEN = "Pause between shipments (seconds)"
PACE_MIN = "from"
PACE_MAX = "to"

# --- PO-tracker (v2)
MAPPING_PROFILE = "File format:"
PROFILE_LABELS = {"po_tracker": "PO tracker", "packing_list": "Packing list"}
STATUS_PROFILE = "Format: {profile}"
PLAN_STATUS_HAS_ASN = "already has ASN {asn}"
PLAN_STATUS_UNSELECTED = "not selected"
OPT_GROUPING_FORCED = "PO-tracker files always create one shipment per master PO"
LBL_FACTORY_PICK_RUN = "This file has no factory column - choose the ship-from factory for this run"
ERR_NO_SELECTION = "No PO line is selected."
SET_TRACKER_WEIGHT = "Weight for PO-tracker files"
SET_WEIGHT_PER_CARTON_AS_IS = "Gross weight per carton, as in the file"
SET_REVIEW_BETWEEN = "Pause for review between shipments"
NOTIFY_SHIPMENT_DONE = "Shipment {idx} created: Web Shipment ID {wid} (written to {path})"

# --- locked-down PCs: system check, autostart, browser
MENU_SYSTEM_CHECK = "System check…"
SET_CHANNEL_AUTO = "Auto (bundled Chromium, else Edge)"
SYSCHECK_TITLE = "System check"
SYSCHECK_RUNNING = "Checking this computer… (this takes a few seconds)"
SYSCHECK_COPY = "Copy report"
SYSCHECK_COPIED = "Report copied to the clipboard."
SYSCHECK_CLOSE = "Close"
SYSCHECK_SUMMARY = "{n_pass} passed, {n_warn} warning(s), {n_fail} failed"
SYSCHECK_REPORT_HEADER = "EDI Assistant {version} - system check"
ASK_SYSTEM_CHECK_FIRST_RUN = ("Run a quick system check now? It tests whether this computer allows the browser, "
                              "network access and the other features the app needs.")
CHK_DATA_DIR = "Data folder writable"
CHK_BROWSER_HEADLESS = "Browser launch (headless)"
CHK_BROWSER_HEADED = "Browser launch (visible window)"
CHK_BUNDLED = "Bundled Chromium (full zip)"
CHK_EDGE = "Microsoft Edge installed"
CHK_PORTAL = "EDI portal reachable"
CHK_AUTOSTART = "Start with Windows (registry)"
CHK_NOTIFY = "Tray notifications"
CHK_OK_FOUND = "found"
CHK_NOT_FOUND = "not found"
CHK_SKIPPED = "not applicable on this system"
CHK_HINT_NO_BROWSER = ("No usable browser. Use the 'full' portable zip (includes Chromium) or ask IT to allow "
                       "Edge remote debugging (policy RemoteDebuggingAllowed).")
CHK_HINT_PORTAL = "Check the network/proxy or ask IT to allow https://edi.coat.com."
AUTOSTART_BLOCKED = ("Windows blocked the 'start with Windows' setting (probably a company policy). "
                     "The option was turned off; the app keeps working normally.")
BROWSER_LOCKED_DOWN = ("The browser could not be started. Company policy may block Microsoft Edge automation. "
                       "Use the 'full' portable zip or run Help > System check.")

# --- factory list import (Excel)
BTN_IMPORT_FACTORIES = "Import Excel…"
MENU_IMPORT_FACTORIES = "Import factory list (Excel)…"
FACTORY_IMPORT_TITLE = "Choose the factory list Excel file"
FACTORY_IMPORT_DONE = "Factory list imported from {file}:\n{added} added, {updated} updated ({total} factories in total)."
FACTORY_IMPORT_EMPTY = "No factory rows found in {file}."
FACTORY_IMPORT_TIP = "Load/refresh the factory list from an Excel file (one row per factory). Last file: {file}"
FACTORY_CODE = "Code (file-name number)"
FACTORY_TRANSPORT = "Transportation method (blank = Settings)"
FACTORY_SCAC = "SCAC code (blank = Settings)"
LBL_FACTORY_NOT_FOUND = "Factory in file: {text} - not in the list (import the factory list or add it)"
