"""Materialize and query the disposable DuckDB cache over canonical tracker data.

The trackers framework (``.claude/rules/trackers.md``) stores machine telemetry
as append-only JSONL under the owning folder (e.g. ``Health/data/canonical/``).
This module is the query layer over those files:

- ``rebuild`` materializes every configured dataset into a DuckDB file OUTSIDE
  the iCloud tree (default ``~/.cache/vault-data/aesc.duckdb``, override with
  ``VAULT_DB_PATH``). The cache is disposable: never the record, always
  rebuildable from the JSONL.
- ``query`` runs read-only SQL against the cache.
- ``datasets`` lists the configured datasets and their matching source files.

Datasets are declared in ``vault_scripts/datasets.json`` (override with
``VAULT_DATASETS_JSON``): table name -> vault-relative glob.

Examples:

    scripts/vault-tool db datasets
    scripts/vault-tool db rebuild --write
    scripts/vault-tool db query "SELECT type, count(*) FROM activities GROUP BY 1"
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import re
import sys

import duckdb  # pyright: ignore[reportMissingModuleSource]  # compiled extension; typed via typings/duckdb
from pydantic import ValidationError

from vault_scripts._cli import (
    CliError,
    emit_write,
    envelope,
    error_envelope,
    print_json,
)
from vault_scripts._types import DatasetsConfig
from vault_scripts._utils import VAULT, parse_typed_args

_ID_KEY = "db"
DEFAULT_DB_PATH = "~/.cache/vault-data/aesc.duckdb"
DEFAULT_QUERY_LIMIT = 200
_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Exit codes match the _cli contract: 2 validation (CliError.code), 5 API/engine.
_EXIT_ENGINE = 5


def _db_path() -> Path:
    return Path(os.environ.get("VAULT_DB_PATH", DEFAULT_DB_PATH)).expanduser()


def _config_path() -> Path:
    env = os.environ.get("VAULT_DATASETS_JSON")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent / "datasets.json"


def _load_datasets() -> dict[str, str]:
    """Read and validate the datasets config; dataset names double as DuckDB
    table names, so they must be plain identifiers (also the SQL-injection
    guard for the CREATE TABLE built in :func:`_rebuild`)."""
    path = _config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CliError(f"cannot read datasets config {path}: {e}") from e
    try:
        cfg = DatasetsConfig.model_validate_json(raw)
    except ValidationError as e:
        raise CliError(f"malformed datasets config {path}: {e}") from e
    for name in cfg.datasets:
        if not _TABLE_NAME_RE.match(name):
            raise CliError(f"dataset name is not a valid table identifier: {name!r}")
    return cfg.datasets


def _dataset_files(pattern: str) -> list[Path]:
    return sorted(VAULT.glob(pattern))


def _quote_sql_string(s: str) -> str:
    """Single-quote a string for interpolation into DuckDB SQL (paths can't be
    bound as parameters inside read_json_auto's list literal)."""
    escaped = s.replace("'", "''")
    return f"'{escaped}'"


def _json_safe(value: object) -> object:
    """Coerce a DuckDB cell to a JSON-serializable value (dates, decimals, and
    other engine types stringify)."""
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        # NaN/Infinity aren't valid JSON; json.dumps would emit bare NaN/Infinity
        # tokens that break strict consumers (jq, JS JSON.parse). Stringify them.
        return value if math.isfinite(value) else str(value)
    return str(value)


def _rebuild_plan(datasets: dict[str, str]) -> list[dict[str, object]]:
    return [
        {"dataset": name, "glob": pattern, "files": len(_dataset_files(pattern))}
        for name, pattern in datasets.items()
    ]


def _rebuild(datasets: dict[str, str], db_path: Path) -> dict[str, object]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    con = duckdb.connect(str(db_path))
    try:
        for name, pattern in datasets.items():
            files = _dataset_files(pattern)
            if not files:
                results.append({
                    "dataset": name,
                    "files": 0,
                    "rows": 0,
                    "skipped": "no files match glob",
                })
                continue
            file_list = ", ".join(_quote_sql_string(str(f)) for f in files)
            # Identifier validated in _load_datasets, paths quoted above.
            con.execute(
                f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM "  # noqa: S608
                f"read_json_auto([{file_list}], format='newline_delimited')"
            )
            counted = con.execute(f"SELECT count(*) FROM {name}").fetchall()  # noqa: S608
            rows = _json_safe(counted[0][0]) if counted else 0
            results.append({"dataset": name, "files": len(files), "rows": rows})
    finally:
        con.close()
    return {"datasets": results, "dbPath": str(db_path)}


def _query(sql: str, db_path: Path, limit: int) -> dict[str, object]:
    if limit < 1:
        raise CliError(f"--limit must be >= 1 (got {limit})")
    if not db_path.exists():
        raise CliError(
            f"no cache at {db_path}; run `vault-tool db rebuild --write` first"
        )
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cur = con.execute(sql)
        desc = cur.description
        columns = [d[0] for d in desc] if desc is not None else []
        raw_rows = cur.fetchmany(limit + 1)
    finally:
        con.close()
    if len(set(columns)) != len(columns):
        # Rows are keyed by column name; duplicates would silently collapse and
        # drop a value. Fail loud so the user aliases them uniquely.
        raise CliError("query selects duplicate column names; alias them uniquely")
    truncated = len(raw_rows) > limit
    rows: list[dict[str, object]] = [
        {col: _json_safe(v) for col, v in zip(columns, row, strict=False)}
        for row in raw_rows[:limit]
    ]
    return {
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "truncated": truncated,
    }


class _Args(argparse.Namespace):
    command: str
    sql: str
    limit: int
    write: bool


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Disposable DuckDB cache over canonical tracker JSONL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rebuild_p = sub.add_parser("rebuild", help="materialize datasets into the cache")
    _ = rebuild_p.add_argument(
        "--write", action="store_true", help="apply (default: print the dry-run plan)"
    )

    query_p = sub.add_parser("query", help="run read-only SQL against the cache")
    _ = query_p.add_argument("sql", help="SQL to execute")
    _ = query_p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_QUERY_LIMIT,
        help=f"max rows in the envelope (default {DEFAULT_QUERY_LIMIT})",
    )

    _ = sub.add_parser("datasets", help="list configured datasets and their files")

    args = parse_typed_args(parser, _Args)
    db_path = _db_path()

    try:
        datasets = _load_datasets()
        if args.command == "rebuild":
            emit_write(
                "rebuild",
                _ID_KEY,
                str(db_path),
                write=args.write,
                dry={"datasets": _rebuild_plan(datasets)},
                apply=lambda: _rebuild(datasets, db_path),
            )
        elif args.command == "query":
            result = _query(args.sql, db_path, args.limit)
            print_json(envelope("query", _ID_KEY, str(db_path), result))
        else:
            info = {"datasets": _rebuild_plan(datasets), "cacheExists": db_path.exists()}
            print_json(envelope("datasets", _ID_KEY, str(db_path), info))
    except CliError as e:
        print_json(error_envelope(args.command, _ID_KEY, str(db_path), str(e)))
        sys.exit(e.code)
    except duckdb.Error as e:
        print_json(error_envelope(args.command, _ID_KEY, str(db_path), f"duckdb: {e}"))
        sys.exit(_EXIT_ENGINE)


if __name__ == "__main__":
    main()
