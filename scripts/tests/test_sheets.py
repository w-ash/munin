"""Unit tests for the sheets module: pure helpers, the REST wrapper boundary,
and the dry-run contract. No network — the token mint and HTTP layer are
monkeypatched in ``_google`` (the shared transport). Auth itself is tested in
``test_google``."""

from __future__ import annotations

import pytest

from vault_scripts import _cli, _google, _sheets, sheets
from vault_scripts._types import (
    BatchClearValuesResponse,
    BatchGetValuesResponse,
    BatchUpdateReply,
    BatchUpdateSpreadsheetResponse,
    BatchUpdateValuesResponse,
    ClearValuesResponse,
    CreateSpreadsheetResponse,
    DuplicateSheetReply,
    FindReplaceReply,
    GridProperties,
    SheetEntry,
    SheetProperties,
    SpreadsheetMeta,
    SpreadsheetProperties,
    ValueRange,
)

# --- parse_spreadsheet_id ---


def test_parse_spreadsheet_id_bare():
    assert sheets.parse_spreadsheet_id("1AbC-_dEf") == "1AbC-_dEf"


def test_parse_spreadsheet_id_url_with_gid():
    url = "https://docs.google.com/spreadsheets/d/1AbC-_dEf/edit#gid=0"
    assert sheets.parse_spreadsheet_id(url) == "1AbC-_dEf"


def test_parse_spreadsheet_id_multi_account_url():
    url = "https://docs.google.com/spreadsheets/u/0/d/1AbC-_dEf/edit"
    assert sheets.parse_spreadsheet_id(url) == "1AbC-_dEf"


def test_parse_spreadsheet_id_strips_whitespace():
    assert sheets.parse_spreadsheet_id("  1AbC-_dEf  ") == "1AbC-_dEf"


# --- build_range / _quote_sheet ---


def test_build_range_always_quotes_sheet():
    assert sheets.build_range("Budget", None) == "'Budget'"
    assert sheets.build_range("My Sheet", None) == "'My Sheet'"
    # Cell-like and all-numeric names must be quoted or they misparse.
    assert sheets.build_range("A1", None) == "'A1'"
    assert sheets.build_range("2026", None) == "'2026'"


def test_build_range_escapes_apostrophe():
    assert sheets.build_range("O'Brien", None) == "'O''Brien'"


def test_build_range_sheet_and_a1():
    assert sheets.build_range("Sheet1", "A1:C5") == "'Sheet1'!A1:C5"


def test_build_range_a1_only_passthrough():
    assert sheets.build_range(None, "Sheet1!A1") == "Sheet1!A1"


def test_build_range_requires_one():
    with pytest.raises(sheets.CliError):
        sheets.build_range(None, None)


# --- rows_to_dicts ---


def test_rows_to_dicts_positions_and_pads_ragged_rows():
    values = [["Name", "Status"], ["Den", "done"], ["Sushi"]]
    assert sheets.rows_to_dicts(values) == [
        {"row": 2, "cells": {"Name": "Den", "Status": "done"}},
        {"row": 3, "cells": {"Name": "Sushi", "Status": ""}},
    ]


def test_rows_to_dicts_empty():
    assert sheets.rows_to_dicts([]) == []


# --- _match_row (row resolution; data_start/col come from combine_header) ---

# Header row 1, key column 0, data starting at index 1.
_KEYED = [["Month", "Spent"], ["May", "100"], ["June", "200"]]


def test_match_row_returns_sheet_row():
    assert sheets._match_row(_KEYED, 1, 0, "June") == 3
    assert sheets._match_row(_KEYED, 1, 0, "May") == 2


def test_match_row_no_match():
    assert sheets._match_row(_KEYED, 1, 0, "July") is None


def test_match_row_skips_short_rows():
    # A row shorter than the key column index is skipped, not an IndexError.
    assert sheets._match_row([["Month", "Spent"], ["May"]], 1, 1, "x") is None


# --- _col_letter / _col_a1 ---


@pytest.mark.parametrize(
    ("n", "letter"),
    [
        (1, "A"),
        (26, "Z"),
        (27, "AA"),
        (52, "AZ"),
        (53, "BA"),
        (702, "ZZ"),
        (703, "AAA"),
    ],
)
def test_col_letter(n, letter):
    assert sheets._col_letter(n) == letter


def test_col_letter_rejects_zero():
    with pytest.raises(sheets.CliError):
        sheets._col_letter(0)


def test_col_a1_from_zero_based_index():
    assert sheets._col_a1("Budget", 5, 10) == "'Budget'!F10"
    assert sheets._col_a1("My Sheet", 0, 3) == "'My Sheet'!A3"


# --- envelope ---


def test_envelope_shape():
    env = sheets.envelope("read-table", "sid1", {"rows": []})
    assert env == {
        "ok": True,
        "cmd": "read-table",
        "spreadsheetId": "sid1",
        "result": {"rows": []},
    }


# --- JSON input parsing ---


def test_cell_str_variants():
    assert sheets._cell_str(None) == ""
    assert sheets._cell_str(True) == "TRUE"
    assert sheets._cell_str(False) == "FALSE"
    assert sheets._cell_str(1240) == "1240"
    assert sheets._cell_str("x") == "x"


def test_parse_grid_stringifies_mixed_cells():
    assert sheets._parse_grid('[["a", 1, true]]') == [["a", "1", "TRUE"]]


def test_parse_grid_bad_json_raises():
    with pytest.raises(sheets.CliError):
        sheets._parse_grid("[[unclosed")


def test_parse_grid_not_an_array_raises():
    with pytest.raises(sheets.CliError):
        sheets._parse_grid('{"a": 1}')


def test_parse_object_stringifies_values():
    assert sheets._parse_object('{"a": "b", "c": 2}') == {"a": "b", "c": "2"}


def test_parse_ops_builds_value_ranges():
    ops = sheets._parse_ops('[{"range": "S!A1", "values": [["x", 2]]}]')
    assert ops == [
        {"range": "S!A1", "majorDimension": "ROWS", "values": [["x", "2"]]},
    ]


# --- REST wrapper boundary ---


def test_values_get_parses_response(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "fake-token")
    payload = '{"range": "S!A1:B2", "majorDimension": "ROWS", "values": [["a", "b"]]}'

    def fake_request(method, url, *, response_model, **_):
        assert method == "GET"
        return response_model.model_validate_json(payload)

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    vr = _sheets.values_get("sid", "S!A1:B2")
    assert isinstance(vr, ValueRange)
    assert vr.values == [["a", "b"]]


# --- dry-run contract ---


def _update_key_args(*, write: bool) -> sheets._Args:
    args = sheets._Args()
    args.command = "update-key"
    args.spreadsheet = "sid"
    args.sheet = "Budget"
    args.key_col = "Month"
    args.key = "June"
    args.set = '{"Spent": "1240"}'
    args.value_input = "USER_ENTERED"
    args.write = write
    args.header_row = 1
    args.header_rows = 1
    return args


def _fake_sheet(monkeypatch) -> list[tuple[str, list[dict[str, object]], str]]:
    """Stub values_get with a known table; record every values_batch_update call."""

    def fake_get(_sid, rng):
        return ValueRange(
            range=rng,
            majorDimension="ROWS",
            values=[["Month", "Spent"], ["May", "100"], ["June", "200"]],
        )

    monkeypatch.setattr(_sheets, "values_get", fake_get)
    calls: list[tuple[str, list[dict[str, object]], str]] = []

    def fake_batch(sid, data, value_input):
        calls.append((sid, data, value_input))
        return BatchUpdateValuesResponse(spreadsheetId=sid, totalUpdatedCells=len(data))

    monkeypatch.setattr(_sheets, "values_batch_update", fake_batch)
    return calls


def test_update_key_dry_run_makes_no_write(monkeypatch, capsys):
    calls = _fake_sheet(monkeypatch)
    sheets.cmd_update_key(_update_key_args(write=False), "sid")
    assert calls == []
    assert '"dryRun": true' in capsys.readouterr().out


def test_update_key_write_targets_only_changed_cell(monkeypatch, capsys):
    calls = _fake_sheet(monkeypatch)
    sheets.cmd_update_key(_update_key_args(write=True), "sid")
    assert len(calls) == 1
    _sid, data, _vio = calls[0]
    # Only the Spent cell of June's row (sheet row 3, column B) is written —
    # the rest of the row (and any formulas) is never touched.
    assert data == [{"range": "'Budget'!B3", "values": [["1240"]]}]
    capsys.readouterr()


def test_update_key_unknown_key_raises(monkeypatch):
    _fake_sheet(monkeypatch)
    args = _update_key_args(write=True)
    args.key = "Smarch"
    with pytest.raises(sheets.CliError):
        sheets.cmd_update_key(args, "sid")


# --- combine_header: offset + multi-row headers ---


def test_combine_header_default_is_first_row():
    header, data_start = sheets.combine_header([["A", "B"], ["1", "2"]], 1, 1)
    assert header == ["A", "B"]
    assert data_start == 1


def test_combine_header_offset_single_row():
    values = [["note"], [], ["Manufacturer", "Model"], ["Aima", "Big Sur"]]
    header, data_start = sheets.combine_header(values, 3, 1)
    assert header == ["Manufacturer", "Model"]
    assert data_start == 3


def test_combine_header_two_rows_forward_fills_merges():
    # Row 1 holds merged group labels (value then blanks); row 2 the leaf labels.
    values = [
        ["2026", "", "2027", ""],
        ["Jan", "Feb", "Jan", "Feb"],
        ["10", "20", "30", "40"],
    ]
    header, data_start = sheets.combine_header(values, 1, 2)
    assert header == ["2026 Jan", "2026 Feb", "2027 Jan", "2027 Feb"]
    assert data_start == 2


def test_combine_header_dedups_repeated_parts():
    header, _ = sheets.combine_header([["Qty", "Qty"], ["Qty", "each"]], 1, 2)
    assert header == ["Qty", "Qty each"]


def test_combine_header_rejects_bad_args():
    with pytest.raises(sheets.CliError):
        sheets.combine_header([["A"]], 0, 1)
    with pytest.raises(sheets.CliError):
        sheets.combine_header([["A"]], 1, 0)


def test_rows_to_dicts_with_offset_header():
    values = [["preamble"], ["Name", "Status"], ["Den", "done"], ["Sushi", "todo"]]
    # Header on sheet row 2 -> data rows are sheet rows 3 and 4.
    assert sheets.rows_to_dicts(values, header_row=2, header_rows=1) == [
        {"row": 3, "cells": {"Name": "Den", "Status": "done"}},
        {"row": 4, "cells": {"Name": "Sushi", "Status": "todo"}},
    ]


def test_match_row_with_offset_header():
    values = [["preamble"], ["Month", "Spent"], ["May", "100"], ["June", "200"]]
    header, data_start = sheets.combine_header(values, 2, 1)
    col = sheets.header_index(header, "Month")
    assert col is not None
    # Header on sheet row 2 -> data rows 3-4; "June" is sheet row 4.
    assert sheets._match_row(values, data_start, col, "June") == 4


def test_match_row_with_multirow_header():
    values = [
        ["", "Spend"],  # merged group row
        ["Month", "USD"],  # leaf row
        ["May", "100"],
        ["June", "200"],
    ]
    header, data_start = sheets.combine_header(values, 1, 2)
    col = sheets.header_index(header, "Month")
    assert col is not None
    # Header spans rows 1-2 -> data from row 3; "June" is sheet row 4.
    assert sheets._match_row(values, data_start, col, "June") == 4


# --- update-key on an offset header (command level) ---


def _fake_offset_sheet(monkeypatch) -> list[tuple[str, list[dict[str, object]], str]]:
    def fake_get(_sid, rng):
        return ValueRange(
            range=rng,
            majorDimension="ROWS",
            values=[
                ["Rebate program"],  # row 1 preamble
                ["Manufacturer", "Model", "Class"],  # row 2 header
                ["Aima", "Big Sur", "3"],  # row 3
                ["Always", "Anytime", "3"],  # row 4
            ],
        )

    monkeypatch.setattr(_sheets, "values_get", fake_get)
    calls: list[tuple[str, list[dict[str, object]], str]] = []

    def fake_batch(sid, data, value_input):
        calls.append((sid, data, value_input))
        return BatchUpdateValuesResponse(spreadsheetId=sid, totalUpdatedCells=len(data))

    monkeypatch.setattr(_sheets, "values_batch_update", fake_batch)
    return calls


def _offset_args(*, write: bool) -> sheets._Args:
    args = sheets._Args()
    args.command = "update-key"
    args.spreadsheet = "sid"
    args.sheet = "Models"
    args.key_col = "Model"
    args.key = "Anytime"
    args.set = '{"Class": "1"}'
    args.value_input = "USER_ENTERED"
    args.write = write
    args.header_row = 2
    args.header_rows = 1
    return args


def test_update_key_offset_header_targets_correct_cell(monkeypatch, capsys):
    calls = _fake_offset_sheet(monkeypatch)
    sheets.cmd_update_key(_offset_args(write=True), "sid")
    assert len(calls) == 1
    _sid, data, _vio = calls[0]
    # "Anytime" is sheet row 4; Class is column C. Only C4 is written.
    assert data == [{"range": "'Models'!C4", "values": [["1"]]}]
    capsys.readouterr()


def test_update_key_offset_header_dry_run_no_write(monkeypatch, capsys):
    calls = _fake_offset_sheet(monkeypatch)
    sheets.cmd_update_key(_offset_args(write=False), "sid")
    assert calls == []
    out = capsys.readouterr().out
    assert '"dryRun": true' in out
    assert '"row": 4' in out


# --- review fixes: header validation, unnamed columns, numeric cells ---


def test_combine_header_rejects_duplicate_keys():
    with pytest.raises(sheets.CliError):
        sheets.combine_header([["ID", "ID"], ["1", "2"]], 1, 1)


def test_combine_header_rejects_out_of_range_row():
    with pytest.raises(sheets.CliError):
        sheets.combine_header([["A", "B"], ["1", "2"]], 99, 1)


def test_rows_to_dicts_skips_unnamed_columns():
    # A leading unnamed column (empty header) is dropped, not surfaced under "".
    assert sheets.rows_to_dicts([["", "Name"], ["x", "Den"]]) == [
        {"row": 2, "cells": {"Name": "Den"}},
    ]


def test_cell_str_integral_float_drops_decimal():
    assert sheets._cell_str(1240.0) == "1240"
    assert sheets._cell_str(1.5) == "1.5"


# --- add_sheet (idempotent sheet creation) ---


def test_list_sheet_titles_extracts_present_titles(monkeypatch):
    meta = SpreadsheetMeta(
        sheets=[SheetEntry(properties=SheetProperties(title="Budget")), SheetEntry()]
    )
    monkeypatch.setattr(_sheets, "_sheets_request", lambda *_a, **_k: meta)
    assert _sheets.list_sheet_titles("sid") == ["Budget"]


def test_add_sheet_skips_existing(monkeypatch):
    monkeypatch.setattr(_sheets, "list_sheet_titles", lambda _sid: ["Research Log"])
    calls: list[str] = []
    monkeypatch.setattr(_sheets, "_sheets_request", lambda *_a, **_k: calls.append("x"))
    assert _sheets.add_sheet("sid", "Research Log") is False
    assert calls == []  # no batchUpdate when the sheet already exists


def test_add_sheet_creates_when_absent(monkeypatch):
    monkeypatch.setattr(_sheets, "list_sheet_titles", lambda _sid: ["Other"])
    seen: dict[str, str] = {}

    def fake_request(method, url, *, response_model, **_):
        seen["method"], seen["url"] = method, url
        return response_model()

    monkeypatch.setattr(_sheets, "_sheets_request", fake_request)
    assert _sheets.add_sheet("sid", "Research Log") is True
    assert seen["method"] == "POST"
    assert seen["url"].endswith(":batchUpdate")


# --- new helpers: _stringify_grid / _parse_ranges / _resolve_sheet / _dup_result ---


def test_stringify_grid_renders_mixed_cells():
    # FORMATTED reads are already strings; UNFORMATTED/FORMULA can yield numbers,
    # booleans, and (rarely) nulls — all must come back as strings.
    assert sheets._stringify_grid([["a", 1, 2.0, True, None]]) == [
        ["a", "1", "2", "TRUE", ""],
    ]


def test_parse_ranges_valid():
    assert sheets._parse_ranges('["S!A1:B2", "S!D1"]') == ["S!A1:B2", "S!D1"]


def test_parse_ranges_empty_array_raises():
    with pytest.raises(sheets.CliError):
        sheets._parse_ranges("[]")


def test_parse_ranges_not_an_array_raises():
    with pytest.raises(sheets.CliError):
        sheets._parse_ranges('"S!A1"')


def test_resolve_sheet_finds_by_title():
    props = [
        SheetProperties(sheetId=5, title="Sheet1"),
        SheetProperties(sheetId=6, title="Budget"),
    ]
    assert sheets._resolve_sheet(props, "Budget").sheetId == 6


def test_resolve_sheet_missing_raises():
    with pytest.raises(sheets.CliError):
        sheets._resolve_sheet([SheetProperties(sheetId=1, title="Budget")], "Ghost")


def test_dup_result_reads_reply_props():
    resp = BatchUpdateSpreadsheetResponse(
        replies=[
            BatchUpdateReply(
                duplicateSheet=DuplicateSheetReply(
                    properties=SheetProperties(sheetId=99, title="Copy of Budget")
                )
            )
        ]
    )
    assert sheets._dup_result(resp, "Budget", None) == {
        "source": "Budget",
        "newSheetId": 99,
        "newTitle": "Copy of Budget",
    }


def test_dup_result_falls_back_without_reply():
    resp = BatchUpdateSpreadsheetResponse()
    assert sheets._dup_result(resp, "Budget", None) == {
        "source": "Budget",
        "newTitle": "Copy of Budget",
    }
    assert sheets._dup_result(resp, "Budget", "2027")["newTitle"] == "2027"


# --- ValueRange broadening: mixed cell types from FORMULA/UNFORMATTED reads ---


def test_value_range_accepts_mixed_cells():
    vr = ValueRange.model_validate_json(
        '{"range":"S!A1:C1","values":[[1240, "=A1+1", true]]}'
    )
    assert vr.values == [[1240, "=A1+1", True]]


# --- REST boundary: new value + metadata wrappers ---


def test_values_get_passes_value_render(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, params=None, **_):
        seen["params"] = params
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.values_get("sid", "S!A1", "FORMULA")
    assert seen["params"] == {"valueRenderOption": "FORMULA"}


def test_values_get_omits_render_by_default(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, params=None, **_):
        seen["params"] = params
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.values_get("sid", "S!A1")
    assert seen["params"] is None


def test_values_batch_get_builds_repeated_range_query(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, str] = {}

    def fake_request(method, url, *, response_model, **_):
        seen["method"], seen["url"] = method, url
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.values_batch_get("sid", ["S!A1:B2", "S!D1"], "UNFORMATTED_VALUE")
    assert seen["method"] == "GET"
    assert "values:batchGet?" in seen["url"]
    assert "ranges=S%21A1%3AB2" in seen["url"]
    assert "ranges=S%21D1" in seen["url"]
    assert "valueRenderOption=UNFORMATTED_VALUE" in seen["url"]


def test_values_clear_posts_empty_body_to_clear_suffix(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["method"], seen["url"], seen["json"] = method, url, json
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.values_clear("sid", "S!A1:B2")
    assert seen["method"] == "POST"
    assert str(seen["url"]).endswith(":clear")
    assert seen["json"] == {}


def test_values_batch_clear_posts_ranges(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["url"], seen["json"] = url, json
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.values_batch_clear("sid", ["S!A1", "S!B2"])
    assert str(seen["url"]).endswith("values:batchClear")
    assert seen["json"] == {"ranges": ["S!A1", "S!B2"]}


def test_list_sheets_extracts_properties(monkeypatch):
    meta = SpreadsheetMeta(
        sheets=[
            SheetEntry(
                properties=SheetProperties(
                    sheetId=0,
                    title="Budget",
                    index=0,
                    gridProperties=GridProperties(rowCount=100, columnCount=12),
                )
            ),
            SheetEntry(),  # a sheet with no properties is skipped
        ]
    )
    monkeypatch.setattr(_sheets, "_sheets_request", lambda *_a, **_k: meta)
    props = _sheets.list_sheets("sid")
    assert [p.title for p in props] == ["Budget"]
    assert props[0].gridProperties is not None
    assert props[0].gridProperties.rowCount == 100


def test_rename_sheet_request_shape(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["url"], seen["json"] = url, json
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.rename_sheet("sid", 7, "Budget")
    assert str(seen["url"]).endswith(":batchUpdate")
    assert seen["json"] == {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": 7, "title": "Budget"},
                    "fields": "title",
                }
            }
        ]
    }


def test_delete_sheet_request_shape(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["json"] = json
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.delete_sheet("sid", 7)
    assert seen["json"] == {"requests": [{"deleteSheet": {"sheetId": 7}}]}


def test_duplicate_sheet_omits_name_when_absent(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["json"] = json
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.duplicate_sheet("sid", 7)
    assert seen["json"] == {"requests": [{"duplicateSheet": {"sourceSheetId": 7}}]}
    _ = _sheets.duplicate_sheet("sid", 7, "Copy")
    assert seen["json"] == {
        "requests": [{"duplicateSheet": {"sourceSheetId": 7, "newSheetName": "Copy"}}]
    }


def test_create_spreadsheet_posts_title(monkeypatch):
    monkeypatch.setattr(_google, "get_access_token", lambda *_a, **_k: "tok")
    seen: dict[str, object] = {}

    def fake_request(method, url, *, response_model, json=None, **_):
        seen["method"], seen["url"], seen["json"] = method, url, json
        return response_model()

    monkeypatch.setattr(_google, "request_validated_json", fake_request)
    _ = _sheets.create_spreadsheet("New Budget")
    assert seen["method"] == "POST"
    assert str(seen["url"]).endswith("/spreadsheets")
    assert seen["json"] == {"properties": {"title": "New Budget"}}


# --- command-level: dry-run contract for the new mutating commands ---


def _clear_args(*, write: bool) -> sheets._Args:
    args = sheets._Args()
    args.command = "clear"
    args.spreadsheet = "sid"
    args.range = "Budget!A1:B2"
    args.write = write
    return args


def test_clear_dry_run_makes_no_write(monkeypatch, capsys):
    calls: list[tuple[str, str]] = []

    def fake_clear(sid, rng):
        calls.append((sid, rng))
        return ClearValuesResponse(clearedRange=rng)

    monkeypatch.setattr(_sheets, "values_clear", fake_clear)
    sheets.cmd_clear(_clear_args(write=False), "sid")
    assert calls == []
    assert '"dryRun": true' in capsys.readouterr().out


def test_clear_write_calls_api(monkeypatch, capsys):
    calls: list[tuple[str, str]] = []

    def fake_clear(sid, rng):
        calls.append((sid, rng))
        return ClearValuesResponse(clearedRange=rng)

    monkeypatch.setattr(_sheets, "values_clear", fake_clear)
    sheets.cmd_clear(_clear_args(write=True), "sid")
    assert calls == [("sid", "Budget!A1:B2")]
    assert '"clearedRange"' in capsys.readouterr().out


def test_batch_clear_dry_run_lists_ranges(monkeypatch, capsys):
    monkeypatch.setattr(
        _sheets,
        "values_batch_clear",
        lambda _sid, _ranges: BatchClearValuesResponse(),
    )
    args = sheets._Args()
    args.command = "batch-clear"
    args.spreadsheet = "sid"
    args.ranges = '["S!A1", "S!B2"]'
    args.write = False
    sheets.cmd_batch_clear(args, "sid")
    out = capsys.readouterr().out
    assert '"dryRun": true' in out
    assert "S!A1" in out


def _sheet_props() -> list[SheetProperties]:
    return [
        SheetProperties(sheetId=5, title="Sheet1"),
        SheetProperties(sheetId=6, title="Budget"),
    ]


def _rename_args(*, write: bool, sheet: str = "Sheet1") -> sheets._Args:
    args = sheets._Args()
    args.command = "rename-sheet"
    args.spreadsheet = "sid"
    args.sheet = sheet
    args.to = "Tab1"
    args.write = write
    return args


def test_rename_sheet_dry_run_resolves_id(monkeypatch, capsys):
    monkeypatch.setattr(_sheets, "list_sheets", lambda _sid: _sheet_props())
    calls: list[object] = []
    monkeypatch.setattr(_sheets, "rename_sheet", lambda *a: calls.append(a))
    sheets.cmd_rename_sheet(_rename_args(write=False), "sid")
    out = capsys.readouterr().out
    assert calls == []
    assert '"dryRun": true' in out
    assert '"sheetId": 5' in out


def test_rename_sheet_write_targets_resolved_id(monkeypatch, capsys):
    monkeypatch.setattr(_sheets, "list_sheets", lambda _sid: _sheet_props())
    calls: list[tuple[str, int, str]] = []

    def fake_rename(sid, sheet_id, new_title):
        calls.append((sid, sheet_id, new_title))
        return BatchUpdateSpreadsheetResponse()

    monkeypatch.setattr(_sheets, "rename_sheet", fake_rename)
    sheets.cmd_rename_sheet(_rename_args(write=True), "sid")
    assert calls == [("sid", 5, "Tab1")]
    capsys.readouterr()


def test_rename_sheet_unknown_name_raises(monkeypatch):
    monkeypatch.setattr(_sheets, "list_sheets", lambda _sid: _sheet_props())
    with pytest.raises(sheets.CliError):
        sheets.cmd_rename_sheet(_rename_args(write=True, sheet="Ghost"), "sid")


def test_delete_sheet_dry_run_no_write(monkeypatch, capsys):
    monkeypatch.setattr(_sheets, "list_sheets", lambda _sid: _sheet_props())
    calls: list[object] = []
    monkeypatch.setattr(_sheets, "delete_sheet", lambda *a: calls.append(a))
    args = sheets._Args()
    args.command = "delete-sheet"
    args.spreadsheet = "sid"
    args.sheet = "Budget"
    args.write = False
    sheets.cmd_delete_sheet(args, "sid")
    out = capsys.readouterr().out
    assert calls == []
    assert '"wouldDelete": "Budget"' in out
    assert '"sheetId": 6' in out


def test_duplicate_sheet_write_reports_new_title(monkeypatch, capsys):
    monkeypatch.setattr(_sheets, "list_sheets", lambda _sid: _sheet_props())

    def fake_dup(_sid, _sheet_id, new_title):
        return BatchUpdateSpreadsheetResponse(
            replies=[
                BatchUpdateReply(
                    duplicateSheet=DuplicateSheetReply(
                        properties=SheetProperties(
                            sheetId=99, title=new_title or "Copy of Budget"
                        )
                    )
                )
            ]
        )

    monkeypatch.setattr(_sheets, "duplicate_sheet", fake_dup)
    args = sheets._Args()
    args.command = "duplicate-sheet"
    args.spreadsheet = "sid"
    args.sheet = "Budget"
    args.to = "Budget 2027"
    args.write = True
    sheets.cmd_duplicate_sheet(args, "sid")
    out = capsys.readouterr().out
    assert '"newSheetId": 99' in out
    assert '"newTitle": "Budget 2027"' in out


def _create_args(*, write: bool) -> sheets._Args:
    args = sheets._Args()
    args.command = "create"
    args.title = "New Budget"
    args.write = write
    return args


def test_create_dry_run_makes_no_call(monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(_sheets, "create_spreadsheet", calls.append)
    sheets.cmd_create(_create_args(write=False), "")
    assert calls == []
    assert '"wouldCreate": "New Budget"' in capsys.readouterr().out


def _fake_create(monkeypatch):
    def fake_create(title):
        return CreateSpreadsheetResponse(
            spreadsheetId="newid",
            spreadsheetUrl="https://docs.google.com/spreadsheets/d/newid/edit",
            properties=SpreadsheetProperties(title=title),
        )

    monkeypatch.setattr(_sheets, "create_spreadsheet", fake_create)


def test_create_write_oauth_default_notes_ownership(monkeypatch, capsys):
    # oauth is the default mode, so a created sheet is the user's and opens directly.
    _fake_create(monkeypatch)
    sheets.cmd_create(_create_args(write=True), "")
    out = capsys.readouterr().out
    assert '"spreadsheetId": "newid"' in out
    assert "your Google account" in out
    assert "service account" not in out


def test_create_write_service_mode_notes_sharing(monkeypatch, capsys):
    # --auth service makes a service-account-owned sheet that must be shared.
    _fake_create(monkeypatch)
    with _google.using_auth("service"):
        sheets.cmd_create(_create_args(write=True), "")
    out = capsys.readouterr().out
    assert '"spreadsheetId": "newid"' in out
    assert "service account" in out


def test_sheets_request_threads_active_auth(monkeypatch):
    """The CLI's auth mode reaches the transport: _sheets_request passes the active
    mode (current_auth) to authed_request, with no per-function threading."""
    seen: dict[str, object] = {}

    def fake_authed(method, url, *, response_model, scopes, auth, **_):
        seen["auth"] = auth
        return response_model()

    monkeypatch.setattr(_sheets, "authed_request", fake_authed)
    with _google.using_auth("service"):
        _ = _sheets.values_get("sid", "S!A1")
    assert seen["auth"] == "service"
    with _google.using_auth("oauth"):
        _ = _sheets.values_get("sid", "S!A1")
    assert seen["auth"] == "oauth"


def test_auth_parent_defaults_to_oauth():
    parser = _cli.auth_parent()
    assert parser.parse_args([]).auth == "oauth"
    assert parser.parse_args(["--auth", "service"]).auth == "service"


def test_cmd_list_sheets_outputs_dimensions(monkeypatch, capsys):
    monkeypatch.setattr(
        _sheets,
        "list_sheets",
        lambda _sid: [
            SheetProperties(
                sheetId=0,
                title="Budget",
                index=0,
                gridProperties=GridProperties(rowCount=100, columnCount=12),
            )
        ],
    )
    sheets.cmd_list_sheets(sheets._Args(), "sid")
    out = capsys.readouterr().out
    assert '"title": "Budget"' in out
    assert '"rows": 100' in out
    assert '"columns": 12' in out


def test_cmd_batch_get_outputs_value_ranges(monkeypatch, capsys):
    def fake_bg(_sid, _ranges, _render):
        return BatchGetValuesResponse(
            valueRanges=[
                ValueRange(range="S!A1:B1", values=[["a", "b"]]),
                ValueRange(range="S!D1", values=[[1]]),
            ]
        )

    monkeypatch.setattr(_sheets, "values_batch_get", fake_bg)
    args = sheets._Args()
    args.command = "batch-get"
    args.spreadsheet = "sid"
    args.ranges = '["S!A1:B1", "S!D1"]'
    args.value_render = None
    sheets.cmd_batch_get(args, "sid")
    out = capsys.readouterr().out
    assert '"rangeCount": 2' in out


def test_error_envelope_includes_status_and_code():
    env = _cli.error_envelope(
        "read-range",
        "spreadsheetId",
        "sid",
        "PERMISSION_DENIED: no",
        status="PERMISSION_DENIED",
        code=403,
    )
    assert env["status"] == "PERMISSION_DENIED"
    assert env["code"] == 403


def test_error_envelope_omits_absent_status_and_code():
    env = _cli.error_envelope("read-range", "spreadsheetId", "sid", "boom")
    assert "status" not in env
    assert "code" not in env


# --- find-replace ---


def _find_replace_args(*, write: bool, sheet: str | None = None) -> sheets._Args:
    args = sheets._Args()
    args.command = "find-replace"
    args.spreadsheet = "sid"
    args.find = "Q1"
    args.replace = "Quarter 1"
    args.sheet = sheet
    args.match_case = False
    args.match_entire_cell = False
    args.regex = False
    args.include_formulas = False
    args.write = write
    return args


def test_find_replace_dry_run_all_sheets_makes_no_call(monkeypatch, capsys):
    calls: list[object] = []
    monkeypatch.setattr(_sheets, "find_replace", lambda *_a, **k: calls.append(k))
    sheets.cmd_find_replace(_find_replace_args(write=False), "sid")
    out = capsys.readouterr().out
    assert calls == []
    assert '"dryRun": true' in out
    assert '"scope": "all sheets"' in out


def test_find_replace_write_all_sheets_reports_count(monkeypatch, capsys):
    def fake_fr(_sid, **kwargs):
        assert kwargs["sheet_id"] is None
        return BatchUpdateSpreadsheetResponse(
            replies=[
                BatchUpdateReply(
                    findReplace=FindReplaceReply(occurrencesChanged=3, valuesChanged=2)
                )
            ]
        )

    monkeypatch.setattr(_sheets, "find_replace", fake_fr)
    sheets.cmd_find_replace(_find_replace_args(write=True), "sid")
    assert '"occurrencesChanged": 3' in capsys.readouterr().out


def test_find_replace_scopes_to_resolved_sheet_id(monkeypatch, capsys):
    monkeypatch.setattr(
        _sheets,
        "list_sheets",
        lambda _sid: [SheetProperties(sheetId=6, title="Budget")],
    )
    seen: dict[str, object] = {}

    def fake_fr(_sid, **kwargs):
        seen.update(kwargs)
        return BatchUpdateSpreadsheetResponse(
            replies=[
                BatchUpdateReply(findReplace=FindReplaceReply(occurrencesChanged=1))
            ]
        )

    monkeypatch.setattr(_sheets, "find_replace", fake_fr)
    sheets.cmd_find_replace(_find_replace_args(write=True, sheet="Budget"), "sid")
    assert seen["sheet_id"] == 6
    capsys.readouterr()


def test_find_replace_unknown_sheet_raises(monkeypatch):
    monkeypatch.setattr(
        _sheets,
        "list_sheets",
        lambda _sid: [SheetProperties(sheetId=6, title="Budget")],
    )
    with pytest.raises(sheets.CliError):
        sheets.cmd_find_replace(_find_replace_args(write=True, sheet="Ghost"), "sid")


# --- non-idempotent writes must not be retried (no duplicate rows / objects) ---


def _capture_idempotent(monkeypatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_request(_method, _url, *, response_model, idempotent=True, **_):
        captured["idempotent"] = idempotent
        return response_model.model_validate({})

    monkeypatch.setattr(_sheets, "_sheets_request", fake_request)
    return captured


def test_values_append_runs_once(monkeypatch):
    captured = _capture_idempotent(monkeypatch)
    _ = _sheets.values_append("sid", "Sheet!A1", [["x"]], "RAW")
    assert captured["idempotent"] is False


def test_values_update_stays_retried(monkeypatch):
    captured = _capture_idempotent(monkeypatch)
    _ = _sheets.values_update("sid", "Sheet!A1", [["x"]], "RAW")
    assert captured["idempotent"] is True


def test_duplicate_sheet_runs_once(monkeypatch):
    captured = _capture_idempotent(monkeypatch)
    _ = _sheets.duplicate_sheet("sid", 6, "Copy")
    assert captured["idempotent"] is False
