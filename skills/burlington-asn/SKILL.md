---
name: burlington-asn
description: Create DRAFT ASN shipments on the Burlington EDI Gateway (edi.coat.com/vms-gateway) from a PO-tracker Excel (MDDP tracker, primary) or a factory packing-list Excel (PKL, secondary) - fills in the shipment header, PO lines, cartons and weights, and never submits (the human reviews, validates and submits). Use whenever the user mentions "tạo shipment", "tạo ASN", "tạo draft ASN", "nhập packing list lên EDI Burlington", "nhập PKL lên EDI", "làm shipment cho PO", "PO tracker", "MDDP", "tracker excel", "Q4 Pet Beds", "nhập tracker lên EDI", "làm ASN từ tracker", "create shipment from PKL excel", "create ASN for Burlington", "enter packing list on EDI", gives Burlington PO numbers (7-digit like 5803674 or 9-digit like 580367401) together with an Excel packing list, mentions edi.coat.com, the EDI Gateway, VMS gateway, SHYFT GLOBAL LLC, or asks about "PO replaced"/"PO bị replace" on a shipment. Trigger even if the user only drops an Excel PO tracker or packing list and says "làm ASN" or "lên shipment".
---

# Burlington ASN draft creator

You create **draft** ASN shipments in the Burlington EDI Gateway from a PO-tracker (format A, primary) or packing-list (format B) Excel file, using the Claude-in-Chrome
browser tools. You fill everything in, then stop. A human reviews the draft, runs Validate and clicks Submit ASN.

Talk to the user in **Vietnamese** (short, clear). Keep code, selectors and this file in English.

## Why the safety rules exist
This is Burlington's production EDI system. A submitted ASN is transmitted to the customer and cannot be taken back; a cancelled
shipment or a wrong submission costs real money and trust. So the job is "prepare accurately, never commit". Follow these as hard rules:

1. **Never click `Submit ASN`** (`input[name=btnSubmitASN]`) and never navigate to any `asn.do` URL. It sends the ASN to Burlington.
2. **Never click** `Cancel` (`#cancelShipment`, cancels the shipment), `Clear Values` (`input[name=btnCancel]`), `Remove`
   links, `Validate` / `Validate Shipment` (`input[name=validateShipment]`, left to the human) or `Label`. Do not run JS that clicks them or submits their forms.
3. **Never type the password.** If the page title contains `-- Login`, ask the user to log in themselves in that tab, then poll the title and continue.
4. **Plan confirmation before the first write.** Before the first Save of the shipment header, show the user a compact plan and get an explicit yes.
   Afterwards run through the steps without asking each time - but **stop on any anomaly**: PO row not found, quantity mismatch,
   unexpected page title, validation/error text on the page, an unexpected dialog, values that did not persist after Save.
5. **Confirm dialogs**: the gateway uses `confirm()`. Only OK the intended ones ("Do you want to add the selected Purchase Orders / Items ?",
   and in the replaced workflow "Remove Replaced PO and Transfer Items to New PO?"). Cancel everything else, especially anything about cancelling.
   If Chrome shows a native dialog the extension cannot see, ask the user to press the right button.
6. The rule of thumb when in doubt: do not click it, ask.

## Input formats
**Format A - PO tracker (primary).** The MDDP tracker workbook (sheet `Vendor `, header in row 1). Columns used: `Master PO #` (D, merged cells:
inherit the value downwards), `Line #` (E, text `01`), `ASN #` (F), `Model #`, `Container`, `Order Units` (J), `EDI PO Start Ship` (M),
`EDI PO End Ship` (N), `Pack` (Q), `Gross Weight/Carton(kg)` (T). Rules:
- PO line id = Master PO + Line # (e.g. 5820678 + 02 -> `582067802`). Merged cells never mean "same PO" - only A-D identity columns are inherited.
- **One shipment per master PO** (always, for this format).
- **Ship date** = midpoint (floor) of the intersection of the lines' `EDI PO Start/End Ship` windows. The Excel dates are authoritative;
  the dates on the PO page are only a cross-check (report a difference, do not block). Still open the PO page: `Create New Shipment` lives there.
- **Qty Per Carton = Pack**, **Cartons Per Site = Order Units / Pack** (must be an integer). On the carton page compare with the web
  `Qty Ordered`: == Order Units -> Pack per carton; == Order Units / Pack (prepack) -> 1 per carton; anything else -> stop and ask.
  Before Save check `qty per carton x cartons per site == Qty Ordered`.
- **Weight per PO line = `Gross Weight/Carton(kg)` as-is**, 2 decimals, KG (it is NOT a total - do not multiply).
- Rows whose `ASN #` is already filled are **skipped** unless the user says to include them (`--include-with-asn`).
- **Ask the factory every run** (the tracker has no factory column).
- The block below the data (a second mini-table after a blank row) is not data; the parser stops at the first blank row / auto-filter end.
- After each shipment, write its ASN into column `ASN #` of a **copy** `<name>_ASN_<timestamp>.xlsx` with `scripts/write_asn.py`.
  Never write into the original, and never into `Submit ASN # (w/ Date)`.

**Format B - factory packing list (secondary).** Rules in Step 0 below ("packing_list" profile); grouping default is one shipment per file.

## Inputs to collect
- Excel path (required; the parser auto-detects the format and prints `profile`). Master PO numbers are inside the Excel; if the user also lists POs, cross-check them.
- Grouping: format A = one shipment per master PO (fixed); format B = default **one shipment per Excel file**, one per master PO only if the user asks.
- Factory (From address): see Step 0 (format A: always ask).
- The user must be logged in to edi.coat.com in Chrome (you never handle credentials).

## Tools and working style
Load the Chrome tools first (ToolSearch for the claude-in-chrome tools: tabs_context_mcp, tabs_create_mcp, navigate, read_page,
get_page_text, find, form_input, computer, javascript_tool). Use a dedicated tab. Prefer reading page state through JS/DOM
(selectors in `references/edi_dom.md`) because it is fast and exact; take screenshots when a page is unfamiliar - the Search
Purchase Orders tab, PO detail page and Create Carton page have **unverified** selectors, so look first and record what you see
before relying on a selector. Selects must be set so that `change` events fire (`form_input`, real clicks, or JS that sets the value
and dispatches `change`) - the page logic (`setCarrier`, `setHiddenOnChange`) depends on it. After every save re-read the page to
confirm the values really persisted.

Files in this skill (read on demand):
- `references/edi_dom.md` - per-page URLs, titles, selectors, dangerous controls. Read the section of the page you are on.
- `references/procedure.md` - the full step-by-step checklist with checks, and the PO-replaced workflow. **Read it before starting a run.**
- `references/excel_mapping.md` - read when the parser has low confidence or the layout is new.
- `scripts/parse_packing_list.py` (both formats), `scripts/plan_shipment.py`, `scripts/factories.py`, `scripts/write_asn.py` (tracker write-back) - helpers (Python 3.9+, openpyxl only).
  Run them with the Bash tool; if openpyxl is missing, `pip install openpyxl`.

## Workflow overview

### Step 0 - Parse the Excel and prepare (no browser writes)
```
python scripts/parse_packing_list.py "<file.xlsx>" > parsed.json      # add --include-with-asn only if the user asks
```
`profile` in the output is `po_tracker` or `packing_list`. For `po_tracker`: `lines[]` carry `document_id`, `order_units`, `pack`, `cartons`,
`gross_weight_per_carton`, `start_ship`/`end_ship` (ISO), `container`, `model_no`; rows that already have an ASN are listed in
`skipped_with_asn` (tell the user which). `blocking` (non-integer Order Units / Pack, missing values, duplicate ids) = stop and ask.
Then ask the user which factory (From address) this run ships from. The rest of this step describes the packing-list output.

Packing-list output: detected columns, `lines[]` (one per Excel row = one PO line: `document_id`, cartons, quantity, `units_per_carton`, `gross_weight`),
`totals_check`, `factory_name_guess`, `blocking`, `errors`. Business rules the parser encodes:
- Each Excel row is one PO line. A 9-digit PO is a full line id (e.g. `580367401`). A 7-digit master PO gets a line suffix 01, 02, ...
  by order of appearance of that master in the file (flagged as a warning - verify on the EDI that the line exists).
- Cartons Per Site = Packages. units_per_carton = Quantity / Packages and must be an integer; otherwise stop and ask the user.
- Weight = the total G.W. of that PO row, written with 2 decimals in KG.
Read `blocking`, `errors`, `confidence`: anything there means stop and resolve with the user (`references/excel_mapping.md`).
A totals mismatch (sum of lines vs the totals row) must be shown to the user. (Tracker files have no totals row.)

**Factory / From address**: `python scripts/factories.py find "<factory_name_guess>"`. The list lives in `~/.burlington-asn/factories.json`
(user-writable; created on first add). One match: use it and mention it in the plan. No match: ask the user for Name, Address 1,
Address 2, City, State, Zip, Country (propose `factory_address_guess` from the Excel footer), then save with
`python scripts/factories.py add --json '{...}'`. The Country select only has US/CA/CN; for another country (e.g. Vietnam) the
"More.." link must be used - ask the user to pick it manually and wait.

### Step 1 - Login and inbox
Open https://edi.coat.com/vms-gateway/. Login page -> ask the user to log in. Then Select Profile -> click `SHYFT GLOBAL LLC` ->
`EDI Gateway` button -> inbox (title "... -- EDI Gateway Inbox").

### Step 2 - Locate each PO line and read dates
(Tracker: dates come from the Excel; read the PO page's dates only as a cross-check.) In the inbox search Document ID with the **full 9-digit id** (master PO + 2-digit suffix; the master alone returns nothing).
Pick the row that is not replaced: class `stricken` (strikethrough) or status REPLACED means skip it. Open the PO, read Early Ship Date
and Late Ship Date (format `09-MAR-26`), confirm the delivery address/site (CA=512, NJ=053, GA=934), the Qty Ordered, and whether
the item shows a prepack subitem with N units. Warn if the Excel quantity exceeds Qty Ordered.

### Step 3 - Plan and confirm
```
python scripts/plan_shipment.py parsed.json --dates 'DOC=09-MAR-26,13-MAR-26;DOC2=...' [--prepack 'DOC=N'] [--ordered 'DOC=Q'] [--per-master] --format table
```
Tracker: `--dates` is optional (Excel wins; a different PO-page date only adds `WEB_DATES_DIFFER`), grouping is per master PO automatically,
and `--ordered DOC=Q` (web Qty Ordered) applies the Order-Units / Order-Units-per-Pack rule above and blocks on a mismatch.
- Ship date = midpoint of the intersection of all PO windows in the shipment, floor for even spans (Mar 9 & 13 -> Mar 11), `MM/DD/YYYY`.
  No intersection -> stop and ask the user. A midpoint that is already in the past becomes **today** (the script does this and
  reports `SHIP_DATE_IN_PAST`) - say so in the plan.
- Qty Per Carton = units_per_carton / N when the item shows a prepack subitem of N units (e.g. 6/6 = 1), else units_per_carton (e.g. 6).
- Show the user the table (PO line, container/model, ship window, cartons, qty/carton, weight KG), ship date, factory, To site, grouping, warnings. Wait for explicit confirmation.

### Step 4 - Shipment header (first write)
From the PO page click "Create New Shipment" -> `new_shipment.do`. Fill:
Shipping Type `Ship to DC` (value 3); Shipping Date; Transportation Method `Containerized Ocean` (value O);
SCAC `MAEU-MAERSK` (carrier fills itself - verify); Bill of Lading `unknown`; PRO Number `unknown`; From address = factory;
leave From Site No on "Select One" and UPS unchecked. To address is read-only: just verify it matches the PO. Click `Save`.
The Web Shipment ID that appears is the ASN number - note it for the report.

### Step 5 - Add PO lines
`Selected Purchase Orders >>` -> tab "Search Purchase Orders" -> search the 9-digit PO -> tick it -> `Add Selected` -> OK.

### Step 6 - Cartons, per PO line
Row `Create Carton` -> Search Items -> select item -> Add Selected -> OK -> Search Sites -> select the site -> Add Selected -> OK ->
Packaging Code `Physical Container - Carton` -> Qty Per Carton and Cartons Per Site -> Save -> `<< Back to Purchase Order` ->
set Complete/Partial to **Partial** (always) -> Save. Repeat for every PO line. Partial is always used, whether the
shipment is partial or complete, because the procedure doc says it reduces the likelihood of getting a quantity
error when creating the carton definition.

### Step 7 - Weights
`View Shipment Orders Detail` -> (set rows-per-page to All if more than 10 lines) -> weight per PO line, 2 decimals, unit KG, fire the
change event -> Save -> re-read to verify.

### Step 8 - Hand over (never submit)
Tracker: after each shipment run `python scripts/write_asn.py "<file.xlsx>" --asn DOC=ASN [--asn DOC2=ASN ...] --out "<same copy path for the whole run>"`
(one `--asn` per PO line of the shipment, all lines of a shipment get the same Web Shipment ID); report the copy path. The user pastes the ASNs
into the master tracker after submitting.
Leave the shipment page open. Do not Validate, do not Submit. Reply in Vietnamese with:
- ASN / Web Shipment ID (and link/URL of the draft);
- a table: each PO line with cartons, qty per carton, weight, plus ship date and factory;
- warnings (quantity above ordered, suffix assigned automatically, totals mismatch, anything skipped or edited manually);
- the reminder: kiểm tra lại -> bấm Validate -> rồi tự bấm Submit ASN.

## Edge cases
- Tracker: `Qty Ordered` neither Order Units nor Order Units/Pack, or one master PO fails: stop that shipment, report, ask whether to continue with the others.
- Row not found for a document id: stop; the suffix may be wrong or the PO replaced. Ask the user.
- More than one non-replaced row: stop and ask.
- A page shows an error/validation message: report the exact text, do not retry blindly.
- Draft already exists for these POs (check `drafts.do`) - ask before creating a duplicate.
- User asks to fix a PO that was replaced: follow "PO replaced workflow" in `references/procedure.md` (secondary flow, only on request).
- Session expires mid-run (title "-- Login"): ask the user to log in again, then resume from the current draft (drafts.do).
