"""Shared CLI plumbing for the ``docs`` and ``sheets`` subcommand modules.

Both wrap an id-bearing Google resource and emit the same JSON envelope contract
(``{ok, cmd, <idKey>, result}`` on success, ``{ok: false, ..., error}`` on
failure) with the same exit-code mapping (2 validation, 3 auth, 4 permission, 5
API) and the same dry-run-before-write guard. Keeping that contract in one place
stops the two CLIs from drifting; each passes its own id key ("documentId" /
"spreadsheetId").
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import re
import sys
from typing import Protocol

from vault_scripts._google import (
    EXIT_AUTH,
    EXIT_VALIDATION,
    OAUTH_USER_SCOPES,
    AuthMode,
    GoogleAuthError,
    exit_code_for_api_error,
    format_api_error,
    google_error,
    oauth_login,
    oauth_token_path,
    using_auth,
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


def auth_parent() -> argparse.ArgumentParser:
    """Shared ``--auth`` flag for the docs and sheets CLIs.

    OAuth-user is the default mode of interacting: it acts as the user and can own
    the files it creates, so no per-resource sharing is needed. ``--auth service`` opts
    into the sandboxed service account (sees only what's explicitly shared with it;
    unattended-stable for scheduled jobs)."""
    parent = argparse.ArgumentParser(add_help=False)
    _ = parent.add_argument(
        "--auth",
        choices=["oauth", "service"],
        default="oauth",
        help="Auth mode: oauth user (default, acts as you) or service account",
    )
    return parent


def auth_login() -> dict[str, object]:
    """Run the one-time OAuth-user consent and return the result payload (stored
    token path and granted scopes). Shared by ``docs``/``sheets auth-login``; the
    consent always requests ``OAUTH_USER_SCOPES``, every scope the toolchain
    uses, so either subcommand suffices."""
    token = oauth_login(OAUTH_USER_SCOPES)
    return {"stored": str(oauth_token_path()), "scopes": token.scopes}


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


class EnvelopeFn(Protocol):
    """A module's success-envelope builder with its id key bound."""

    def __call__(
        self, cmd: str, id_value: str, result: object, *, ok: bool = True
    ) -> dict[str, object]: ...


class EmitWriteFn(Protocol):
    """A module's dry-run-or-apply tail with its id key bound."""

    def __call__(
        self,
        cmd: str,
        id_value: str,
        *,
        write: bool,
        dry: dict[str, object],
        apply: Callable[[], dict[str, object]],
    ) -> None: ...


def make_envelope(id_key: str) -> EnvelopeFn:
    """Bind ``id_key`` ('documentId'/'spreadsheetId') onto :func:`envelope`, so
    each CLI defines its envelope shape in one line instead of a wrapper body."""

    def bound(
        cmd: str, id_value: str, result: object, *, ok: bool = True
    ) -> dict[str, object]:
        return envelope(cmd, id_key, id_value, result, ok=ok)

    return bound


def make_emit_write(id_key: str) -> EmitWriteFn:
    """Bind ``id_key`` onto :func:`emit_write` (see :func:`make_envelope`)."""

    def bound(
        cmd: str,
        id_value: str,
        *,
        write: bool,
        dry: dict[str, object],
        apply: Callable[[], dict[str, object]],
    ) -> None:
        emit_write(cmd, id_key, id_value, write=write, dry=dry, apply=apply)

    return bound


def run_cli(
    command: str,
    id_key: str,
    id_value: str,
    auth: AuthMode,
    run: Callable[[], None],
) -> None:
    """Shared ``main`` tail: bind the invocation's auth mode, run the command, and
    map each failure to an error envelope and the matching exit code."""
    try:
        with using_auth(auth):
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
