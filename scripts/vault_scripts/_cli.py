"""Shared CLI plumbing for the ``docs`` and ``sheets`` subcommand modules.

Both wrap an id-bearing Google resource and emit the same JSON envelope contract
(``{ok, cmd, <idKey>, result}`` on success, ``{ok: false, ..., error}`` on
failure) with the same exit-code mapping (2 validation, 3 auth, 4 permission, 5
API) and the same dry-run-before-write guard. Keeping that contract in one place
stops the two CLIs from drifting; each passes its own id key ("documentId" /
"spreadsheetId").
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re
import sys

from vault_scripts._google import (
    EXIT_AUTH,
    EXIT_VALIDATION,
    GoogleAuthError,
    exit_code_for_api_error,
    format_api_error,
    google_error,
)
from vault_scripts._retry import APIError


class CliError(Exception):
    """User-facing input error (bad JSON, missing argument, no matching row).
    Maps to the validation exit code."""

    code = EXIT_VALIDATION


# Matches the /d/<id> segment of any Docs/Sheets URL, including the
# /document/d/<id> and /u/<n>/d/<id> multi-account forms. A bare id has no
# slashes, so .search falls through to it.
_DRIVE_URL_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)")


def parse_drive_id(ref: str) -> str:
    """Accept a bare Drive file ID or a full Docs/Sheets URL, return the ID."""
    m = _DRIVE_URL_RE.search(ref)
    return m.group(1) if m else ref.strip()


def print_json(obj: dict[str, object]) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def require_flag[T](value: T | None, flag: str) -> T:
    """Return a required CLI value as non-optional. argparse enforces presence at
    the parser; this is a runtime guard that also narrows the type."""
    if value is None:
        raise CliError(f"missing required argument: {flag}")
    return value


def envelope(
    cmd: str,
    id_key: str,
    id_value: str,
    result: object,
    *,
    ok: bool = True,
) -> dict[str, object]:
    """The standard success envelope; ``id_key`` is 'documentId'/'spreadsheetId'."""
    return {"ok": ok, "cmd": cmd, id_key: id_value, "result": result}


def error_envelope(
    cmd: str,
    id_key: str,
    id_value: str,
    message: str,
    *,
    status: str | None = None,
    code: int | None = None,
) -> dict[str, object]:
    """Failure envelope. ``status``/``code`` carry Google's machine-readable error
    fields (e.g. PERMISSION_DENIED / 403) when the response body parsed, so scripts
    can branch on them instead of scraping the message."""
    env: dict[str, object] = {"ok": False, "cmd": cmd, id_key: id_value, "error": message}
    if status:
        env["status"] = status
    if code is not None:
        env["code"] = code
    return env


def emit_write(
    cmd: str,
    id_key: str,
    id_value: str,
    *,
    write: bool,
    dry: dict[str, object],
    apply: Callable[[], dict[str, object]],
) -> None:
    """Shared mutating-command tail: print the planned change on a dry-run, or
    apply it and print the result. Centralizing the guard means a command can't
    accidentally skip the dry-run default."""
    result = apply() if write else {"dryRun": True, **dry}
    print_json(envelope(cmd, id_key, id_value, result))


def run_cli(
    command: str,
    id_key: str,
    id_value: str,
    run: Callable[[], None],
) -> None:
    """Shared ``main`` tail: run the command, mapping each failure to an error
    envelope and the matching exit code."""
    try:
        run()
    except GoogleAuthError as e:
        print_json(error_envelope(command, id_key, id_value, str(e)))
        sys.exit(EXIT_AUTH)
    except CliError as e:
        print_json(error_envelope(command, id_key, id_value, str(e)))
        sys.exit(e.code)
    except APIError as e:
        err = google_error(e)
        print_json(
            error_envelope(
                command,
                id_key,
                id_value,
                format_api_error(e),
                status=err.status if err and err.status else None,
                code=err.code if err and err.code else None,
            )
        )
        sys.exit(exit_code_for_api_error(e))
