# Run checklist - create DRAFT ASN shipment(s)

Selectors: see edi_dom.md. After every step verify the expected page title/state before continuing; any surprise
(row not found, wrong title, error text, quantity mismatch) = stop and tell the user in Vietnamese.
Take a screenshot on pages marked UNVERIFIED in edi_dom.md.

Script paths below are relative to the skill directory (`SKILL_DIR`).

## Step 0 - Prepare (no browser writes)
1. `python SKILL_DIR/scripts/parse_packing_list.py <xlsx>` -> parsed JSON (save to a scratch file). Read `profile`, `errors`, `blocking`, `confidence`, `totals_check`.
   Low confidence or errors -> references/excel_mapping.md. `profile = po_tracker` (primary format): rows with an existing `ASN #` are in
   `skipped_with_asn` and are NOT processed (show them to the user; `--include-with-asn` only on request). One shipment per master PO.
   The factory is never in the file: ALWAYS ask which factory this run ships from.
2. Factory: `python SKILL_DIR/scripts/factories.py find "<factory_name_guess>"`. Match -> use it. No match -> ask the user for
   Name, Address 1, Address 2, City, State, Zip, Country (offer `factory_address_guess` as a draft) and save with `factories.py add --json ...`.
   Country other than US/CA/CN -> tell the user they will have to pick it via "More.." themselves.
3. Decide grouping: tracker = one shipment per master PO (fixed). Packing list = one shipment for the whole file (default) or one per master PO (only if the user asks; use `--per-master`).

## Step 1 - Login and inbox
- Open https://edi.coat.com/vms-gateway/ in a tab (Chrome tab group). Title contains "-- Login" -> ask the user to log in; poll title.
- Select Profile -> click `SHYFT GLOBAL LLC` -> click `EDI Gateway` button. Expect title "... -- EDI Gateway Inbox".

## Step 2 - Find each PO line and read its dates
For each `document_id` (9 digits):
1. In inbox fill `documentID` with the 9-digit id, click Search (clear status filters if rows are hidden).
2. Choose the row: Document ID == id, no class `stricken`, status != REPLACED. Zero rows -> stop (wrong suffix? ask user).
   Two valid rows -> stop and ask.
   Tracker: the dates are in the Excel (`start_ship`/`end_ship`); the PO page dates are a cross-check only - a difference is a warning, never a blocker.
   You still open the PO page because `Create New Shipment` is there.
3. Open the PO (`view_order.do`). Read Early Ship Date and Late Ship Date (`DD-MON-YY`), the ship-to site (512/053/934) and the item
   table: Qty Ordered, and whether the item has a prepack subitem (and its unit count N).
4. Record: dates, ordered qty, prepack N, ship-to site. Warn if Excel quantity > Qty Ordered. Warn if the ship-to sites of the
   PO lines in one shipment differ (one shipment has one To address) - ask the user.
5. Collect dates for all lines, then run
   `python SKILL_DIR/scripts/plan_shipment.py parsed.json --dates 'DOC=09-MAR-26,13-MAR-26;DOC2=...' --prepack 'DOC=N' --ordered 'DOC=Q' --format table`
   (add `--per-master` if requested). Exit code 1 / BLOCKING lines (no date intersection, non-integer units, missing dates) = stop and ask.
   `SHIP_DATE_IN_PAST` in issues = the midpoint was in the past and today's date is used: mention it in the plan (not a blocker).

## Step 3 - Confirm the plan (the gate before the first write)
Show the table: PO line | container | model | ship window | cartons | qty/carton | weight KG, ship date (and window), factory (from address), To site, grouping.
Wait for an explicit "ok/đồng ý". Nothing has been written to EDI until now except the harmless "read" flag on POs.

## Step 4 - Shipment header
1. From the first PO's detail page click "Create New Shipment" (find by text). Expect title "Vendor Management Suite -- Shipment", `new_shipment.do`.
2. Fill: `#OptShippingType`=3 (Ship to DC); `#txtShippingDate`=ship date MM/DD/YYYY; `#OptTransMethod`=O;
   `#OptSCACCode`=MAEU (then check `txtcarrier` is now filled); `txtBillLading`=unknown; `txtPRONumber`=unknown;
   From fields from the factory record; Shipment With Cartons radio Y stays selected. Leave From Site No = Select One.
3. Verify the To block (site number, address) is filled and equals the PO ship-to (512 CA / 053 NJ / 934 GA).
4. Click `#saveonly` (Save). Expect the same page with `#txtWebShipmentId` now non-empty -> record it as the ASN / Web Shipment ID.
   Page shows validation text (e.g. "required") -> fix field, never work around it.

## Step 5 - Add the PO lines to the shipment
1. Click `#submit123` ("Selected Purchase Orders >>") (it also saves). Expect title "BCF EDI Gateway -- Selected Purchase Orders".
2. Tab "Search Purchase Orders" -> Purchase Order No = 9-digit id -> Search -> tick the checkbox of the matching row only ->
   `Add Selected` -> OK in the confirm. Repeat per PO line (or search each and add one by one). The PO must then appear in the
   Selected Purchase Orders list. (UNVERIFIED page: screenshot first.)

## Step 6 - Carton per PO line (repeat for every line)
1. Get internal id N of the row (edi_dom.md snippet) - the row containing the 9-digit id.
2. Click that row's `Create Carton`. Page heading "Create Carton Definition ... Purchase Order: <po>" (UNVERIFIED - screenshot).
3. Tab "Search Items" -> tick the item -> `Add Selected` -> OK. Read the prepack sub-row (N units) if present.
4. Search Sites -> tick the site (must match To site) -> Add Selected -> OK.
5. Packaging Code = "Physical Container - Carton". Qty Per Carton = units_per_carton / N when prepack N exists, else units_per_carton
   (use the plan's `qty_per_carton`). Cartons Per Site = cartons.
   Tracker: read the web `Qty Ordered` first and re-run `plan_shipment.py ... --ordered DOC=Q`: == Order Units -> Qty Per Carton = Pack;
   == Order Units / Pack -> Qty Per Carton 1; otherwise STOP and ask. Cartons Per Site = Order Units / Pack. Before Save verify
   `qty per carton x cartons per site == Qty Ordered`. Leave Carton Name as is.
6. Save (bottom Save). Re-read the fields to confirm the saved values (qty per carton, cartons per site). Qty Ordered unchanged.
7. `<< Back to Purchase Order` -> in that PO row set `complete_shipment_N` = Partial (always) -> row `Save`.
   Confirm it still reads Partial after the page reloads.
Check after the loop: every PO line has its carton definition (expand arrow shows "Carton Definition: ...").

## Step 7 - Weights
1. Click `View Shipment Orders Detail` (`input[name=poSiteShipment]`). URL `po_site_shipment.do?shipment_id=<id>`
   (title says "Create User" - normal).
2. If more than 10 lines: `select[name=orderperpage]` = All (page reloads) first.
3. For each row (find by PO # text): weight input `editedSiteWgtquM` = total gross weight of that PO line, 2 decimals (e.g. 1020.00); tracker: = `Gross Weight/Carton(kg)` exactly as in the file, 2 decimals (NOT multiplied by cartons),
   unit select `editedSiteWgtumM` = KG. The `change` event must fire (setHiddenOnChange) - type + Tab, or set value and dispatch change.
   Easiest: `commonunit` = KG first, then fill the weights.
4. Click `Save` (`input[name=SaveCarton2]`). Re-read the inputs after the reload to confirm values persisted.

## Step 8 - Finish
Leave the browser on the shipment (or Selected Purchase Orders) page. Do NOT click Validate, Label, Submit ASN.
Report to the user in Vietnamese (see SKILL.md). Mention the ASN/Web Shipment ID.
Tracker: run `python SKILL_DIR/scripts/write_asn.py <xlsx> --asn DOC=ASN ... --out <copy>` for the lines of this shipment (same `--out` for the whole run), never into the original
or the `Submit ASN # (w/ Date)` column, and tell the user the copy path. Then continue with the next master PO (a failing PO does not cancel the others - ask).

## Finding a draft you already created
`drafts.do` -> filter by Shipment ID or PO -> open the link `new_shipment.do?...shipment_id=<id>&ReadOnly=false`.
If the user asks to resume, continue from the step the draft state indicates ("Shipment Created Ready To Add PO" = step 5).

## PO replaced workflow (secondary - only when the user asks)
Context: Burlington replaced a PO after the shipment already contained it (status link "Replaced" in the selected PO list).
1. Open the shipment (`drafts.do` -> shipment) -> `Selected Purchase Orders >>`.
2. In the row of the replaced PO click the red "Replaced" status link. Page text: "PO <n> has been replaced".
3. Pick the option "Remove Replaced PO and Transfer Items to New PO" in the select, click the Replace PO button, and answer OK
   to "Do you want to Remove Replaced PO and Transfer Items to New PO?" (this is the one place where this confirm is intended).
4. Back in the PO list check that the new PO line appears and its carton definition was transferred (open Create Carton to compare).
5. Re-check Complete/Partial = Partial, carton quantities and weights (Step 6-7) for the new PO.
6. The human runs Validate and regenerates the labels. Never click Validate/Label/Submit yourself.
This flow is UNVERIFIED (screenshots only): screenshot each page before acting and stop on anything different.
