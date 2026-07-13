"""Bulk-safe frontmatter field editor for the vault.

``obsidian property:set`` rewrites the whole YAML block through Obsidian's own
serializer, which strips the vault's convention quotes: ``created: "2026-07-02"``
comes back a bare YAML date, quoted ``coordinates`` lose their quotes, and every
other string field is re-emitted with minimal quoting regardless of which key
you set. There is no quote-style flag to turn that off.

This module edits frontmatter the way the rest of the toolchain does: one line
at a time through the :mod:`vault_scripts._utils` helpers, leaving every other
line byte-for-byte intact. Values are formatted with
:func:`vault_scripts._utils.yaml_scalar`, the package's single serializer
(strings double-quoted, ints/bools/floats bare), so quoting stays consistent
with the templates. A string value is always quoted, which sidesteps the bare
YAML traps (``accepting_new: yes`` would parse as boolean ``true``); pass
``:int``/``:float``/``:bool`` when you want a bare scalar.

Paths are explicit: callers enumerate the files, and any argument that contains
``=`` is read as an assignment, everything else as a note path. There is no glob
expansion. Dry-run by default; pass ``--write`` to persist. A batch that hits an
unusable file (no frontmatter block) writes nothing, so a bulk apply is
all-or-nothing.

Usage:
    scripts/vault-tool fm set <path> [<path> ...] <key=value> [<key:int=value> ...] [--after FIELD] [--write]

Examples:
    # preview adding two fields to three notes (dry run)
    scripts/vault-tool fm set A.md B.md C.md status=candidate rank=

    # apply, positioning rank right after status
    scripts/vault-tool fm set Health/Providers/entries/Foo.md rank=strong --after status --write

    # a numeric field stays a bare YAML number
    scripts/vault-tool fm set Foo.md score:int=44 --write
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys

import frontmatter

from vault_scripts._utils import (
    find_vault_file,
    has_field,
    parse_typed_args,
    patch_field,
    rel_path,
    upsert_field_after,
)

# A ``key[:type]=value`` assignment. Field names are YAML-plain (letter or
# underscore first, then word chars or hyphens); an optional ``:type`` picks the
# value parser. DOTALL so a value may contain newlines (a multi-line note field).
_ASSIGN_RE = re.compile(
    r"^(?P<field>[A-Za-z_][\w-]*)(?::(?P<type>[a-z]+))?=(?P<value>.*)$",
    re.DOTALL,
)

_TYPES = ("str", "int", "float", "bool")

# Frontmatter splits on "---" into [before, yaml, body] -> three parts.
_FM_PARTS_EXPECTED = 3


class _Args(argparse.Namespace):
    command: str
    items: list[str]
    after: str | None
    write: bool


@dataclass
class _Plan:
    """One file's planned edit: the report shown to the caller, the rewritten
    text (``None`` when the file has no frontmatter and is skipped), and whether
    the text actually changed."""

    fp: Path
    report: dict[str, object]
    new_text: str | None
    changed: bool


class FmError(Exception):
    """User-facing input error (bad assignment, unknown type, missing file)."""


def _parse_value(type_name: str | None, raw: str) -> object:
    """Turn a CLI value string into the Python value handed to ``yaml_scalar``.

    Default (no type) is a string, so ``key=`` yields ``""`` and any text is
    double-quoted. ``:int``/``:float`` emit bare numbers and ``:bool`` accepts
    true/false. A number-looking string stays a quoted string unless an explicit
    numeric type is given, so a ZIP or phone number keeps its quotes.
    """
    if type_name in {None, "str"}:
        return raw
    if type_name == "int":
        try:
            return int(raw)
        except ValueError as e:
            raise FmError(f"not an int: {raw!r}") from e
    if type_name == "float":
        try:
            return float(raw)
        except ValueError as e:
            raise FmError(f"not a float: {raw!r}") from e
    if type_name == "bool":
        low = raw.strip().lower()
        if low in {"true", "false"}:
            return low == "true"
        raise FmError(f"not a bool (use true/false): {raw!r}")
    raise FmError(f"unknown type ':{type_name}' (use one of {', '.join(_TYPES)})")


def parse_assignment(item: str) -> tuple[str, object]:
    """Parse a ``key[:type]=value`` argument into (field, python_value)."""
    m = _ASSIGN_RE.match(item)
    if not m:
        raise FmError(f"not a key=value assignment: {item!r}")
    return m["field"], _parse_value(m["type"], m["value"])


def _has_frontmatter(text: str) -> bool:
    """True when the note opens with a closed ``---`` YAML block. A lone ``---``
    rule in the body is not a fence, so a note without frontmatter is reported as
    an error rather than silently no-op'd."""
    return text.startswith("---") and len(text.split("---", 2)) >= _FM_PARTS_EXPECTED


def apply_assignments(
    text: str,
    assignments: list[tuple[str, object]],
    after: str | None,
) -> tuple[str, list[dict[str, object]]]:
    """Apply every (field, value) to ``text`` and return (new_text, changes).

    Each field is upserted on its own line; all other lines are preserved.
    ``after`` positions newly-added fields right after that anchor field (when
    the anchor exists), otherwise a new field lands before the closing fence.
    ``from``/``action`` are computed against the original text, so the report
    reflects the note as it was before this call.
    """
    original_meta = frontmatter.loads(text).metadata
    new_text = text
    changes: list[dict[str, object]] = []
    for name, value in assignments:
        existed = has_field(text, name)
        if after:
            new_text = upsert_field_after(new_text, name, value, after)
        else:
            new_text = patch_field(new_text, name, value)
        changes.append({
            "field": name,
            "action": "updated" if existed else "added",
            "from": original_meta.get(name) if existed else None,
            "to": value,
        })
    return new_text, changes


def _plan_file(
    fp: Path, assignments: list[tuple[str, object]], after: str | None
) -> _Plan:
    """Read one note and compute its edit, or flag it when it has no frontmatter."""
    text = fp.read_text(encoding="utf-8")
    rel = str(rel_path(fp))
    if not _has_frontmatter(text):
        return _Plan(
            fp,
            {"path": rel, "error": "no frontmatter block", "changed": False},
            None,
            False,
        )
    new_text, changes = apply_assignments(text, assignments, after)
    changed = new_text != text
    return _Plan(
        fp, {"path": rel, "changed": changed, "fields": changes}, new_text, changed
    )


def run_set(items: list[str], after: str | None, write: bool) -> dict[str, object]:
    """Plan and (optionally) apply frontmatter assignments across notes.

    Partitions ``items`` into note paths (no ``=``) and assignments (contain
    ``=``), resolves each path, and computes the edit for every file first. When
    ``write`` is set and no file errored, the whole batch is written; a single
    unusable file aborts the write so nothing lands half-done.
    """
    paths = [i for i in items if "=" not in i]
    raw_assigns = [i for i in items if "=" in i]
    if not paths:
        raise FmError("no note paths given (arguments containing '=' are assignments)")
    if not raw_assigns:
        raise FmError("no key=value assignments given")
    assignments = [parse_assignment(a) for a in raw_assigns]

    resolved: list[Path] = []
    missing: list[str] = []
    for p in paths:
        fp = find_vault_file(p)
        if fp is None:
            missing.append(p)
        else:
            resolved.append(fp)
    if missing:
        raise FmError(f"file(s) not found: {', '.join(missing)}")

    plans = [_plan_file(fp, assignments, after) for fp in resolved]

    errored = [pl for pl in plans if "error" in pl.report]
    # All-or-nothing: never persist a partial batch when a file is unusable.
    do_write = write and not errored
    if do_write:
        for pl in plans:
            if pl.changed and pl.new_text is not None:
                pl.fp.write_text(pl.new_text, encoding="utf-8")

    changed = sum(1 for pl in plans if pl.changed)
    result: dict[str, object] = {
        "ok": not errored,
        "cmd": "fm set",
        "dryRun": not write,
        "written": do_write,
        "summary": {
            "files": len(plans),
            "changed": changed,
            "unchanged": len(plans) - changed - len(errored),
            "errored": len(errored),
        },
        "files": [pl.report for pl in plans],
    }
    if write and errored:
        result["aborted"] = "no files written: fix the errored notes above and retry"
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vault-tool fm",
        description="Bulk-safe frontmatter field editor (quote-preserving).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set", help="Upsert frontmatter fields on one or more notes")
    _ = p_set.add_argument(
        "items",
        nargs="+",
        metavar="PATH|key=value",
        help="note paths and key[:type]=value assignments, mixed in any order",
    )
    _ = p_set.add_argument(
        "--after",
        metavar="FIELD",
        help="position newly-added fields right after this field",
    )
    _ = p_set.add_argument(
        "--write",
        action="store_true",
        help="apply changes (default: dry run)",
    )
    return parser


def main() -> None:
    # Only ``set`` exists today; argparse's required subparser guarantees it, so
    # main dispatches directly instead of branching (which keeps the raise out of
    # the try below). Add a handler map here when a second subcommand lands.
    args = parse_typed_args(_build_parser(), _Args)
    try:
        result = run_set(args.items, args.after, args.write)
    except FmError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
