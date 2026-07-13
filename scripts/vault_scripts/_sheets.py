"""REST wrappers for the Google Sheets API.

Auth and the shared transport live in :mod:`vault_scripts._google` (the token
mint, token cache, and the authenticated REST helper). This module binds that
helper to the Sheets scope and the invocation's auth mode (oauth user by default;
service account under ``--auth service``) and exposes one function per operation.

Under ``--auth service``, share each target spreadsheet with the service account's
``client_email`` (Editor for writes, Viewer for read-only), or calls come back 403.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from pydantic import BaseModel

from vault_scripts._google import authed_request, current_auth
from vault_scripts._types import (
    AppendValuesResponse,
    BatchClearValuesResponse,
    BatchGetValuesResponse,
    BatchUpdateSpreadsheetResponse,
    BatchUpdateValuesResponse,
    ClearValuesResponse,
    CreateSpreadsheetResponse,
    SheetProperties,
    SpreadsheetMeta,
    UpdateValuesResponse,
    ValueRange,
)

SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def _sheets_request[M: BaseModel](
    method: str,
    url: str,
    *,
    response_model: type[M],
    params: dict[str, str] | None = None,
    json: object | None = None,
    idempotent: bool = True,
) -> M:
    """Issue an authenticated Sheets REST call, validated against ``response_model``.

    Binds the shared :func:`vault_scripts._google.authed_request` to the Sheets
    scope and the invocation's auth mode (:func:`current_auth`; oauth user by
    default, service account under ``--auth service``); the retry policy, Bearer
    header, and JSON validation all live in the shared transport. Pass
    ``idempotent=False`` for row appends and resource creates so a retried
    transport error can't duplicate them.
    """
    return authed_request(
        method,
        url,
        response_model=response_model,
        scopes=(SHEETS_SCOPE,),
        auth=current_auth(),
        params=params,
        json=json,
        idempotent=idempotent,
    )


def _values_url(spreadsheet_id: str, a1_range: str, suffix: str = "") -> str:
    """Build a ``spreadsheets.values`` URL. The A1 range sits in the path and
    must be percent-encoded; it contains ``!`` and ``:``."""
    return f"{SHEETS_BASE}/{spreadsheet_id}/values/{quote(a1_range, safe='')}{suffix}"


def values_get(
    spreadsheet_id: str, a1_range: str, value_render: str | None = None
) -> ValueRange:
    """Read a range (``spreadsheets.values.get``). ``value_render`` maps to
    ``valueRenderOption``; None leaves the API default (FORMATTED_VALUE)."""
    params = {"valueRenderOption": value_render} if value_render else None
    return _sheets_request(
        "GET",
        _values_url(spreadsheet_id, a1_range),
        params=params,
        response_model=ValueRange,
    )


def values_batch_get(
    spreadsheet_id: str, ranges: list[str], value_render: str | None = None
) -> BatchGetValuesResponse:
    """Read several ranges in one call (``spreadsheets.values.batchGet``). The
    repeated ``ranges`` query params are built into the URL directly."""
    query: list[tuple[str, str]] = [("ranges", r) for r in ranges]
    if value_render:
        query.append(("valueRenderOption", value_render))
    url = f"{SHEETS_BASE}/{spreadsheet_id}/values:batchGet?{urlencode(query)}"
    return _sheets_request("GET", url, response_model=BatchGetValuesResponse)


def values_update(
    spreadsheet_id: str,
    a1_range: str,
    values: list[list[str]],
    value_input: str,
) -> UpdateValuesResponse:
    """Overwrite a range (``spreadsheets.values.update``)."""
    return _sheets_request(
        "PUT",
        _values_url(spreadsheet_id, a1_range),
        params={"valueInputOption": value_input},
        json={"range": a1_range, "majorDimension": "ROWS", "values": values},
        response_model=UpdateValuesResponse,
    )


def values_append(
    spreadsheet_id: str,
    a1_range: str,
    values: list[list[str]],
    value_input: str,
) -> AppendValuesResponse:
    """Append rows after a table (``spreadsheets.values.append``, INSERT_ROWS)."""
    return _sheets_request(
        "POST",
        _values_url(spreadsheet_id, a1_range, ":append"),
        params={
            "valueInputOption": value_input,
            "insertDataOption": "INSERT_ROWS",
        },
        json={"range": a1_range, "majorDimension": "ROWS", "values": values},
        response_model=AppendValuesResponse,
        idempotent=False,
    )


def values_batch_update(
    spreadsheet_id: str,
    data: list[dict[str, object]],
    value_input: str,
) -> BatchUpdateValuesResponse:
    """Write several ranges atomically (``spreadsheets.values.batchUpdate``)."""
    return _sheets_request(
        "POST",
        f"{SHEETS_BASE}/{spreadsheet_id}/values:batchUpdate",
        json={"valueInputOption": value_input, "data": data},
        response_model=BatchUpdateValuesResponse,
    )


def values_clear(spreadsheet_id: str, a1_range: str) -> ClearValuesResponse:
    """Clear a range's values (``spreadsheets.values.clear``); formatting and
    formulas in unaffected cells are untouched. POSTs an empty body."""
    return _sheets_request(
        "POST",
        _values_url(spreadsheet_id, a1_range, ":clear"),
        json={},
        response_model=ClearValuesResponse,
    )


def values_batch_clear(
    spreadsheet_id: str, ranges: list[str]
) -> BatchClearValuesResponse:
    """Clear several ranges atomically (``spreadsheets.values.batchClear``)."""
    return _sheets_request(
        "POST",
        f"{SHEETS_BASE}/{spreadsheet_id}/values:batchClear",
        json={"ranges": ranges},
        response_model=BatchClearValuesResponse,
    )


def list_sheet_titles(spreadsheet_id: str) -> list[str]:
    """Existing sheet titles. Used to make sheet creation idempotent."""
    meta = _sheets_request(
        "GET",
        f"{SHEETS_BASE}/{spreadsheet_id}",
        params={"fields": "sheets.properties.title"},
        response_model=SpreadsheetMeta,
    )
    return [s.properties.title for s in meta.sheets if s.properties]


# Field mask for a full sheet listing: every property the CLI surfaces, and no
# cell data. The richer sibling of list_sheet_titles; also resolves a title to a
# sheetId for the rename/delete/duplicate commands.
_SHEET_PROPS_MASK = (
    "sheets.properties("
    "sheetId,title,index,sheetType,"
    "gridProperties(rowCount,columnCount),hidden)"
)


def list_sheets(spreadsheet_id: str) -> list[SheetProperties]:
    """All sheets' properties (``spreadsheets.get`` with a properties field mask)."""
    meta = _sheets_request(
        "GET",
        f"{SHEETS_BASE}/{spreadsheet_id}",
        params={"fields": _SHEET_PROPS_MASK},
        response_model=SpreadsheetMeta,
    )
    return [s.properties for s in meta.sheets if s.properties]


def add_sheet(spreadsheet_id: str, title: str) -> bool:
    """Create a sheet if absent (``spreadsheets.batchUpdate`` AddSheet). Returns
    True if created, False if a sheet with that title already existed, so
    re-running a research pass is safe."""
    if title in list_sheet_titles(spreadsheet_id):
        return False
    body: dict[str, object] = {
        "requests": [{"addSheet": {"properties": {"title": title}}}]
    }
    _ = _sheets_request(
        "POST",
        f"{SHEETS_BASE}/{spreadsheet_id}:batchUpdate",
        json=body,
        response_model=BatchUpdateSpreadsheetResponse,
        idempotent=False,
    )
    return True


def batch_update(
    spreadsheet_id: str,
    requests: list[dict[str, object]],
    *,
    idempotent: bool = True,
) -> BatchUpdateSpreadsheetResponse:
    """Issue a multi-request ``spreadsheets.batchUpdate`` in one atomic call, e.g.
    grouping resize + freeze + number-format requests for a mirror push.
    ``idempotent=False`` for requests that create new objects (e.g. DuplicateSheet)."""
    return _sheets_request(
        "POST",
        f"{SHEETS_BASE}/{spreadsheet_id}:batchUpdate",
        json={"requests": requests},
        response_model=BatchUpdateSpreadsheetResponse,
        idempotent=idempotent,
    )


def _batch_update(
    spreadsheet_id: str,
    request: dict[str, object],
    *,
    idempotent: bool = True,
) -> BatchUpdateSpreadsheetResponse:
    """Issue a single-request ``spreadsheets.batchUpdate`` (see :func:`batch_update`).
    ``idempotent=False`` for requests that create new objects (e.g. DuplicateSheet)."""
    return batch_update(spreadsheet_id, [request], idempotent=idempotent)


def rename_sheet(
    spreadsheet_id: str, sheet_id: int, new_title: str
) -> BatchUpdateSpreadsheetResponse:
    """Rename a sheet (``UpdateSheetProperties``). The ``fields`` mask limits the
    update to the title, leaving every other sheet property untouched."""
    return _batch_update(
        spreadsheet_id,
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "title": new_title},
                "fields": "title",
            }
        },
    )


def delete_sheet(spreadsheet_id: str, sheet_id: int) -> BatchUpdateSpreadsheetResponse:
    """Delete a sheet (``DeleteSheet``)."""
    return _batch_update(spreadsheet_id, {"deleteSheet": {"sheetId": sheet_id}})


def duplicate_sheet(
    spreadsheet_id: str, sheet_id: int, new_title: str | None = None
) -> BatchUpdateSpreadsheetResponse:
    """Duplicate a sheet (``DuplicateSheet``). Without ``new_title`` the API names
    the copy 'Copy of <source>'; the copy is inserted after the last sheet."""
    dup: dict[str, object] = {"sourceSheetId": sheet_id}
    if new_title:
        dup["newSheetName"] = new_title
    return _batch_update(spreadsheet_id, {"duplicateSheet": dup}, idempotent=False)


def find_replace(
    spreadsheet_id: str,
    *,
    find: str,
    replacement: str,
    sheet_id: int | None = None,
    match_case: bool = False,
    match_entire_cell: bool = False,
    regex: bool = False,
    include_formulas: bool = False,
) -> BatchUpdateSpreadsheetResponse:
    """Find and replace across one sheet (``sheet_id``) or every sheet (when None),
    via ``FindReplaceRequest``. ``regex`` enables searchByRegex; ``include_formulas``
    also rewrites formula text. There is no preview mode; the change applies on call."""
    req: dict[str, object] = {"find": find, "replacement": replacement}
    if match_case:
        req["matchCase"] = True
    if match_entire_cell:
        req["matchEntireCell"] = True
    if regex:
        req["searchByRegex"] = True
    if include_formulas:
        req["includeFormulas"] = True
    if sheet_id is not None:
        req["sheetId"] = sheet_id
    else:
        req["allSheets"] = True
    return _batch_update(spreadsheet_id, {"findReplace": req})


def create_spreadsheet(title: str) -> CreateSpreadsheetResponse:
    """Create a new spreadsheet (``spreadsheets.create``). Under oauth-user auth
    (the default) it is owned by the user and opens directly; under ``--auth service``
    it is owned by the service account and must be shared before it can be opened."""
    return _sheets_request(
        "POST",
        SHEETS_BASE,
        json={"properties": {"title": title}},
        response_model=CreateSpreadsheetResponse,
        idempotent=False,
    )
