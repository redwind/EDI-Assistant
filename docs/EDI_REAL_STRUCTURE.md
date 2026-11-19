# Burlington EDI Gateway — real DOM structure (inspected read-only, 2026-10-18)

Base: `https://edi.coat.com/vms-gateway/`. Classic Struts/JSP, server-rendered, no iframes, plain `<form>` posts.
Page `<title>` is a reliable page identifier (some titles are wrong/odd, e.g. weight page says "Create User").

## 0. Login & vendor selection
- Login: `login.do` (title "Vendor Management Suite -- Login"). User ID prefilled; user types password, clicks "Go". Tool must NEVER type the password → wait for user (detect title change).
- After login: "Vendor Management Suite -- Select Profile" (`login.do`) = "Search Vendor" page with a results table; click link text `SHYFT GLOBAL LLC` → `vendor.do?vendor_id=...&profile` (title "... -- View Profile") → click button `EDI Gateway` (input submit, value "EDI Gateway") → inbox.
- Session-expired detection: title contains "-- Login".
- News banner on Select Profile page: "DC addresses have been changed... CA=512, NJ=053, GA=934" (TO site numbers).

## 1. Inbox — `gateway/inbox.do` (title "Vendor Management Suite -- EDI Gateway Inbox")
- Tabs: links `inbox.do`, `outbox.do`, `drafts.do` (SHIPMENTS tab → drafts.do).
- Filter form `name="filterinbox"` action `filter_inbox.do`:
  - checkboxes: `filter_unread, filter_read, filter_submitted, filter_resubmitted, filter_replaced, filter_acknowledged, filter_notshipped, filter_fullyshipped, filter_partiallyshipped`
  - text `documentID` (Document ID search), `start_date`, `end_date`
  - `input[type=submit][value=Search]`, `input[name=reset]` (Reset)
  - `select[name=orderperpage]` (10/…)
- Results: rows `tr.odd` / `tr.even` (+ class `unviewed` if unread). **Replaced rows have class `stricken`** (CSS `tr.stricken {text-decoration: line-through}`) — use class + Status text, not visual strikethrough.
  - cells: 0 #, 1 envelope (Read), 2 Type "850" (link), 3 Document ID link `view_order.do?order_id=<internal>&orderNo=<9-digit>`, 4 Transmission Date, 5 Status (SUBMITTED / RESUBMITTED / REPLACED / ACKNOWLEDGED…), 6 Shipment Status (Not Shipped / Partially / Fully), 7 Turn Around `[New Shipment]` link → `new_shipment.do` (generic, no PO param).
  - Pick row: Document ID == target 9-digit AND not `.stricken` AND status != REPLACED. Statuses seen on live data: SUBMITTED, RESUBMITTED (not only ACKNOWLEDGED) → accept any non-REPLACED.
- Opening `view_order.do` marks the order as read (side effect, acceptable in real runs).
- PO detail page (`view_order.do`) NOT inspected yet (would mark as read). Parse Early/Late Ship Date via regex on body text (format `09-MAR-26`), "Create New Shipment" button location unknown → keep label-based candidates.

## 2. Shipment header — `gateway/new_shipment.do` (title "Vendor Management Suite -- Shipment")
Existing draft URL: `new_shipment.do?readyForLabels=N&shipment_id=<id>&ReadOnly=false`.
Form `name="new_shipment" id="new_shipment"` action `new_shipment.do`, onsubmit `checkform(this) && validateSiteNo(...)`.
Hidden: `action, shipment_id, Dirty_Flag, required, AddUpdate, checkShipmentHasOrders, isInvoiceOnlyCustomer`.

| Field | Selector | Notes |
|---|---|---|
| Web Shipment ID | `#txtWebShipmentId` (readonly) | = ASN id after save |
| ASN Shipment ID | `#txtASNId` | auto = web id |
| Shipment With Cartons | `input[name=CartonRadio][value=Y]` | onclick shipWithCarton |
| Shipping Type | `#OptShippingType` | options `0`=Select One, `3`=Ship to DC |
| Transportation Method | `#OptTransMethod` | `O`=Containerized Ocean (also S=Ocean, A=Air …) |
| Shipping Date | `#txtShippingDate` | `MM/DD/YYYY`; has CalendarPopup; validateShippingDate JS |
| SCAC Code | `#OptSCACCode` | value `MAEU` text "MAEU-MAERSK"; onchange `setCarrier();DirtyFlag()` → fills carrier. After select_option, dispatch change (Playwright select_option does). |
| Carrier | `input[name=txtcarrier]` (readonly) | auto |
| Bill Of Lading | `input[name=txtBillLading]` | "unknown" (lowercase seen in live data; doc says Unknown) |
| PRO Number | `input[name=txtPRONumber]` | "unknown" |
| UPS Shipment | `input[name=chkShipment]` | leave unchecked |
| From Site No | `select[name=OptSiteNO]` | options: "" Select One, "Add New Address" (no saved sites). Leave "Select One"; onchange setFromSiteValues fills from option attrs (name11…). |
| From site no text | `input[name=txtSiteNO]` | leave empty |
| From Name | `#txtFromName` | required |
| From Address 1 | `#txtFromAddress1` | required |
| From Address 2 | `input[name=txtFromAddress2]` | no id |
| From City | `#txtFromCity` | required |
| From State | `#txtFromState` | required |
| From Zip | `#txtFromZip` | required |
| From Country | `#txtFromCountry` (select) | ONLY `US, CA, CN` + "More.." link → Vietnam etc. NOT in list! Need popup handling or flag for user. |
| To Site No | `input[name=optToSiteNo]` readonly (e.g. 512) | auto from PO when the shipment is opened from an order. On a blank New Shipment it is a dropdown that must be chosen from the Delivery Address state (EDI notice: CA=512, NJ=053, GA=934); exact select name not captured yet (`ship.to_site_select` is unverified) |
| To fields | `txtToName, txtToAddress1, txtToAddress2, txtToCity, txtToState, txtToZip, txtToCountryUnHidden` readonly | read for verification only |

Buttons:
- `<< Back To Drafts` (button, sendBackToDrafts())
- `Clear Values` `input[name=btnCancel]` (reset1()) — never click
- `Selected Purchase Orders >>` `#submit123` (submit; setAddUpdate('Update') → SAVES then goes to PO page). In read-only mode it is a plain `location.href='selected_pos.do'`.
- `Save` `#saveonly` (submit, setAddUpdate('Update'))
- `Cancel` `#cancelShipment` (confirm dialog → cancels shipment!) — NEVER click
- `Label` `input[name=label]`
- `Validate` `input[name=validateShipment]` (showLoadingOverlay) — do not click (user does)
- **`Submit ASN` `input[name=btnSubmitASN]` → `document.location.href='asn.do?shipment_id=<id>'`** — NEVER. Hard guard: Playwright `context.route("**/asn.do*", abort)` + refuse clicks on this element.
- Uses JS `confirm()` dialogs in places (Cancel) → register `page.on("dialog")` handler that DISMISSES by default.

## 3. Drafts list — `gateway/drafts.do` (title "BCF EDI Gateway -- Drafts")
Filter: Shipment ID, Purchase Order No, Invoice No, Shipment Status, Turn Around, dates. Table: Shipment ID link (`new_shipment.do?readyForLabels=N&shipment_id=...&ReadOnly=false`), Create Date, Status (CREATED/INVALID), State ("Shipment Created Ready To Add PO", "Site Added Ready for Validation", "PO has been replaced"). Archives: `archives.do`.

## 4. Selected Purchase Orders — `gateway/selected_pos.do` (title "BCF EDI Gateway -- Selected Purchase Orders")
Form `name="form1"` action `selected_pos.do`. Hidden: `action, webshipmentId, poHeaderID, purchaseOrderNo, packaging_code, cart_def_id, site, webShOrdId, webShOrdAddr, packing_type, complete_partial, carton_definition_name, required, selectedCartId, isCustomizedPage, savepo`.
Tabs: "Selected Purchase Orders", "Search Purchase Orders" (search tab not inspected — only visible on editable shipments).
Per PO row (keyed by internal poHeaderId N, discover via row containing the 9-digit PO text):
- checkbox `PO-N`
- PO number link (displayIds popup)
- `select[name=complete_shipment_N]` options `Complete`, `Partial`
- `select[name=web_sh_packing_type_id_N]` 0 Select One, 1 Pack all items of a specific PO in one carton, 2..5, **6 = Customized quantities and cartons** (default, disabled)
- `select[name=pack_code_N]` (id `pack_code`, dup ids!) options `CTN25` = "Corrugated or Solid Carton" (default), CTN01/31/76/79/94, BAG*, PLT*
- button `Save` onclick `saveCarton('saveCarton', N, '<po>', 'Y')` → posts row values (complete_partial etc.)
- button `Create Carton` onclick `insertCarton('insertCarton', N, '<po>', 'Y')`
- expand arrow `javascript:expandSubmit('N','poHeaderId','')` shows existing "Carton Definition:X11…" links.
Bottom: `<< Back To Shipment Header` (sendBackToShipmentHeader()), `View Shipment Orders Detail` `input[name=poSiteShipment]` → `po_site_shipment.do?shipment_id=<id>`, `Validate Shipment` `input[name=validateShipment]`, Submit ASN (never).
- "Remove" link + "Export … PDF" (`SelectedPurchaseOrdersListPDFServlet.do`).

## 5. Carton page (Create Carton) — NOT inspected (requires a write action). Rely on screenshots image10–16 + calibrate mode. Note "Physical Container - Carton" packaging code appears on the carton page (different list from row pack_code).

## 6. Weight page — `gateway/po_site_shipment.do?shipment_id=<id>` (title wrongly "Vendor Management Suite -- Create User")
Form `name="po_site_shipment"`. Hidden `actionItemAdded, editedElement`.
- `select[name=commonunit]` "Change ALL Weight UM": Select One / KG / LB (onchange updateDD())
- `select[name=orderperpage]` 10/15/20/25/100000(All) → set All first if >10 lines (onchange reloads page).
- Per row (internal id M): `input[name=editedSiteWgtquM]` (id `editedSiteWgtM`) weight, `select[name=editedSiteWgtumM]` KG/LB; onchange `setHiddenOnChange(M)` — must fire change event (use fill + dispatch 'change').
- Table headers: PO #; SITE; ADDRESS; CITY; STATE; LADING QUANTITY; WEIGHT; WEIGHT UM → locate row by PO # text.
- `Back To Select Purchase Order` (`input[name=backtoorders]`), `Save` `input[name=SaveCarton2]` onclick `checkAndSaveCarton()`.
