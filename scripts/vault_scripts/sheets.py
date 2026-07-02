"""Read and write Google Sheets directly over the Sheets REST API.

Reads run as-is; mutating commands default to a dry-run and need ``--write``
to apply (same convention as ``geocode``). Every command prints a JSON
envelope ``{ok, cmd, spreadsheetId, result}`` to stdout; errors print
``{ok: false, ..., error}`` and exit with a code (2 validation, 3 auth,
4 permission, 5 API).

Auth runs through the shared seam in ``_google``. ``--auth oauth`` (the default)
acts as the user: reads, in-place edits, and owned-file creation, after a one-time
``sheets auth-login`` (shared with the ``docs`` login). ``--auth service`` uses the
service account; share each target sheet with its client_email or calls 403.

Usage:
    scripts/vault-tool sheets read-range  --spreadsheet <id|url> --range "Sheet1!A1:C5"
    scripts/vault-tool sheets read-table  --spreadsheet <id> --sheet "Budget"
    scripts/vault-tool sheets append      --spreadsheet <id> --sheet "Budget" --values '[["x","y"]]'
    scripts/vault-tool sheets append      --spreadsheet <id> --sheet "Budget" --values '[["x","y"]]' --write
    scripts/vault-tool sheets set-range   --spreadsheet <id> --range "Sheet1!M2" --values '[["hi"]]' --write
    scripts/vault-tool sheets update-key  --spreadsheet <id> --sheet "Budget" --key-col "Month" --key "June" --set '{"Spent":"1240"}'
    scripts/vault-tool sheets update-key  --spreadsheet <id> --sheet "Budget" --key-col "Month" --key "June" --set '{"Spent":"1240"}' --write
    scripts/vault-tool sheets batch       --spreadsheet <id> --ops '[{"range":"Sheet1!A10","values":[["a"]]}]' --write
    scripts/vault-tool sheets add-sheet   --spreadsheet <id> --title "Research Log"
    scripts/vault-tool sheets list-sheets --spreadsheet <id>
    scripts/vault-tool sheets batch-get   --spreadsheet <id> --ranges '["S!A1:B2","S!D1:D5"]'
    scripts/vault-tool sheets read-range  --spreadsheet <id> --range "Budget!B2" --value-render FORMULA
    scripts/vault-tool sheets clear       --spreadsheet <id> --range "Budget!B2:B9" --write
    scripts/vault-tool sheets rename-sheet --spreadsheet <id> --sheet "Sheet1" --to "Budget" --write
    scripts/vault-tool sheets duplicate-sheet --spreadsheet <id> --sheet "Budget" --to "Budget 2027" --write
    scripts/vault-tool sheets delete-sheet --spreadsheet <id> --sheet "Scratch" --write
    scripts/vault-tool sheets create      --title "New Budget" --write

The spreadsheet argument accepts a bare ID or a full Sheets URL. ``--value-input``
(USER_ENTERED, default, or RAW) controls whether inputs are parsed like the UI
(so "=1+2" becomes a formula and "1240" a number) or inserted verbatim. On reads,
``--value-render`` (FORMATTED_VALUE default, UNFORMATTED_VALUE, FORMULA) controls
whether cells come back as display strings, raw numbers, or formulas.

read-table and update-key default to a header on row 1. For a sheet whose header
sits lower or stacks across rows, pass --header-row N (where it starts) and
--header-rows N (how many rows it spans); stacked keys join with a space.

Mutating commands (append, set-range, update-key, batch, clear, batch-clear,
rename-sheet, delete-sheet, duplicate-sheet, create) default to a dry-run and need
--write to apply. ``create`` under the default oauth auth makes a spreadsheet the
user owns and can open directly; under ``--auth service`` it must be shared first.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from pydantic import ValidationError

from vault_scripts import _cli, _sheets
from vault_scripts._cli import (
    CliError,
    parse_drive_id as parse_spreadsheet_id,
    print_json as _print,
    require_flag as _require,
)
from vault_scripts._google import AuthMode, current_auth
from vault_scripts._types import (
    AppendUpdate,
    BatchOps,
    BatchUpdateSpreadsheetResponse,
    CellGrid,
    CellObject,
    RangeList,
    SheetCell,
    SheetProperties,
    TableRow,
)
from vault_scripts._utils import parse_typed_args

# The id key this CLI stamps into every JSON envelope.
_ID_KEY = "spreadsheetId"


# --- Pure helpers (no network; unit-tested) ---


def _quote_sheet(sheet: str) -> str:
    """Quote a sheet name for A1 notation. Always quoting is safe and avoids
    misparsing names that look like cell references ('A1') or are all digits
    ('2026'); embedded single quotes double, per A1 syntax."""
    return "'" + sheet.replace("'", "''") + "'"


def build_range(sheet: str | None, a1: str | None) -> str:
    """Compose an A1 range. ``sheet`` only -> the whole sheet; ``sheet`` + ``a1``
    -> ``'Sheet'!A1:Z9``; ``a1`` only -> passed through (already qualified)."""
    if sheet is not None and a1 is not None:
        return f"{_quote_sheet(sheet)}!{a1}"
    if sheet is not None:
        return _quote_sheet(sheet)
    if a1 is not None:
        return a1
    raise CliError("provide --sheet or --range")


def _ffill(row: list[str]) -> list[str]:
    """Forward-fill empty cells with the previous non-empty value (left to
    right). A horizontally-merged header label reads back as a value in its
    first cell and empty strings after; this spreads it across the columns it
    covers."""
    out: list[str] = []
    last = ""
    for cell in row:
        if cell:
            last = cell
        out.append(last)
    return out


def _check_duplicate_keys(header: list[str]) -> None:
    """Reject duplicate non-empty column keys: an ambiguous lookup would
    silently bind to the first match and drop the other column's data on read."""
    seen: set[str] = set()
    for key in header:
        if key and key in seen:
            raise CliError(
                f"duplicate header column {key!r}; rename it or use read-range"
            )
        seen.add(key)


def combine_header(
    values: list[list[str]], header_row: int, header_rows: int
) -> tuple[list[str], int]:
    """Collapse a (possibly offset, possibly multi-row) header into one key per
    column, and return the 0-based index of the first data row.

    ``header_row`` is the 1-based sheet row where the header starts;
    ``header_rows`` is how many rows it spans. Every header row except the last
    is forward-filled (so merged group labels spread across their columns); the
    last row is taken as-is. A column's key is its non-empty, de-duplicated parts
    joined top to bottom with a space ("Q1" over "Jan" -> "Q1 Jan"). With
    ``(1, 1)`` this is just the first row, a plain single-row header.
    """
    if header_row < 1:
        raise CliError(f"--header-row must be >= 1, got {header_row}")
    if header_rows < 1:
        raise CliError(f"--header-rows must be >= 1, got {header_rows}")
    start = header_row - 1
    if values and start >= len(values):
        raise CliError(
            f"--header-row {header_row} is past the last row ({len(values)})"
        )
    block = values[start : start + header_rows]
    filled = [_ffill(r) if i < len(block) - 1 else r for i, r in enumerate(block)]
    width = max((len(r) for r in filled), default=0)
    header: list[str] = []
    for c in range(width):
        parts: list[str] = []
        for r in filled:
            cell = r[c] if c < len(r) else ""
            if cell and cell not in parts:
                parts.append(cell)
        header.append(" ".join(parts))
    _check_duplicate_keys(header)
    return header, start + header_rows


def rows_to_dicts(
    values: list[list[str]], header_row: int = 1, header_rows: int = 1
) -> list[TableRow]:
    """Header-aware view: each data row becomes a {row, cells} record keyed by
    the (possibly multi-row) header. ``row`` is the 1-based sheet row (so callers
    can write a cell back); unnamed (empty-key) columns are skipped; short rows
    read as empty strings."""
    header, data_start = combine_header(values, header_row, header_rows)
    cols = [(i, key) for i, key in enumerate(header) if key]
    return [
        {
            "row": data_start + offset + 1,
            "cells": {key: row[i] if i < len(row) else "" for i, key in cols},
        }
        for offset, row in enumerate(values[data_start:])
    ]


def header_index(header: list[str], col: str) -> int | None:
    """Zero-based position of ``col`` in the header row, or None."""
    try:
        return header.index(col)
    except ValueError:
        return None


def _match_row(
    values: list[list[str]], data_start: int, col: int, key: str
) -> int | None:
    """1-based sheet row of the first data row whose ``col`` cell equals ``key``."""
    for offset, row in enumerate(values[data_start:]):
        if col < len(row) and row[col] == key:
            return data_start + offset + 1
    return None


def _col_letter(n: int) -> str:
    """1-based column number to its A1 letter (1->A, 26->Z, 27->AA)."""
    if n < 1:
        raise CliError(f"column index must be >= 1, got {n}")
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _col_a1(sheet: str, col: int, row: int) -> str:
    """A1 ref for one cell from a 0-based column index, e.g.
    ('Budget', 5, 10) -> 'Budget'!F10."""
    return f"{_quote_sheet(sheet)}!{_col_letter(col + 1)}{row}"


# The success envelope and dry-run-or-apply tail, with this CLI's id key bound.
envelope = _cli.make_envelope(_ID_KEY)
_emit_write = _cli.make_emit_write(_ID_KEY)


# --- JSON input parsing (CLI strings -> typed, stringified cells) ---


def _cell_str(c: SheetCell) -> str:
    """Render a parsed JSON cell as the string the Sheets API stores. Booleans
    become TRUE/FALSE so USER_ENTERED reads them as sheet booleans."""
    if c is None:
        return ""
    if isinstance(c, bool):
        return "TRUE" if c else "FALSE"
    if isinstance(c, float) and c.is_integer():
        return str(int(c))  # 1240.0 -> "1240", not "1240.0"; also de-sci-notates
    return str(c)


def _stringify_grid(values: list[list[SheetCell]]) -> list[list[str]]:
    """Render an API value grid as strings. FORMATTED_VALUE reads are already
    strings; UNFORMATTED_VALUE / FORMULA reads can return numbers and booleans,
    which the header and key-matching logic needs as strings."""
    return [[_cell_str(c) for c in row] for row in values]


def _parse_grid(raw: str) -> list[list[str]]:
    try:
        grid = CellGrid.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(f"--values must be a JSON array of rows: {e}") from e
    return [[_cell_str(c) for c in row] for row in grid.root]


def _parse_ranges(raw: str) -> list[str]:
    try:
        ranges = RangeList.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(f"--ranges must be a JSON array of A1 strings: {e}") from e
    if not ranges.root:
        raise CliError("--ranges must contain at least one range")
    return ranges.root


def _parse_object(raw: str) -> dict[str, str]:
    try:
        obj = CellObject.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(f"--set must be a JSON object: {e}") from e
    return {k: _cell_str(v) for k, v in obj.root.items()}


def _parse_ops(raw: str) -> list[dict[str, object]]:
    try:
        ops = BatchOps.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(f"--ops must be a JSON array of {{range, values}}: {e}") from e
    return [
        {
            "range": op.range,
            "majorDimension": "ROWS",
            "values": [[_cell_str(c) for c in row] for row in op.values],
        }
        for op in ops.root
    ]


# --- Commands ---


class _Args(argparse.Namespace):
    command: str
    spreadsheet: str
    range: str | None
    sheet: str | None
    values: str | None
    key_col: str | None
    key: str | None
    set: str | None
    ops: str | None
    ranges: str | None
    title: str | None
    to: str | None
    find: str | None
    replace: str | None
    write: bool
    value_input: str
    value_render: str | None
    match_case: bool
    match_entire_cell: bool
    regex: bool
    include_formulas: bool
    header_row: int
    header_rows: int
    auth: AuthMode


def cmd_read_range(args: _Args, sid: str) -> None:
    rng = _require(args.range, "--range")
    vr = _sheets.values_get(sid, rng, args.value_render)
    _print(envelope("read-range", sid, {"range": vr.range, "values": vr.values}))


def cmd_read_table(args: _Args, sid: str) -> None:
    sheet = _require(args.sheet, "--sheet")
    vr = _sheets.values_get(sid, build_range(sheet, None), args.value_render)
    rows = rows_to_dicts(_stringify_grid(vr.values), args.header_row, args.header_rows)
    _print(
        envelope(
            "read-table",
            sid,
            {"sheet": sheet, "rowCount": len(rows), "rows": rows},
        )
    )


def cmd_append(args: _Args, sid: str) -> None:
    sheet = _require(args.sheet, "--sheet")
    values = _parse_grid(_require(args.values, "--values"))
    rng = build_range(sheet, None)

    def apply() -> dict[str, object]:
        u = _sheets.values_append(sid, rng, values, args.value_input).updates
        u = u or AppendUpdate()
        return {"updatedRange": u.updatedRange, "updatedRows": u.updatedRows}

    _emit_write(
        "append",
        sid,
        write=args.write,
        dry={"range": rng, "wouldAppend": values},
        apply=apply,
    )


def cmd_set_range(args: _Args, sid: str) -> None:
    rng = _require(args.range, "--range")
    values = _parse_grid(_require(args.values, "--values"))

    def apply() -> dict[str, object]:
        r = _sheets.values_update(sid, rng, values, args.value_input)
        return {"updatedRange": r.updatedRange, "updatedCells": r.updatedCells}

    _emit_write(
        "set-range",
        sid,
        write=args.write,
        dry={"range": rng, "wouldWrite": values},
        apply=apply,
    )


def cmd_update_key(args: _Args, sid: str) -> None:
    sheet = _require(args.sheet, "--sheet")
    key_col = _require(args.key_col, "--key-col")
    key = _require(args.key, "--key")
    updates = _parse_object(_require(args.set, "--set"))
    values = _stringify_grid(_sheets.values_get(sid, build_range(sheet, None)).values)
    header, data_start = combine_header(values, args.header_row, args.header_rows)
    col = header_index(header, key_col)
    if col is None:
        raise CliError(f"key column {key_col!r} not found in {sheet!r}")
    row_num = _match_row(values, data_start, col, key)
    if row_num is None:
        raise CliError(f"no row where {key_col}={key!r}")
    # Write only the changed cells so formulas/formatting elsewhere in the row
    # (and any concurrent edits to other columns) survive untouched.
    cells: list[dict[str, object]] = []
    for name, value in updates.items():
        idx = header_index(header, name)
        if idx is None:
            raise CliError(f"column {name!r} not in header")
        cells.append({"range": _col_a1(sheet, idx, row_num), "values": [[value]]})

    def apply() -> dict[str, object]:
        r = _sheets.values_batch_update(sid, cells, args.value_input)
        return {"row": row_num, "updatedCells": r.totalUpdatedCells}

    _emit_write(
        "update-key",
        sid,
        write=args.write,
        dry={"row": row_num, "updates": updates},
        apply=apply,
    )


def cmd_batch(args: _Args, sid: str) -> None:
    ops = _parse_ops(_require(args.ops, "--ops"))

    def apply() -> dict[str, object]:
        r = _sheets.values_batch_update(sid, ops, args.value_input)
        return {
            "totalUpdatedCells": r.totalUpdatedCells,
            "totalUpdatedRows": r.totalUpdatedRows,
        }

    _emit_write(
        "batch",
        sid,
        write=args.write,
        dry={"operations": ops},
        apply=apply,
    )


def cmd_add_sheet(args: _Args, sid: str) -> None:
    # Idempotent and additive (creates an empty sheet), so it just runs: no
    # --write gate. Re-running is a no-op once the sheet exists.
    title = _require(args.title, "--title")
    created = _sheets.add_sheet(sid, title)
    _print(envelope("add-sheet", sid, {"title": title, "created": created}))


def cmd_list_sheets(_args: _Args, sid: str) -> None:
    props = _sheets.list_sheets(sid)
    out = [
        {
            "sheetId": p.sheetId,
            "title": p.title,
            "index": p.index,
            "rows": p.gridProperties.rowCount if p.gridProperties else None,
            "columns": p.gridProperties.columnCount if p.gridProperties else None,
            "hidden": p.hidden,
        }
        for p in props
    ]
    _print(envelope("list-sheets", sid, {"sheetCount": len(out), "sheets": out}))


def cmd_batch_get(args: _Args, sid: str) -> None:
    ranges = _parse_ranges(_require(args.ranges, "--ranges"))
    resp = _sheets.values_batch_get(sid, ranges, args.value_render)
    out = [{"range": vr.range, "values": vr.values} for vr in resp.valueRanges]
    _print(envelope("batch-get", sid, {"rangeCount": len(out), "valueRanges": out}))


def cmd_clear(args: _Args, sid: str) -> None:
    rng = _require(args.range, "--range")

    def apply() -> dict[str, object]:
        return {"clearedRange": _sheets.values_clear(sid, rng).clearedRange}

    _emit_write(
        "clear",
        sid,
        write=args.write,
        dry={"range": rng, "wouldClear": rng},
        apply=apply,
    )


def cmd_batch_clear(args: _Args, sid: str) -> None:
    ranges = _parse_ranges(_require(args.ranges, "--ranges"))

    def apply() -> dict[str, object]:
        return {"clearedRanges": _sheets.values_batch_clear(sid, ranges).clearedRanges}

    _emit_write(
        "batch-clear", sid, write=args.write, dry={"wouldClear": ranges}, apply=apply
    )


def _resolve_sheet(props: list[SheetProperties], name: str) -> SheetProperties:
    """Find the sheet whose title equals ``name`` (the sheet-management commands
    address a sheet by name; the API addresses it by sheetId)."""
    for p in props:
        if p.title == name:
            return p
    have = ", ".join(repr(p.title) for p in props) or "none"
    raise CliError(f"no sheet named {name!r} (have: {have})")


def cmd_rename_sheet(args: _Args, sid: str) -> None:
    sheet = _require(args.sheet, "--sheet")
    new_title = _require(args.to, "--to")
    target = _resolve_sheet(_sheets.list_sheets(sid), sheet)

    def apply() -> dict[str, object]:
        _ = _sheets.rename_sheet(sid, target.sheetId, new_title)
        return {"sheetId": target.sheetId, "renamed": sheet, "to": new_title}

    _emit_write(
        "rename-sheet",
        sid,
        write=args.write,
        dry={"sheetId": target.sheetId, "from": sheet, "to": new_title},
        apply=apply,
    )


def cmd_delete_sheet(args: _Args, sid: str) -> None:
    sheet = _require(args.sheet, "--sheet")
    target = _resolve_sheet(_sheets.list_sheets(sid), sheet)

    def apply() -> dict[str, object]:
        _ = _sheets.delete_sheet(sid, target.sheetId)
        return {"sheetId": target.sheetId, "deleted": sheet}

    _emit_write(
        "delete-sheet",
        sid,
        write=args.write,
        dry={"sheetId": target.sheetId, "wouldDelete": sheet},
        apply=apply,
    )


def _dup_result(
    resp: BatchUpdateSpreadsheetResponse, source: str, fallback: str | None
) -> dict[str, object]:
    """Pull the copy's real name/id out of the duplicateSheet reply, falling back
    to the requested name (the API auto-names it 'Copy of <source>' when none
    was given, so report that shape when the reply is unexpectedly empty)."""
    reply = resp.replies[0].duplicateSheet if resp.replies else None
    props = reply.properties if reply else None
    if props is not None:
        return {"source": source, "newSheetId": props.sheetId, "newTitle": props.title}
    return {"source": source, "newTitle": fallback or f"Copy of {source}"}


def cmd_duplicate_sheet(args: _Args, sid: str) -> None:
    sheet = _require(args.sheet, "--sheet")
    target = _resolve_sheet(_sheets.list_sheets(sid), sheet)

    def apply() -> dict[str, object]:
        resp = _sheets.duplicate_sheet(sid, target.sheetId, args.to)
        return _dup_result(resp, sheet, args.to)

    _emit_write(
        "duplicate-sheet",
        sid,
        write=args.write,
        dry={
            "sourceSheetId": target.sheetId,
            "from": sheet,
            "to": args.to or f"Copy of {sheet}",
        },
        apply=apply,
    )


# Surfaced in the create result. Under oauth (the default) the new spreadsheet is
# the user's and opens directly; under --auth service it is the service account's,
# not the user's, until it's explicitly shared (which needs the Drive API).
_CREATE_NOTE_OAUTH = "Owned by your Google account; open the URL directly."
_CREATE_NOTE_SERVICE = (
    "Owned by the service account; share it with your Google account "
    "to open it in a browser."
)


def cmd_create(args: _Args, sid: str) -> None:
    title = _require(args.title, "--title")
    note = _CREATE_NOTE_OAUTH if current_auth() == "oauth" else _CREATE_NOTE_SERVICE

    def apply() -> dict[str, object]:
        r = _sheets.create_spreadsheet(title)
        return {
            "spreadsheetId": r.spreadsheetId,
            "spreadsheetUrl": r.spreadsheetUrl,
            "title": title,
            "note": note,
        }

    _emit_write(
        "create", sid, write=args.write, dry={"wouldCreate": title}, apply=apply
    )


def cmd_auth_login(_args: _Args, _sid: str) -> None:
    _print(envelope("auth-login", "", _cli.auth_login()))


def cmd_find_replace(args: _Args, sid: str) -> None:
    find = _require(args.find, "--find")
    replacement = _require(args.replace, "--replace")
    # Scope to one sheet by name, or every sheet when --sheet is omitted. The
    # preview only needs the name, so the name->sheetId lookup is deferred to the
    # write path; the dry-run stays offline (unlike rename/delete, whose preview
    # shows the resolved sheetId and so must resolve up front).
    scope = args.sheet if args.sheet is not None else "all sheets"

    def apply() -> dict[str, object]:
        sheet_id = (
            _resolve_sheet(_sheets.list_sheets(sid), args.sheet).sheetId
            if args.sheet is not None
            else None
        )
        resp = _sheets.find_replace(
            sid,
            find=find,
            replacement=replacement,
            sheet_id=sheet_id,
            match_case=args.match_case,
            match_entire_cell=args.match_entire_cell,
            regex=args.regex,
            include_formulas=args.include_formulas,
        )
        fr = resp.replies[0].findReplace if resp.replies else None
        return {
            "scope": scope,
            "occurrencesChanged": fr.occurrencesChanged if fr else 0,
            "valuesChanged": fr.valuesChanged if fr else 0,
        }

    _emit_write(
        "find-replace",
        sid,
        write=args.write,
        # find-replace has no preview API, so the dry-run can only echo intent.
        dry={
            "wouldReplace": {"find": find, "replacement": replacement, "scope": scope},
            "note": "dry-run can't preview the match count; run with --write to apply",
        },
        apply=apply,
    )


# --- CLI plumbing ---


# Subcommand dispatch. argparse declares the same names with required=True, so
# an unknown command never reaches the lookup.
_COMMANDS: dict[str, Callable[[_Args, str], None]] = {
    "read-range": cmd_read_range,
    "read-table": cmd_read_table,
    "append": cmd_append,
    "set-range": cmd_set_range,
    "update-key": cmd_update_key,
    "batch": cmd_batch,
    "add-sheet": cmd_add_sheet,
    "list-sheets": cmd_list_sheets,
    "batch-get": cmd_batch_get,
    "clear": cmd_clear,
    "batch-clear": cmd_batch_clear,
    "rename-sheet": cmd_rename_sheet,
    "delete-sheet": cmd_delete_sheet,
    "duplicate-sheet": cmd_duplicate_sheet,
    "create": cmd_create,
    "find-replace": cmd_find_replace,
    "auth-login": cmd_auth_login,
}


def _run(args: _Args, sid: str) -> None:
    _COMMANDS[args.command](args, sid)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and write Google Sheets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --auth applies to every command (oauth user by default; --auth service for
    # the sandboxed service account). Shared with the docs CLI via _cli.
    auth_opts = _cli.auth_parent()

    common = argparse.ArgumentParser(add_help=False)
    _ = common.add_argument(
        "--spreadsheet",
        required=True,
        help="Spreadsheet ID or full Sheets URL",
    )

    write_opts = argparse.ArgumentParser(add_help=False)
    _ = write_opts.add_argument(
        "--write",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    _ = write_opts.add_argument(
        "--value-input",
        choices=["USER_ENTERED", "RAW"],
        default="USER_ENTERED",
        help="Parse inputs like the UI (USER_ENTERED, default) or insert verbatim (RAW)",
    )

    header_opts = argparse.ArgumentParser(add_help=False)
    _ = header_opts.add_argument(
        "--header-row",
        type=int,
        default=1,
        help="1-based sheet row where the header starts (default 1)",
    )
    _ = header_opts.add_argument(
        "--header-rows",
        type=int,
        default=1,
        help="Rows the header spans (default 1; >1 for stacked/merged headers)",
    )

    # Read-side render option. Default None leaves the API default
    # (FORMATTED_VALUE); FORMULA / UNFORMATTED_VALUE expose formulas and raw
    # numbers instead of the display string.
    render_opts = argparse.ArgumentParser(add_help=False)
    _ = render_opts.add_argument(
        "--value-render",
        choices=["FORMATTED_VALUE", "UNFORMATTED_VALUE", "FORMULA"],
        default=None,
        help="How cells render: FORMATTED_VALUE (default), UNFORMATTED_VALUE, FORMULA",
    )

    # The --write gate alone, for mutations that take no value input
    # (clear, sheet management, create). Value-writing commands use write_opts.
    write_flag = argparse.ArgumentParser(add_help=False)
    _ = write_flag.add_argument(
        "--write",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )

    rr = subparsers.add_parser(
        "read-range", parents=[auth_opts, common, render_opts], help="Read an A1 range"
    )
    _ = rr.add_argument("--range", required=True, help="A1 range, e.g. 'Sheet1!A1:C5'")

    rt = subparsers.add_parser(
        "read-table",
        parents=[auth_opts, common, header_opts, render_opts],
        help="Read a sheet as positioned {row, cells} records",
    )
    _ = rt.add_argument("--sheet", required=True, help="Sheet name")

    ap = subparsers.add_parser(
        "append",
        parents=[auth_opts, common, write_opts],
        help="Append rows to a sheet",
    )
    _ = ap.add_argument("--sheet", required=True, help="Sheet name")
    _ = ap.add_argument(
        "--values",
        required=True,
        help='JSON 2-D array of rows, e.g. \'[["a","b"]]\'',
    )

    sr = subparsers.add_parser(
        "set-range",
        parents=[auth_opts, common, write_opts],
        help="Overwrite an A1 range",
    )
    _ = sr.add_argument("--range", required=True, help="A1 range, e.g. 'Sheet1!M2'")
    _ = sr.add_argument("--values", required=True, help="JSON 2-D array of rows")

    uk = subparsers.add_parser(
        "update-key",
        parents=[auth_opts, common, write_opts, header_opts],
        help="Update the row whose key column matches a value",
    )
    _ = uk.add_argument("--sheet", required=True, help="Sheet name")
    _ = uk.add_argument(
        "--key-col", required=True, help="Header name of the key column"
    )
    _ = uk.add_argument("--key", required=True, help="Value to match in the key column")
    _ = uk.add_argument(
        "--set",
        required=True,
        help='JSON object of column -> value, e.g. \'{"Status":"done"}\'',
    )

    ba = subparsers.add_parser(
        "batch",
        parents=[auth_opts, common, write_opts],
        help="Write several ranges atomically",
    )
    _ = ba.add_argument(
        "--ops",
        required=True,
        help='JSON array of {range, values}, e.g. \'[{"range":"S!A1","values":[["a"]]}]\'',
    )

    asheet = subparsers.add_parser(
        "add-sheet",
        parents=[auth_opts, common],
        help="Create a sheet if absent (idempotent)",
    )
    _ = asheet.add_argument("--title", required=True, help="Sheet name to create")

    _ = subparsers.add_parser(
        "list-sheets",
        parents=[auth_opts, common],
        help="List the sheets in a spreadsheet (title, sheetId, dimensions)",
    )

    bg = subparsers.add_parser(
        "batch-get",
        parents=[auth_opts, common, render_opts],
        help="Read several ranges in one call",
    )
    _ = bg.add_argument(
        "--ranges",
        required=True,
        help='JSON array of A1 ranges, e.g. \'["S!A1:B2","S!D1:D5"]\'',
    )

    cl = subparsers.add_parser(
        "clear",
        parents=[auth_opts, common, write_flag],
        help="Clear the values in an A1 range",
    )
    _ = cl.add_argument("--range", required=True, help="A1 range, e.g. 'Sheet1!A1:B10'")

    bc = subparsers.add_parser(
        "batch-clear",
        parents=[auth_opts, common, write_flag],
        help="Clear several ranges atomically",
    )
    _ = bc.add_argument(
        "--ranges", required=True, help="JSON array of A1 ranges to clear"
    )

    rn = subparsers.add_parser(
        "rename-sheet",
        parents=[auth_opts, common, write_flag],
        help="Rename a sheet",
    )
    _ = rn.add_argument("--sheet", required=True, help="Current sheet name")
    _ = rn.add_argument("--to", required=True, help="New sheet name")

    dl = subparsers.add_parser(
        "delete-sheet",
        parents=[auth_opts, common, write_flag],
        help="Delete a sheet",
    )
    _ = dl.add_argument("--sheet", required=True, help="Sheet name to delete")

    dup = subparsers.add_parser(
        "duplicate-sheet",
        parents=[auth_opts, common, write_flag],
        help="Duplicate a sheet",
    )
    _ = dup.add_argument("--sheet", required=True, help="Sheet name to duplicate")
    _ = dup.add_argument("--to", help="Name for the copy (default: 'Copy of <sheet>')")

    cr = subparsers.add_parser(
        "create",
        parents=[auth_opts, write_flag],
        help="Create a new spreadsheet (owned by you under oauth, the default)",
    )
    _ = cr.add_argument("--title", required=True, help="Title for the new spreadsheet")

    fr = subparsers.add_parser(
        "find-replace",
        parents=[auth_opts, common, write_flag],
        help="Find and replace a value across a sheet or the whole spreadsheet",
    )
    _ = fr.add_argument("--find", required=True, help="Text (or regex) to find")
    _ = fr.add_argument("--replace", required=True, help="Replacement text")
    _ = fr.add_argument("--sheet", help="Limit to this sheet (default: all sheets)")
    _ = fr.add_argument(
        "--match-case", action="store_true", help="Case-sensitive match"
    )
    _ = fr.add_argument(
        "--match-entire-cell",
        action="store_true",
        help="Match only when the whole cell equals --find",
    )
    _ = fr.add_argument(
        "--regex", action="store_true", help="Treat --find as a regular expression"
    )
    _ = fr.add_argument(
        "--include-formulas",
        action="store_true",
        help="Also search and replace within formula text",
    )

    _ = subparsers.add_parser(
        "auth-login",
        parents=[auth_opts],
        help="Run the one-time OAuth consent and store the token (shared with docs)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parse_typed_args(parser, _Args)
    # create and auth-login take no --spreadsheet; create's envelope carries the
    # new id in the result, not the top-level spreadsheetId.
    no_spreadsheet = {"create", "auth-login"}
    sid = "" if args.command in no_spreadsheet else parse_spreadsheet_id(args.spreadsheet)
    _cli.run_cli(args.command, _ID_KEY, sid, args.auth, lambda: _run(args, sid))


if __name__ == "__main__":
    main()
