"""One-way push of a topic's store and computed columns to a Google Sheet.

Grids come straight from the CSV store, and the computed columns arrive as
values (the CLI is the calculator, so the Sheet carries no live formulas). The
caller passes the mode-specific content as a ``SheetExtras`` (computed blocks
joined onto store tabs, plus a doc tab) so this module stays mode-agnostic. The
destination Sheet must already exist; this module writes by Sheet id and never
creates or owns it.

Auth and the REST transport come from the vault's Google stack
(:mod:`vault_scripts._google` / :mod:`vault_scripts._sheets`): oauth-user by
default (acts as you), service account when the topic sets
``[sheets] auth = "service"`` in ``research.toml``. The content-hash skip state
is a disposable dot-file inside the topic directory.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import cast

from vault_scripts import _sheets
from vault_scripts._google import AuthMode, GoogleAuthError, using_auth
from vault_scripts._retry import APIError
from vault_scripts.research._output import emit_error
from vault_scripts.research.store import CONFIG_NAME, DATA_DIR, Topic

# Skip-state cache, keyed by sheet_id, under the topic root. Disposable.
STATE_FILE = ".research-sync-state.json"

# Bumped whenever the pushed tab layout changes, so every topic re-pushes.
LAYOUT_VERSION = "3"

# Modest slack so a value write never exceeds a tab's grid bounds.
MIN_ROWS = 100
MIN_COLS = 8

_VALUE_INPUT = "USER_ENTERED"


@dataclass(frozen=True)
class ComputedBlock:
    """Computed columns appended to one store tab, joined on its id column.

    ``rows`` maps a join id to one value per ``columns`` entry; a store row
    whose id has no computed entry gets empty cells. ``percent_columns``
    names the 0-1-scaled columns to percent-format (never 0-100 values).
    """

    csv_name: str
    join_column: str
    columns: tuple[str, ...]
    # Covariant in the value type so callers can pass a concrete
    # ``dict[str, tuple[float, str, ...]]`` (dict is invariant; Mapping is not).
    rows: Mapping[str, tuple[object, ...]]
    percent_columns: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SheetExtras:
    """Everything mode-specific the mirror adds over the raw CSV passthrough."""

    blocks: tuple[ComputedBlock, ...]
    doc_title: str
    doc_lines: tuple[str, ...] = field(default_factory=tuple)


def tab_title(filename: str) -> str:
    """``taxonomy.csv`` -> ``Taxonomy``, ``individuals.csv`` -> ``Individuals``."""
    return Path(filename).stem.replace("_", " ").title()


def build_grids(topic: Topic, extras: SheetExtras) -> dict[str, list[list[object]]]:
    """Build every tab's grid: store tabs, computed blocks, and the doc tab."""
    grids: dict[str, list[list[object]]] = {}
    blocks = {b.csv_name: b for b in extras.blocks}

    for name, table in topic.tables.items():
        block = blocks.get(name)
        if block:
            grid: list[list[object]] = [[*table.columns, *block.columns]]
            empty: tuple[object, ...] = ("",) * len(block.columns)
            for row in table.rows:
                computed = block.rows.get(row.get(block.join_column, ""), empty)
                grid.append([*(row.get(c, "") for c in table.columns), *computed])
        else:
            grid = [list(table.columns)]
            grid.extend([row.get(c, "") for c in table.columns] for row in table.rows)
        grids[tab_title(name)] = grid

    grids[extras.doc_title] = [[line] for line in extras.doc_lines]
    return grids


def percent_headers_by_tab(extras: SheetExtras) -> dict[str, frozenset[str]]:
    """Which header labels get percent formatting, per tab title."""
    return {tab_title(b.csv_name): b.percent_columns for b in extras.blocks}


def digest(topic: Topic) -> str:
    """Content hash over the store, the config, and the layout version."""
    md5 = hashlib.md5(usedforsecurity=False)
    md5.update(LAYOUT_VERSION.encode())
    md5.update((topic.root / CONFIG_NAME).read_bytes())
    data = topic.root / DATA_DIR
    for path in sorted(data.glob("*.csv")):
        md5.update(path.name.encode())
        md5.update(path.read_bytes())
    return md5.hexdigest()


# --- Skip-state cache (content hash per sheet id) ---


def _state_path(topic: Topic) -> Path:
    return topic.root / STATE_FILE


def _load_state(topic: Topic) -> dict[str, str]:
    path = _state_path(topic)
    if not path.exists():
        return {}
    try:
        raw = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, dict):
        items = cast("dict[object, object]", raw).items()
        return {str(k): str(v) for k, v in items}
    return {}


def _save_state(topic: Topic, state: dict[str, str]) -> None:
    _state_path(topic).write_text(json.dumps(state, indent=2), encoding="utf-8")


# --- Push ---


def _a1(title: str) -> str:
    """A tab title as a quoted A1 sheet reference (single quotes doubled)."""
    return title.replace("'", "''")


def _sheet_url(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def _percent_format_request(
    sheet_id: int, col_index: int, rows: int
) -> dict[str, object]:
    """A ``repeatCell`` request percent-formatting one data column (rows 2..end)."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": rows,
                "startColumnIndex": col_index,
                "endColumnIndex": col_index + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {"type": "PERCENT", "pattern": "0%"}
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def _shape_request(sheet_id: int, rows: int, cols: int) -> dict[str, object]:
    """Grow a tab to fit (never shrinks) and freeze its header row, in one
    ``updateSheetProperties``."""
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "rowCount": rows,
                    "columnCount": cols,
                    "frozenRowCount": 1,
                },
            },
            "fields": (
                "gridProperties.rowCount,gridProperties.columnCount,"
                "gridProperties.frozenRowCount"
            ),
        }
    }


def _push_grids(
    sheet_id: str,
    grids: dict[str, list[list[object]]],
    percent_by_tab: dict[str, frozenset[str]],
) -> dict[str, dict[str, int]]:
    """Mirror the grids onto the Sheet's tabs: add missing tabs, drop tabs the
    store no longer has, resize + freeze + format, then clear and rewrite every
    tab's values. One structural/format batchUpdate, one clear, one value write."""
    titles = list(grids)
    title_set = set(titles)
    existing = {p.title: p for p in _sheets.list_sheets(sheet_id)}

    # Add any tab the store now has but the Sheet lacks.
    for title in titles:
        if title not in existing:
            _ = _sheets.add_sheet(sheet_id, title)

    # Drop tabs no longer backed by the store, never the last remaining sheet.
    survivors = len(existing) + sum(1 for t in titles if t not in existing)
    for title, props in existing.items():
        if title not in title_set and survivors > 1:
            _ = _sheets.delete_sheet(sheet_id, props.sheetId)
            survivors -= 1

    # Re-read for sheetIds and current dims after the structural changes.
    props_by_title = {p.title: p for p in _sheets.list_sheets(sheet_id)}

    requests: list[dict[str, object]] = []
    summary: dict[str, dict[str, int]] = {}
    for title in titles:
        grid = grids[title]
        props = props_by_title[title]
        width = max((len(r) for r in grid), default=MIN_COLS)
        cur = props.gridProperties
        rows = max(len(grid), MIN_ROWS, cur.rowCount if cur else 0)
        cols = max(width, MIN_COLS, cur.columnCount if cur else 0)
        requests.append(_shape_request(props.sheetId, rows, cols))
        header = grid[0] if grid else []
        percent = percent_by_tab.get(title, frozenset())
        for idx, label in enumerate(header):
            if label in percent:
                requests.append(_percent_format_request(props.sheetId, idx, rows))
        summary[title] = {"rows": len(grid), "cols": width}

    if requests:
        # Format empty cells first; the value write below keeps cell formats
        # (clear/update touch values, not formats), so numbers land formatted.
        _ = _sheets.batch_update(sheet_id, requests)

    _ = _sheets.values_batch_clear(sheet_id, [f"'{_a1(t)}'" for t in titles])
    data: list[dict[str, object]] = [
        {"range": f"'{_a1(t)}'!A1", "values": grids[t]} for t in titles if grids[t]
    ]
    if data:
        _ = _sheets.values_batch_update(sheet_id, data, _VALUE_INPUT)
    return summary


def _resolve_auth(topic: Topic) -> AuthMode:
    raw = topic.config.auth or "oauth"
    if raw not in {"oauth", "service"}:
        emit_error(
            f"Invalid auth mode {raw!r} in research.toml; use 'oauth' or 'service'."
        )
    return cast("AuthMode", raw)


def sync(
    topic: Topic,
    extras: SheetExtras,
    *,
    dry_run: bool,
    force: bool,
) -> dict[str, object]:
    """Push the topic to its Sheet. Returns the result envelope fields."""
    auth = _resolve_auth(topic)
    sheet_id = topic.config.sheet_id
    grids = build_grids(topic, extras)
    current = digest(topic)
    state = _load_state(topic)
    if not force and not dry_run and state.get(sheet_id) == current:
        return {"status": "skipped", "reason": "unchanged", "sheet_id": sheet_id}

    identity = "your Google account" if auth == "oauth" else "the service account"
    url = _sheet_url(sheet_id)
    with using_auth(auth):
        try:
            # Confirm the Sheet exists and is reachable before planning or pushing.
            _ = _sheets.list_sheets(sheet_id)
        # APIError is a tuple of exception classes; splat it before adding one more.
        except (*APIError, GoogleAuthError) as exc:
            share_hint = (
                " (share it with the service account as Editor)"
                if auth == "service"
                else ""
            )
            emit_error(
                f"Could not open Sheet {sheet_id} as {identity}{share_hint}.",
                sheet_id=sheet_id,
                detail=str(exc),
            )
        if dry_run:
            plan = {
                title: {
                    "rows": len(grid),
                    "cols": max((len(r) for r in grid), default=0),
                }
                for title, grid in grids.items()
            }
            return {
                "status": "dry-run",
                "sheet_id": sheet_id,
                "url": url,
                "identity": identity,
                "tabs": plan,
            }
        summary = _push_grids(sheet_id, grids, percent_headers_by_tab(extras))
    state[sheet_id] = current
    _save_state(topic, state)
    return {
        "status": "synced",
        "sheet_id": sheet_id,
        "url": url,
        "identity": identity,
        "tabs": summary,
    }
