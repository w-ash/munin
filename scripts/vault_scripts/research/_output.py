"""CLI output plumbing for the research subpackage.

Every research subcommand writes exactly one JSON object to stdout
(:func:`emit_result` / :func:`emit_error`) and exits non-zero on failure; human
progress goes to stderr via :func:`log` so stdout stays machine-parseable for the
skill callers. Self-contained by design: the harness ``.env`` is already loaded by
the ``vault-tool`` dispatcher (``uv run --env-file``), so there is no env or config
handling here.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import sys
from typing import Never

# Date format for the store's ``date_captured`` column.
DATE_FMT = "%Y-%m-%d"


def emit_result(**fields: object) -> None:
    """Print a single success envelope ``{"ok": true, ...}`` to stdout."""
    print(json.dumps({"ok": True, **fields}, default=str))


def emit_error(message: str, **extra: object) -> Never:
    """Print an error envelope to stdout and exit non-zero."""
    print(json.dumps({"ok": False, "error": message, **extra}, default=str))
    sys.exit(1)


def log(*args: object) -> None:
    """Write human-readable progress to stderr, keeping stdout clean for data."""
    print(*args, file=sys.stderr)


def run_cli(main_fn: Callable[[], None]) -> None:
    """Run a subcommand, turning any uncaught error into a JSON envelope.

    ``SystemExit`` (from :func:`emit_error` or argparse) propagates; any other
    exception becomes ``{"ok": false, "error": ...}`` on stdout with exit 1, so a
    command never dies with a bare traceback.
    """
    try:
        main_fn()
    except SystemExit:
        raise
    except Exception as exc:  # top-level CLI boundary by design
        emit_error(f"{type(exc).__name__}: {exc}")
