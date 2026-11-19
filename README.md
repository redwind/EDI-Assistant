# EDI Assistant - User Guide

(Vietnamese version: [README_VI.md](README_VI.md))

## 1. Introduction and safety warnings

EDI Assistant reads the factory's packing list Excel file, plans the shipments and automatically enters the ASN information on Burlington's **EDI Gateway** portal in a browser window that stays visible on screen. The app lives in the system tray and notifies you when it needs your attention.

**Important:**

- The tool **NEVER clicks "Submit ASN"**. When entry is finished, the tool stops and plays a notification and sound: *"Entry finished - please review and click Submit yourself"*. You check the web page and **click Submit ASN yourself**.
- The tool **never types passwords**. You log in yourself in the browser the tool opens.
- Settings > Workflow has "When the ship date is in the past" (`flow.past_date_policy`): "Use today automatically" or "Ask me".
- If you open the Inspector (Calibrate), close the Inspector before exiting the app.
- The tool does not click "Validate Shipment" (unless you enable it in Settings), and never deletes or cancels shipments.
- Opening a PO detail page makes the portal mark the PO as "read" - this is normal behavior.
- The "PO replaced" (Replaced) procedure is not automated: the tool only reports it and waits for you to handle it manually.
- **Human-pace mode** is on by default (Settings > Pace): random delays between actions, key-by-key typing and pauses between shipments. If the site starts returning "Access Denied", "Too Many Requests", a CAPTCHA, or keeps sending you back to the login page, the tool stops immediately and asks you what to do (see section 9).

## 2. Installation

Requirements: Windows 10/11 and **Microsoft Edge** (already included with Windows). If the machine has no Edge, the app offers to download a fallback Chromium (about 150 MB, menu *Tools > Install Chromium browser...*).

### Portable version (recommended)

1. Unzip `EDI-Assistant-portable-x.y.z.zip` into any folder (Desktop, USB...). The folder must be writable.
2. Run `EDI Assistant\EDI Assistant.exe`.
3. All data lives in the `EDI Assistant\data\` folder (thanks to the `portable.flag` file next to the exe). To move to another machine, copy the whole folder.

### Company (locked-down) PCs

Many company PCs block installers, so the portable zip is the recommended way to run EDI Assistant. Two zips are published:

| Zip | Contents | Use when |
|---|---|---|
| `EDI-Assistant-portable-x.y.z.zip` (lite) | The app only; drives Microsoft Edge | Edge is installed and automation is allowed |
| `EDI-Assistant-portable-full-x.y.z.zip` (full) | The app plus its own Chromium in `browsers\` (about 150 MB more) | **Edge automation is blocked** by IT policy (`RemoteDebuggingAllowed`), or Edge is missing; needs no download at run time |

Steps:

1. **Unblock the zip first.** Right-click the downloaded `.zip` > *Properties* > tick **Unblock** > OK. (Otherwise Windows marks every extracted file with "Mark of the Web" and SmartScreen/antivirus may block the exe.)
2. **Extract to a folder you can write to**, such as Documents or Desktop - not `Program Files`. The app stores its data in `data\` next to the exe.
3. Run `EDI Assistant\EDI Assistant.exe`. On first start the app offers a **System check** (also under *Help > System check...*): it reports PASS / WARN / FAIL for the data folder, launching the browser (hidden and visible), bundled Chromium, Edge, access to `https://edi.coat.com/vms-gateway/login.do` (using the system proxy), start-with-Windows and notifications. Use **Copy report** and paste it to IT or support.
4. Settings > Browser: *Auto* (default) uses the bundled Chromium if present, else Edge; if Edge cannot be launched (policy or not installed) it falls back to Chromium when available, otherwise shows a message suggesting the full zip. The app never downloads a browser without your confirmation: a download starts only after you click *Tools > Install Chromium browser...* or answer Yes to the first-run question.
5. If *Start with Windows* is blocked by policy, the app shows a warning, unticks the option and keeps working.

**If AppLocker or antivirus blocks the exe**, tell IT:

- Full path of the exe, e.g. `C:\Users\<you>\Documents\EDI Assistant\EDI Assistant.exe` (and the folder `EDI Assistant\` for allow-listing by path).
- The SHA256 hash from `SHA256SUMS.txt` (published next to the zips; it also lists the exe itself). You can verify with `Get-FileHash "EDI Assistant.exe"`.
- Publisher/product: SHYFT GLOBAL LLC / EDI Assistant (the exe is not code-signed).
- What it needs: outbound HTTPS to `edi.coat.com`; launching a browser it controls (Edge with remote debugging, or its own Chromium in `browsers\`).

### Installer version

1. Run `EDI-Assistant-Setup-x.y.z.exe` (no administrator rights needed; installs for the current user).
2. You can choose to create a desktop icon and "Start with Windows".
3. Data is stored in `%APPDATA%\EDI Assistant` (settings, templates, factories, results) and `%LOCALAPPDATA%\EDI Assistant` (browser profile). On uninstall, the app asks whether to delete the data; choose "No" to keep it.

Running the app a second time while it is open just brings the running window to the front.

## 3. First use

1. Click **Open browser**. An Edge window appears (the tool's own profile).
2. **Log in yourself** to EDI Gateway in that window (enter your password, select the vendor profile). The login session is kept for later runs; when it expires the tool pauses and waits for you to log in again.
3. Add factories: click **Add/Edit...** in the "Factory" group. Enter the name, address, city, country... (you can set "Other names" for automatic recognition). The app suggests a factory from the company name at the top/bottom of the Excel file.
   - **Import the whole list from Excel (recommended):** click **Import Excel…** (or *File > Import factory list (Excel)…*) and pick `factories.xlsx` (first sheet, one row per factory; columns Factory Name, Address 1, Address 2, City, State, Zip, Country, Aliases (`;`-separated), Code, Transportation Method, SCAC Code). Import once; when the list changes, import the file again - factories with the same name are updated, new ones added, others kept.
   - Blank Transportation Method / SCAC Code = use Settings; fill them for factories that ship by truck (e.g. Mexico: LTL + the trucker's SCAC).
   - Trackers with a *Factory Name* column (e.g. `PO_EXTRACT_TRACKER_FORMAT`) pick the matching factory automatically; when *Order Units* is empty, the quantity comes from *EDI Units*.

Note: the portal's Country field only lists US, CA, CN directly. For other countries, the tool pauses and asks you to choose manually.

## 4. Daily workflow

1. **Choose the Excel file** (the *Choose file...* button or menu File > Open Excel).
2. **Check the column mapping.** For a new layout, the *Excel column mapping* dialog appears: preview the headers, check the suggested column for each field (green = high confidence) and fix any mistakes. Keep **"Remember this layout"** ticked so the app applies it automatically next time. Learned layouts are recognized automatically ("Template recognized: ..."); similar layouts are pre-filled and need your confirmation.
3. **Choose the factory** and options: one shipment for the whole file or one per master PO; dry run; write the ASN into a copy of the Excel file (`<name>_ASN.xlsx`, the original is never modified).
4. **Check the plan table.** Red rows have errors (for example the quantity does not divide evenly by the carton count) - the Start button stays locked until you fix the Excel file/mapping. Yellow rows are warnings.
5. Click **Start entry**. Follow the step list; you can minimize to the tray.
6. **Pause dialog.** When you are needed (login, failed step, ship dates, quantity mismatch...), a window appears with a notification and sound, a page screenshot and (if AI is on) an AI explanation:
   - **Continue** - you handled it on the page yourself (or entered the requested value); the tool re-checks and carries on.
   - **Skip step** - skip this step and continue.
   - **Abort** - end the run; the browser is left as it is.
7. **Get the completion notification.** Check the data on the page carefully, then **click Submit ASN yourself**.
8. Results: the *History* tab and the `results.csv` file in `runs\<run id>`.

## 4a. PO tracker files

The MDDP **PO tracker** workbook (columns `Master PO #`, `Line #`, `ASN #`, `Order Units`, `EDI PO Start/End Ship`, `Pack`, `Gross Weight/Carton(kg)`) is detected automatically; the mapping dialog shows **File format: PO tracker** and lets you switch to *Packing list* if needed.

- **Plan table checkboxes.** Every PO line has a checkbox; ticking/unticking a line toggles all lines of the same master PO. Lines that already have an ASN in column `ASN #` are unticked and greyed ("already has ASN ..."). A red (error) row blocks **Start** until you fix the Excel file or untick it. Rows of one shipment (master PO) share a background colour.
- **One shipment per master PO** (the grouping option is fixed). Ship dates come from the Excel `EDI PO Start/End Ship` columns (midpoint of the overlap); the dates on the PO page are only cross-checked.
- **Cartons.** Qty per carton = `Pack`, cartons = `Order Units / Pack` (must be a whole number). The tool compares with the web *Qty Ordered*: equal to Order Units -> Pack per carton; equal to Order Units / Pack (prepack) -> 1 per carton; anything else pauses the run. Weight per PO line = `Gross Weight/Carton(kg)` exactly as in the file (change this in Settings > Workflow > *Weight for PO-tracker files*).
- **Factory per run.** The tracker has no factory column: choose the ship-from factory every run (the last one is pre-selected and remembered when you click Start).
- **Write-back copy.** After each shipment the Web Shipment ID is written into column `ASN #` of a copy `<name>_ASN_<YYYYMMDD-HHMMSS>.xlsx` next to the original (or in the run folder if that folder is read-only). The original and the `Submit ASN # (w/ Date)` column are never touched; dry runs write nothing. Paste the ASN numbers into the master tracker after you submit.
- **Review between shipments.** Settings > Workflow > *Pause for review between shipments* controls the pause after each shipment is filled in.

## 5. Dry run and mock mode

- **Dry run** (the *Dry run* option): the tool goes right up to the shipment's Save button and then stops, saving nothing on the portal. Recommended for the first run on the real site.
- **Mock mode** (practice without network): run `EDI Assistant.exe --mock` - the app starts a local fake EDI portal. Or enable "Use the mock site for practice" in Settings and run `python -m edi_assistant.mock_edi --port 8765` separately.
- Other command-line options: `--minimized` (start in the tray), `--data-dir PATH` (change where data is stored).

## 6. Calibrating selectors (Calibrate / Learn)

When the website changes its layout or the tool cannot find a button/field, use *Tools > Calibrate selectors...*:

1. Open the browser and go to the right page (quick buttons: Inbox, New Shipment, Drafts).
2. Choose a key in the list (unverified keys, marked with a cross, are listed first). If the key needs a PO/Site No, fill in the "Substitution variables" box.
3. **Highlight** shows which element the tool currently picks; **Test** shows the lookup result.
4. If it is wrong or not found: click **Pick on page**, then click the right element in the browser (Esc to cancel). The new selector is saved and used first from then on.
5. **Forget learned** returns to the default selector. **Open Inspector** opens the Playwright Inspector for advanced users.

## 7. AI setup (optional) and cost

The tool works fully with **AI off**. When on, AI is only called when something goes wrong: proposing a new selector, explaining an error (in the interface language, English by default) or reading ship dates from an image. The maximum number of calls per run defaults to 8 (very cheap - usually a few cents per day).

*Tools > Settings... > AI:*

1. Choose a **provider preset**: Anthropic (Claude Haiku - cheap, or Claude Sonnet), OpenAI, Google Gemini, DeepSeek, Qwen, OpenRouter, Ollama (runs locally, no key needed).
2. Paste the **API key** and click **Test connection**.
3. Tick "Enable the AI assistant". You can turn off "Send screenshots to the AI" if the model does not support images or you want to send less data.

Security note: the API key is stored as plain text in `config.yaml` in the data folder; passwords and e-mail addresses on the page are masked before being sent to the AI. Do not use AI if company policy does not allow sending page screenshots.

## 8. Settings: human pace and language

*Tools > Settings... > Pace* (defaults in parentheses):

| Setting | Meaning |
|---|---|
| Enable human-pace mode (on) | Master switch for everything below. |
| Delay between actions (400-1200 ms) | Random delay between clicks / fills / selections. |
| Extra delay after each page load (1000-2000 ms) | Added after every navigation, after waiting for the page to load and the network to go idle. |
| Delay per typed character (30-80 ms) | Text fields are cleared, then typed key by key and verified (falls back to a plain fill once on mismatch). |
| Max shipments per hour (0 = unlimited) | The tool waits when this many shipments were already started within the last hour. |
| Pause between shipments (20-60 s) | Random pause before each next shipment of a run. |

*Settings > Website > Interface language* (`ui.language`: `en` or `vi`, default `en`). It takes effect after restarting the application.

## 9. Data location and logs

| Content | Portable | Installed version |
|---|---|---|
| Settings `config.yaml`, templates `templates\`, factories `factories.json`, learned selectors `selectors.learned.yaml` | `data\` next to the exe | `%APPDATA%\EDI Assistant` |
| Browser profile, fallback Chromium | `data\` | `%LOCALAPPDATA%\EDI Assistant` |
| Log `logs\edi_assistant.log` | `data\logs` | `%APPDATA%\EDI Assistant\logs` |
| Results `runs\<id>\results.csv`, `run.json` | `data\runs` | `%APPDATA%\EDI Assistant\runs` |

The menu *Tools > Open data folder* opens this folder directly. `results.csv` can be opened in Excel.

## 10. Troubleshooting

| Symptom | What to do |
|---|---|
| The browser does not open | Run *Help > System check...* and send the report to IT. Use the *full* zip if Edge automation is blocked. Otherwise install Microsoft Edge, or *Tools > Install Chromium browser...* and then change "Browser" in Settings. |
| Stops at "Login required" | Log in in the tool's browser window and click *Continue*. |
| "The site may be blocking us" | The site returned 403/429/503, an "Access Denied"/CAPTCHA page, or kept redirecting to the login page. The run is stopped on purpose. Wait a while, solve any verification in the browser, log in again if needed, then click *Continue* - or *Abort*. Consider raising the pace delays or setting a max shipments per hour. |
| "Element not found ..." | Do that step by hand on the page and click *Continue*; or calibrate the selector (section 6). |
| The *Start* button is locked | There are red rows in the table, no factory is chosen, or the column mapping is not confirmed. |
| Quantity not divisible by the carton count | Re-check the Quantity / Cartons columns in Excel and the mapping. |
| Cannot read ship dates | Enter the dates manually in the dialog, or enable AI vision. |
| PO shows "Replaced" | Follow the PO replacement procedure manually on the portal, then *Continue*. |
| No notification/sound | Enable them in Settings > Notifications; check Windows "Do not disturb". |
| Portable folder is not writable | Copy it to a writable folder; the app falls back to `%APPDATA%` if `data\` cannot be written. |
| Other errors | Send the `logs\edi_assistant.log` file and a screenshot of the dialog to your support contact. |

## 11. Developer note: notification identity

On Windows the app sets the AppUserModelID `ShyftGlobal.EDIAssistant` (and the installer's shortcuts carry it), so toasts and the taskbar show "EDI Assistant". When running from source on macOS/Linux (`python -m edi_assistant`), the OS attributes notifications to the Python interpreter, so they show as "Python" - this is expected and does not happen in the packaged Windows build.
