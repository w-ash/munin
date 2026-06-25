---
name: google-sheets
description: Read and update Google Sheets from the vault toolchain via `scripts/vault-tool sheets`. Use when the user wants to read, update, append to, or sync data with a Google Sheet or spreadsheet, or pastes a docs.google.com/spreadsheets link. Writes go through a service account, so the sheet must be shared with it first.
user_invocable: true
---

# Google Sheets

Read and write Google Sheets over the Sheets REST API through the `sheets` module
of the vault toolchain. Every command prints a JSON envelope and runs read-only
unless `--write` is passed.

## Access (do this first)

The tool authenticates as a service account, not as Ash. A sheet is reachable only
once it has been shared with that account; otherwise every call returns 403. Share
the sheet (or its parent folder) with this address — **Editor** to write, **Viewer**
to read only:

```
vault-sheets@vault-492101.iam.gserviceaccount.com
```

A call that exits with code 4 (permission) means the sheet isn't shared yet. Ask
Ash to share it with that address.

## Commands

`--spreadsheet` takes a bare ID or a full Sheets URL.

```bash
# Read an A1 range
scripts/vault-tool sheets read-range --spreadsheet <id|url> --range "Sheet1!A1:C20"

# Read a sheet as positioned {row, cells} records (row = 1-based sheet row)
scripts/vault-tool sheets read-table --spreadsheet <id> --sheet "Budget"

# Read several ranges in one request
scripts/vault-tool sheets batch-get --spreadsheet <id> --ranges '["Budget!A1:B5","Notes!A1"]'

# List the sheets (tabs) in a spreadsheet: title, sheetId, index, dimensions
scripts/vault-tool sheets list-sheets --spreadsheet <id>

# Append rows (2-D JSON array)
scripts/vault-tool sheets append --spreadsheet <id> --sheet "Budget" --values '[["Aug","0"]]' --write

# Overwrite a specific range
scripts/vault-tool sheets set-range --spreadsheet <id> --range "Budget!B2" --values '[["1240"]]' --write

# Update the row whose key column matches a value (no fragile row numbers)
scripts/vault-tool sheets update-key --spreadsheet <id> --sheet "Budget" --key-col "Month" --key "June" --set '{"Spent":"1240"}' --write

# Write several ranges atomically
scripts/vault-tool sheets batch --spreadsheet <id> --ops '[{"range":"Budget!B2","values":[["1"]]},{"range":"Budget!B3","values":[["2"]]}]' --write

# Clear the values in a range (formatting/formulas elsewhere untouched)
scripts/vault-tool sheets clear --spreadsheet <id> --range "Budget!B2:B9" --write

# Clear several ranges atomically
scripts/vault-tool sheets batch-clear --spreadsheet <id> --ranges '["Budget!B2:B9","Notes!A1:A50"]' --write

# Create a sheet if it doesn't exist yet (idempotent; no --write needed)
scripts/vault-tool sheets add-sheet --spreadsheet <id> --title "Research Log"
```

`--value-input` defaults to `USER_ENTERED` (inputs parse like the UI: `1240` becomes
a number, `=A1+1` a formula). Pass `--value-input RAW` to store text verbatim.

## Reading formulas and raw numbers

`read-range`, `read-table`, and `batch-get` take `--value-render`:

- `FORMATTED_VALUE` (default) — the display string, e.g. `"$1,240"`.
- `UNFORMATTED_VALUE` — the underlying value, e.g. `1240` (no currency symbol or comma).
- `FORMULA` — the formula text for formula cells, e.g. `=B2*1.1`.

```bash
scripts/vault-tool sheets read-range --spreadsheet <id> --range "Budget!B2" --value-render FORMULA
```

`read-table` and `update-key` still match keys as strings (an unformatted `1240`
reads as `"1240"`); the render option only changes which underlying value is read.

## Sheet (tab) management

Address a sheet by its current name; the tool resolves the name to its `sheetId`
via `list-sheets`, so a wrong name fails fast (exit 2) instead of touching the wrong
tab. All three default to a dry-run and need `--write`.

```bash
scripts/vault-tool sheets rename-sheet --spreadsheet <id> --sheet "Sheet1" --to "Budget" --write
scripts/vault-tool sheets duplicate-sheet --spreadsheet <id> --sheet "Budget" --to "Budget 2027" --write
scripts/vault-tool sheets delete-sheet --spreadsheet <id> --sheet "Scratch" --write
```

`duplicate-sheet --to` is optional; without it the copy is named `Copy of <sheet>`.

## Creating a spreadsheet

```bash
scripts/vault-tool sheets create --title "New Budget" --write
```

Returns the new `spreadsheetId` and `spreadsheetUrl`. **Caveat:** the new spreadsheet
is owned by the service account and lives in *its* Drive, so the returned URL won't
open for Ash until the sheet is shared with his Google account. The toolchain can't
do that sharing itself (it has no Drive-API access), so `create` is mainly useful for
machine-to-machine sheets the service account keeps reading and writing. To get a
human-editable sheet, create it in the Google Sheets UI and share it with the service
account instead.

There is no command to *list which spreadsheets exist* — the Sheets API has no such
method (it needs the Drive API). `list-sheets` lists the tabs within one known
spreadsheet, not spreadsheets across a Drive.

## Find and replace

Replace a value across one sheet (`--sheet`) or the whole spreadsheet (omit `--sheet`):

```bash
scripts/vault-tool sheets find-replace --spreadsheet <id> --sheet "Budget" --find "Q1" --replace "Quarter 1" --write
```

Flags: `--match-case`, `--match-entire-cell` (only when the whole cell equals `--find`),
`--regex` (treat `--find` as a regular expression), `--include-formulas` (also rewrite
formula text). `--write` returns `occurrencesChanged`. The Sheets API has **no preview
mode** for find-replace, so the dry-run can only echo the intent under `wouldReplace`, not
a match count — run with `--write` to apply. (Scoping to an A1 `--range` isn't supported
yet; the API wants a grid range, not A1.)

## Write safely

The mutating commands (`append`, `set-range`, `update-key`, `batch`, `clear`,
`batch-clear`, `rename-sheet`, `delete-sheet`, `duplicate-sheet`, `create`,
`find-replace`) default to a dry-run: they print what they *would* do (under
`wouldWrite` / `wouldAppend` / `updates` / `operations` / `wouldClear` / `wouldDelete` /
`wouldCreate` / `wouldReplace`, or the resolved `sheetId` + `from`/`to` for sheet
management) and change nothing. Run the
command once without `--write`, show Ash the preview, then re-run the same command with
`--write` added. Writes hit a live, shared sheet, so confirm before applying.

`delete-sheet` is the one destructive command (a removed tab can't be recovered through
this tool); its dry-run names the sheet under `wouldDelete` — read it back before adding
`--write`.

`update-key` writes only the cells named in `--set` (one cell per column), so formulas
and formatting elsewhere in the matched row are left untouched. Its dry-run reads the
sheet to resolve the target row, so the preview already shows the row number and the
exact column→value changes.

## Headers below row 1 or spanning rows

`read-table` and `update-key` assume the header is row 1. When it isn't:

- `--header-row N` — the 1-based row where the header starts (e.g. a sheet with notes
  above the table).
- `--header-rows N` — how many rows the header spans. Stacked rows are forward-filled
  (a merged group label spreads across its columns) and joined with a space, so a
  "2026" label over "Jan" becomes the column key `2026 Jan`.

```bash
# Header on row 10, data below it
scripts/vault-tool sheets read-table --spreadsheet <id> --sheet "Qualifying Models" --header-row 10

# Two-row stacked header; address columns by the joined key
scripts/vault-tool sheets update-key --spreadsheet <id> --sheet "Plan" --header-row 1 --header-rows 2 --key-col "Month" --key "Rent" --set '{"2026 Feb":"100"}'
```

## Filling many rows (read → enrich → write back)

To enrich rows (e.g. fill blank cells from research): `read-table` once, keep the
records whose target cell is empty, then write the new values in one `batch`, using
each record's `row` to build the cell ref (column H → `'Sheet'!H{row}`). Prefer this
over calling `update-key` per row — it reads once, writes atomically, and only fills
the cells you set. Re-running is safe because you only touch still-empty cells.

Build the `row`-based cell refs from a **fresh** `read-table` taken immediately before the
write — see the next section for why row numbers go stale.

## Robust writes on shared, human-edited sheets

Collaborators reorder rows, insert columns, and rename things between sessions, so anything
keyed to a fixed position drifts. Defend every write:

- **Match by key, not a remembered row number.** Re-read with `read-table` right before
  writing and target each value by a stable key (`update-key`, or match on the entity's
  natural columns yourself). After writing, re-read and confirm each value landed on the row
  you intended. A row number from an earlier read can point at a different model after a sort.
- **Address columns by header name.** Someone inserting a column (e.g. a new "Details" column
  shifts MSRP from H to I) breaks letter-based refs. `read-table` keys by header, so it
  survives the shift; re-check the literal column letter (read the header row) before any
  letter-based `set-range`/`batch`.
- **Don't `append` to a tab whose column A is blank.** `append` mis-detects the table as
  starting at the first non-empty column, writes the row shifted one column right, and may
  insert mid-sheet. Use `set-range`/`batch` with explicit ranges (`'Sheet'!A{row}:J{row}`).
- **For durable cross-tab links, give rows a frozen ID column.** A value-based ID moves with
  its row on any sort and survives renames, so joins between tabs hold. Use a readable slug —
  `lower("<col1> <col2>")` with each run of non-`[a-z0-9]` replaced by `-`, then trimmed —
  **assigned once and never recomputed** (a later rename keeps the original ID). Join other
  tabs on that ID, and assign IDs to any blank-ID rows before a pass. Prefer this over Google
  Developer Metadata, which is documented to follow rows on *insertion* but is silent on
  *sorting*, is invisible to users, and can't be read by `XLOOKUP`.
- **Friendly links:** write `=HYPERLINK("https://…","Product page")` via `batch` (default
  `USER_ENTERED`); the cell shows the label. Confirm with `--value-render FORMULA`.

## Output and exit codes

Each command prints `{ok, cmd, spreadsheetId, result}`. On failure it prints
`{ok: false, ..., error}` and exits non-zero:

- `2` — bad input (malformed JSON, key column or row not found)
- `3` — auth (the service-account key is missing or invalid)
- `4` — permission (the sheet isn't shared with the service account)
- `5` — other API error

When the failure carries a Google error body, the envelope also includes the parsed
`status` (e.g. `PERMISSION_DENIED`, `RESOURCE_EXHAUSTED`) and `code`, and the `error`
string is `"<STATUS>: <message>"` rather than a raw HTTP error — so a 403 reads as
`PERMISSION_DENIED` (share the sheet) and a quota hit as `RESOURCE_EXHAUSTED` (the tool
already retries 429/5xx with backoff, honoring a `Retry-After` header when present).

Credential storage and setup: `scripts/.env` (`GOOGLE_SHEETS_SA_JSON`) and
`~/.config/gcp/README.md`.
