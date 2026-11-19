# Burlington EDI Gateway - DOM reference

Base: `https://edi.coat.com/vms-gateway/`. Classic Struts/JSP, server-rendered, no iframes, plain `<form>` posts.
The page `<title>` is the most reliable page identifier (some titles are odd, e.g. the weight page says "Create User").

Legend: VERIFIED = inspected live on production (read-only). UNVERIFIED = described from screenshots only
(selectors guessed) - take a screenshot / read the DOM on first use and trust what you see over this file.

Read the section for the page you are on; you do not need the whole file at once.

## Safety map (summary of dangerous controls)
| Control | Selector | Effect | Rule |
|---|---|---|---|
| Submit ASN | `input[name=btnSubmitASN]` | `document.location.href='asn.do?shipment_id=<id>'` - transmits ASN to Burlington | NEVER click; never navigate to `asn.do` |
| Cancel (shipment) | `#cancelShipment` | confirm() then cancels the shipment | NEVER |
| Clear Values | `input[name=btnCancel]` | reset1() wipes header fields | NEVER |
| Validate / Validate Shipment | `input[name=validateShipment]` | server validation, changes shipment state | leave to the human |
| Remove (PO link / "Remove Selected Line Items/Sites") | link text | removes POs/items/sites | avoid |
| Label | `input[name=label]` | label generation | not needed |

Optional hard guard from JS: `window.confirm = () => false;` right after each navigation (resets on every page load) on pages
where no confirm is expected; override to `() => true` only immediately before the legitimate "Add Selected" clicks.

## 0. Login & vendor selection (VERIFIED)
- Login: `login.do`, title "Vendor Management Suite -- Login". User ID is prefilled; the user types the password and clicks "Go".
  NEVER type the password. Wait for the title to change.
- Session-expired detection: title contains "-- Login".
- After login: title "Vendor Management Suite -- Select Profile" (`login.do`) = "Search Vendor" page with a results table.
  Click the link text `SHYFT GLOBAL LLC` -> `vendor.do?vendor_id=...&profile` (title "... -- View Profile")
  -> click the submit button `EDI Gateway` (input submit, value "EDI Gateway") -> inbox.
- News banner on Select Profile page: "DC addresses have been changed ... CA=512, NJ=053, GA=934" (TO site numbers).

## 1. Inbox - `gateway/inbox.do` (VERIFIED)
Title "Vendor Management Suite -- EDI Gateway Inbox".
- Tabs: links `inbox.do`, `outbox.do`, `drafts.do` (SHIPMENTS tab -> drafts.do).
- Filter form `name="filterinbox"` action `filter_inbox.do`:
  - checkboxes: `filter_unread, filter_read, filter_submitted, filter_resubmitted, filter_replaced, filter_acknowledged, filter_notshipped, filter_fullyshipped, filter_partiallyshipped`
  - text `documentID` (Document ID search), `start_date`, `end_date`
  - `input[type=submit][value=Search]`, `input[name=reset]` (Reset)
  - `select[name=orderperpage]` (10/...)
- IMPORTANT: Document ID search needs the full 9-digit id (master PO + 2-digit line suffix); the master PO alone returns nothing.
- Results: rows `tr.odd` / `tr.even` (+ class `unviewed` if unread). **Replaced rows have class `stricken`**
  (CSS `tr.stricken {text-decoration: line-through}`) - use class + Status text, not the visual strikethrough.
  - cells: 0 #, 1 envelope (Read), 2 Type "850" (link), 3 Document ID link `view_order.do?order_id=<internal>&orderNo=<9-digit>`,
    4 Transmission Date, 5 Status (SUBMITTED / RESUBMITTED / REPLACED / ACKNOWLEDGED ...),
    6 Shipment Status (Not Shipped / Partially / Fully), 7 Turn Around `[New Shipment]` link -> `new_shipment.do` (generic, no PO param).
  - Pick row: Document ID == target 9-digit AND not `.stricken` AND status != REPLACED.
    Accept any non-REPLACED status (SUBMITTED, RESUBMITTED, ACKNOWLEDGED all seen).
- Opening `view_order.do` marks the order as read (harmless side effect).

Snippet (find the row and its link):
```js
const id='580367401';
[...document.querySelectorAll('tr.odd,tr.even')].filter(tr=>tr.cells[3]&&tr.cells[3].innerText.trim()===id)
 .map(tr=>({stricken:tr.classList.contains('stricken'),status:tr.cells[5].innerText.trim(),href:tr.cells[3].querySelector('a')?.href}))
```

## 1b. PO detail - `gateway/view_order.do?order_id=..&orderNo=..` (UNVERIFIED)
- Contains Early Ship Date ("Start ship") and Late Ship Date ("Cancel date"), format `09-MAR-26` -> regex `\d{2}-[A-Z]{3}-\d{2}` near those labels.
- Shows the delivery (ship-to) address (site 512 / 053 / 934) and the item table (SKU, Qty Ordered, prepack subitem lines if any).
- Has a "Create New Shipment" button/link (location unknown). Find by text, e.g. a control whose text/value contains "New Shipment".
  Clicking it leads to `new_shipment.do` with this PO as context (the To address then arrives pre-filled).
- Take a screenshot on first visit; use `get_page_text` to read dates.

## 2. Shipment header - `gateway/new_shipment.do` (VERIFIED)
Title "Vendor Management Suite -- Shipment". Existing draft: `new_shipment.do?readyForLabels=N&shipment_id=<id>&ReadOnly=false`.
Form `name="new_shipment" id="new_shipment"` action `new_shipment.do`, onsubmit `checkform(this) && validateSiteNo(...)`.
Hidden: `action, shipment_id, Dirty_Flag, required, AddUpdate, checkShipmentHasOrders, isInvoiceOnlyCustomer`.

| Field | Selector | Notes |
|---|---|---|
| Web Shipment ID | `#txtWebShipmentId` (readonly) | = ASN id after save |
| ASN Shipment ID | `#txtASNId` | auto = web id |
| Shipment With Cartons | `input[name=CartonRadio][value=Y]` | onclick shipWithCarton |
| Shipping Type | `#OptShippingType` | options `0`=Select One, `3`=Ship to DC |
| Transportation Method | `#OptTransMethod` | `O`=Containerized Ocean (also S=Ocean, A=Air ...) |
| Shipping Date | `#txtShippingDate` | `MM/DD/YYYY`; CalendarPopup; validateShippingDate JS |
| SCAC Code | `#OptSCACCode` | value `MAEU` text "MAEU-MAERSK"; onchange `setCarrier();DirtyFlag()` fills carrier. Dispatch `change` after setting. |
| Carrier | `input[name=txtcarrier]` (readonly) | auto from SCAC |
| Bill Of Lading | `input[name=txtBillLading]` | "unknown" (lowercase seen in live data) |
| PRO Number | `input[name=txtPRONumber]` | "unknown" |
| UPS Shipment | `input[name=chkShipment]` | leave unchecked |
| From Site No | `select[name=OptSiteNO]` | options: "" Select One, "Add New Address" (no saved sites). Leave "Select One"; onchange setFromSiteValues fills from option attrs. |
| From site no text | `input[name=txtSiteNO]` | leave empty |
| From Name | `#txtFromName` | required |
| From Address 1 | `#txtFromAddress1` | required |
| From Address 2 | `input[name=txtFromAddress2]` | no id |
| From City | `#txtFromCity` | required |
| From State | `#txtFromState` | required |
| From Zip | `#txtFromZip` | required |
| From Country | `#txtFromCountry` (select) | ONLY `US, CA, CN` + "More.." link (popup) for Vietnam etc. Not in the list -> ask the user to pick manually. |
| To Site No | `input[name=optToSiteNo]` readonly (e.g. 512) | auto from PO when the shipment is opened from an order. On a blank New Shipment it is a dropdown that must be chosen from the Delivery Address state (EDI notice: CA=512, NJ=053, GA=934); exact select name not captured yet (`ship.to_site_select` is unverified) |
| To fields | `txtToName, txtToAddress1, txtToAddress2, txtToCity, txtToState, txtToZip, txtToCountryUnHidden` readonly | verify only |

Buttons:
- `<< Back To Drafts` (sendBackToDrafts()).
- `Clear Values` `input[name=btnCancel]` (reset1()) - never.
- `Selected Purchase Orders >>` `#submit123` (submit; setAddUpdate('Update') SAVES then goes to the PO page; read-only mode: plain `location.href='selected_pos.do'`).
- `Save` `#saveonly` (submit, setAddUpdate('Update')) - the first Save generates the Web Shipment/ASN id. Needs user confirmation of the plan first.
- `Cancel` `#cancelShipment` - never. `Label` `input[name=label]` - not needed.
- `Validate` `input[name=validateShipment]` - human only.
- `Submit ASN` `input[name=btnSubmitASN]` - never.

Fill helper (sets value AND fires change/input):
```js
const set=(sel,val)=>{const e=document.querySelector(sel);e.value=val;
  e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));};
```
For the SCAC select prefer `form_input` (real option selection) and then confirm `txtcarrier` got filled.

## 3. Drafts list - `gateway/drafts.do` (VERIFIED)
Title "BCF EDI Gateway -- Drafts". Filter: Shipment ID, Purchase Order No, Invoice No, Shipment Status, Turn Around, dates.
Table: Shipment ID link (`new_shipment.do?readyForLabels=N&shipment_id=...&ReadOnly=false`), Create Date, Status (CREATED/INVALID),
State ("Shipment Created Ready To Add PO", "Site Added Ready for Validation", "PO has been replaced"). Archives: `archives.do`.

## 4. Selected Purchase Orders - `gateway/selected_pos.do` (list VERIFIED; Search tab UNVERIFIED)
Title "BCF EDI Gateway -- Selected Purchase Orders". Form `name="form1"` action `selected_pos.do`.
Hidden: `action, webshipmentId, poHeaderID, purchaseOrderNo, packaging_code, cart_def_id, site, webShOrdId, webShOrdAddr, packing_type, complete_partial, carton_definition_name, required, selectedCartId, isCustomizedPage, savepo`.
Page heading: "Select Purchase Orders / Web Shipment ID: <id> >> Selecting Purchase Orders".
Tabs: "Selected Purchase Orders" and "Search Purchase Orders".

### Search Purchase Orders tab (UNVERIFIED, from screenshot)
- Filter: text "Purchase Order No" (enter the 9-digit PO with line suffix), select "Status" (All), buttons `Search` / `Reset`.
- Result: "One Order found.", "Show [All] Orders Per Page", table with checkbox, Purchase Order No link, Status (Available).
- Buttons `Add Selected` / `Cancel` (Cancel only closes the search). Clicking `Add Selected` raises confirm
  "Do you want to add the selected Purchase Orders ?" -> OK is the intended answer here.
- After OK the PO appears under the "Selected Purchase Orders" tab.

### Selected Purchase Orders list (VERIFIED)
Per PO row (keyed by internal poHeaderId N; discover via the row containing the 9-digit PO text):
- checkbox `PO-N`; PO number link (displayIds popup)
- `select[name=complete_shipment_N]` options `Complete`, `Partial` (default Complete - always set Partial)
- `select[name=web_sh_packing_type_id_N]` 0 Select One, 1 Pack all items of a specific PO in one carton, 2..5, **6 = Customized quantities and cartons** (default, disabled)
- `select[name=pack_code_N]` (id `pack_code`, duplicate ids!) options `CTN25` = "Corrugated or Solid Carton" (default), CTN01/31/76/79/94, BAG*, PLT*
- button `Save` onclick `saveCarton('saveCarton', N, '<po>', 'Y')` -> posts row values (complete_partial etc.)
- button `Create Carton` onclick `insertCarton('insertCarton', N, '<po>', 'Y')`
- expand arrow `javascript:expandSubmit('N','poHeaderId','')` shows existing "Carton Definition:X11..." links; folder icon at row start; "Expand-All / Collapse-All" links.
Bottom: `<< Back To Shipment Header` (sendBackToShipmentHeader()), `View Shipment Orders Detail` `input[name=poSiteShipment]`
-> `po_site_shipment.do?shipment_id=<id>`, `Validate Shipment` `input[name=validateShipment]` (human), `Submit ASN` (never; greyed out until validated).
Also a "Remove" link and "Export ... PDF" (`SelectedPurchaseOrdersListPDFServlet.do`).

Snippet (internal id N for a PO):
```js
const po='580367401';
const row=[...document.querySelectorAll('tr')].find(tr=>tr.innerText.includes(po)&&tr.querySelector('select[name^=complete_shipment_]'));
const N=row.querySelector('select[name^=complete_shipment_]').name.replace('complete_shipment_','');
```
Note: several rows may match as ancestors; choose the innermost (smallest) `tr` that contains the select.

## 5. Create Carton page (UNVERIFIED - from screenshots; requires a write action to reach)
Reached via `Create Carton` on the PO row (`insertCarton(...)`). Heading:
"Create Carton Definition : Customized quantities and cartons / Web Shipment ID: <id> >> Purchase Order: <po> >> Carton Definition: <id>".
Layout (top to bottom):
1. Tabs "Selected Items" / "Search Items". Before adding, Selected Items is empty -> open "Search Items".
   - Search Items result: "One Item found." table (All/None checkbox, SKU No e.g. `PO6682542LN1` with prepack/sub-row, UPC, Style, Color, Size, UM, Ordered, Shipped), buttons `Add Selected` / `Cancel`.
     `Add Selected` raises confirm "Do you want to add the selected Items ?" -> OK. (Item checkbox is pre-checked.)
   - If the item has a prepack, a light-blue sub-row shows the prepack component (e.g. 46602776 RCS310DUC2 ... qty `6` unit `EA`).
     That number N is the prepack units per item -> Qty Per Carton = units_per_carton / N.
2. Selected Items form: `Carton Name` text (default "CARTON 1"), `Packaging Code` select (set to "Physical Container - Carton";
   default "Select One"), buttons `Save` and `Undo` next to it.
   Item row: checkbox, Sku/Upc/Prepack link, Style, Color/Size, Qty Ordered, **Qty Per Carton** text input (default 0), Unit of Measure (AS/EA).
   Link `Remove Selected Line Items` (avoid).
3. Sites section: tabs "Selected Sites" / "Search Sites". Search Sites lists sites (All/None checkbox, Site 512, Address 570 EAST MILL STREET, City SAN BERNARDINO, State CA, Zip 92408),
   buttons `Add Selected` / `Cancel`; confirm "Do you want to add the selected Items ?" -> OK.
   Selected Sites row: State, City, Site No (512), Site Name/Address, **Cartons Per Site** text input (default 0). Link `Remove Selected Sites` (avoid).
4. Bottom bar: `<< Back to Purchase Order`, `Auto populate Qty (Carton & Site)`, `Auto populate Qty (Site)`, `Save`, `Undo`.
   Prefer typing the two numbers yourself over the auto-populate buttons. Two `Save` buttons exist (one by Packaging Code, one at the bottom): the bottom one saves the whole definition; click it after filling both numbers, then verify the saved values after the page reloads.
Before using any selector on this page, run a DOM dump of `input[type=text]`, `select`, `input[type=button],input[type=submit]` (name, id, value) and record it.

## 6. Weight page - `gateway/po_site_shipment.do?shipment_id=<id>` (VERIFIED)
Title wrongly "Vendor Management Suite -- Create User". Form `name="po_site_shipment"`. Hidden `actionItemAdded, editedElement`.
- `select[name=commonunit]` "Change ALL Weight UM": Select One / KG / LB (onchange updateDD())
- `select[name=orderperpage]` 10/15/20/25/100000(All) -> set All first if more than 10 lines (onchange reloads the page).
- Per row (internal id M): `input[name=editedSiteWgtquM]` (id `editedSiteWgtM`) weight, `select[name=editedSiteWgtumM]` KG/LB;
  onchange `setHiddenOnChange(M)` - the change event MUST fire (type then Tab/blur, or dispatch `change`).
- Table headers: PO #; SITE; ADDRESS; CITY; STATE; LADING QUANTITY; WEIGHT; WEIGHT UM -> locate the row by the PO # text.
- `Back To Select Purchase Order` (`input[name=backtoorders]`), `Save` `input[name=SaveCarton2]` onclick `checkAndSaveCarton()`.

## 7. PO replaced page (UNVERIFIED - screenshots)
In `selected_pos.do` a replaced PO shows the red link "Replaced" in the Status column. Clicking it opens a page "PO <n> has been replaced"
with a select "Replace Option" (value text "Remove Replaced PO and Transfer Items to New PO") and a `<<Back to ...` button, plus a button (Replace PO).
Confirm dialog: "Do you want to Remove Replaced PO and Transfer Items to New PO?" -> OK. See procedure.md "PO replaced workflow".

## Dialog notes
confirm() boxes seen: "Do you want to add the selected Purchase Orders ?", "Do you want to add the selected Items ?" (OK = intended),
shipment Cancel confirm (never reach it), "Remove Replaced PO and Transfer Items to New PO?" (only in the replaced workflow).
A native dialog blocks the extension's tools; if one appears unexpectedly, dismiss it with Cancel unless it is one of the intended ones above.
