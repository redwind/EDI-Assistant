# Handling a new Excel layout

## PO tracker (format A, primary)
`parse_packing_list.py` auto-detects it from the header row (needs `Master PO #`, `Line #`, `Order Units`, `Pack`, `Gross Weight/Carton(kg)`,
`EDI PO Start Ship`, `EDI PO End Ship`; optional `ASN #`, `Model #`, `Container`, `Styles Description`) and prints `"profile": "po_tracker"`.
Matching is by exact normalized header, so `Submit ASN # (w/ Date)` is never taken as `ASN #`. No mapping file is used for this format;
if detection fails force it with `--profile po_tracker` (errors list what is missing) or fall back to `--profile packing_list` + a mapping.
- Merged cells: Container / Shyft PO / Master PO (A-D) are merged over a PO's lines - the parser inherits the top-left value. Other merged
  columns (e.g. R, S over all rows) mean nothing; "merged" never means "same PO".
- `ASN #` may hold an int, text or the empty string `''`; any non-blank value = the line already has an ASN and is skipped.
- Secondary table: a second small table (e.g. `Master PO # | EDI PO Start Ship | ...`) may sit below the data after a blank row. The parser stops at the
  first row that is empty in the key columns (and at the auto-filter end) and never reads it.
- Dates are text `DD-MON-YY` (M/N); `Gross Weight/Carton(kg)` is per carton and is used as-is.
- Write-back: `scripts/write_asn.py` writes the `ASN #` column of a timestamped copy only.

## Packing list (format B, secondary)

The parser (`scripts/parse_packing_list.py`) recognises columns by header text (EN/ZH/VI synonyms). Fields:
`po` (required), `line` (optional 2-digit suffix column), `description`, `packages` (required, cartons), `quantity` (required),
`gross_weight` (required), `net_weight`, `size`.

## Flow
1. Run the parser. Check the printed JSON:
   - `confidence` = "high" and `errors` empty -> carry on, but still show the user the detected columns in your plan.
   - `confidence` = "low", `errors` mention missing columns, or `header_row` is null -> go to 2.
   - `mapping_source` starting with `saved:` means a saved mapping for this header fingerprint was applied automatically.
2. Show the user the first ~10 rows of the sheet (read them with openpyxl, or print the header candidates) and ask in Vietnamese which
   column is PO / cartons / quantity / gross weight (and which row is the header). Do not guess weights vs. net weights.
3. Write a mapping file in your scratch dir, e.g. `{"po":"A","packages":"C","quantity":"E","gross_weight":"F","net_weight":"G","description":"B","size":"H","header_row":4}`
   and re-run with `--mapping mapping.json`. Check lines and totals_check again.
4. Once the user confirms the result is right, save it for next time:
   `python scripts/parse_packing_list.py file.xlsx --mapping mapping.json --save-mapping auto`
   -> writes `~/.burlington-asn/mappings/<fingerprint>.json`. The fingerprint = normalized header texts of the header row joined by `|`
   (printed as `fingerprint_raw`, hashed as `fingerprint`). The same layout in a future file is then auto-loaded.
   (Use `--save-mapping <path>` for a custom path, `--no-saved-mapping` to ignore saved ones.)

## Quirks the parser already handles
- Numbers stored as strings: `'85'`, `'510 PCS'`, `'1,020     PCS'`, `'2,040. KGS'`, `'1020.00'`.
- Merged header cells (e.g. Packages merged over C:D with the unit text `CTN` in D) - the value is read from the first column of the merge.
- Two header rows (Chinese above English): the best-scoring row wins, missing fields are filled from the adjacent row.
- A row without a PO but with carton + quantity numbers is the totals row: not a line, used for `totals_check`. Blank rows and footers are skipped.
- 7-digit master PO without a Line column: suffix 01, 02 ... by order of appearance of that master PO (flagged `LINE_SUFFIX_ASSIGNED`;
  verify on the EDI inbox that `<master>01` exists). 9-digit values are used as-is.

## Things to stop and ask about
- `blocking` not empty: non-integer units per carton (Quantity / Packages), missing cartons/quantity/weight, duplicate document ids,
  totals row not matching the sum of the lines.
- Multiple sheets with data: pass `--sheet NAME` after asking which.
- Weight columns that look like per-carton values rather than totals (gross weight x cartons would be needed): confirm with the user,
  since the rule is "total G.W. of the PO row".
