"""Shared utilities for vault_scripts.

Frontmatter patching, file discovery, and display helpers. Imported by
the package's entry-point scripts. Env loading is handled upstream by
``scripts/vault-tool`` via ``uv run --env-file .env``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import cast

import frontmatter
import yaml

# Keep __pycache__ out of the iCloud-synced vault tree
sys.pycache_prefix = str(Path.home() / ".cache" / "pycache")

_PACKAGE_DIR = Path(__file__).resolve().parent   # scripts/vault_scripts/
_SCRIPTS_DIR = _PACKAGE_DIR.parent               # scripts/

# When the scripts/ directory is symlinked into a separate vault (common
# now that this package lives in its own git repo), Path.resolve above
# yields the physical repo path — wrong for vault operations. The
# dispatcher exports VAULT_DIR using bash's logical pwd, which preserves
# the symlink. Honor it when present; fall back to the script's parent
# for direct invocations of a vault-colocated scripts/ tree.
_vault_env = os.environ.get("VAULT_DIR")
VAULT = Path(_vault_env) if _vault_env else _SCRIPTS_DIR.parent
TRAVEL_DIR = VAULT / "Travel"

# Frontmatter splits on "---" into [before, yaml, body] → three parts
_FM_PARTS_EXPECTED = 3

# Categories with geocodable venues (not areas like Destinations/Neighborhoods)
GEO_CATEGORIES: frozenset[str] = frozenset(
    {"Dining", "Experiences", "Shopping", "Accommodations"}
)
GEO_FIELDS: tuple[str, ...] = (
    "coordinates",
    "google_maps_url",
    "address",
    "address_local",
)


# --- Env helpers ---

def parse_typed_args[T: argparse.Namespace](
    parser: argparse.ArgumentParser, cls: type[T],
) -> T:
    """Parse CLI args into a typed ``argparse.Namespace`` subclass.

    ``cls`` must declare attribute annotations matching each argparse
    ``dest`` the parser writes. argparse populates the instance via
    ``setattr``; passing ``namespace=cls()`` threads the type through
    so call sites get typed attribute access without per-field casts.
    """
    return parser.parse_args(namespace=cls())


def require_env(name: str) -> str:
    """Get a required env var, or exit with a JSON error message for
    skill/script callers that consume our stdout.

    Scripts invoked via ``scripts/vault-tool`` inherit ``.env`` through
    ``uv run --env-file`` — no Python-side loading needed.
    """
    val = os.environ.get(name)
    if not val:
        print(json.dumps({"error": f"Missing env var: {name}"}))
        sys.exit(1)
    return val


def resolve_file_arg(file_arg: str) -> Path:
    """Resolve a CLI ``--file`` argument to an existing path.

    Tries ``VAULT / file_arg`` first (lets callers pass vault-relative
    paths like ``Travel/Japan26/Dining/entries/Den.md``), then the raw
    argument as an absolute/CWD-relative path. Exits with a JSON error
    if neither resolves — matches the rest of the package's "fail fast
    to stdout JSON" convention for script-invoking skills.
    """
    file_path = VAULT / file_arg
    if not file_path.exists():
        file_path = Path(file_arg)
    if not file_path.exists():
        print(json.dumps({"status": "error", "error": f"File not found: {file_arg}"}))
        sys.exit(1)
    return file_path


# --- Frontmatter helpers ---

def fm_str(metadata: dict[str, object], field: str) -> str:
    """Strips YAML quoting artifacts — frontmatter values sometimes retain
    surrounding double-quotes after parsing depending on the quoting style.
    """
    return str(metadata.get(field, "")).strip().strip('"')


def _match_field_line(field: str) -> tuple[str, str]:
    """Return (pattern_with_value, pattern_empty) regexes for a frontmatter field."""
    escaped = re.escape(field)
    return rf'^({escaped}:) .*$', rf'^({escaped}:)\s*$'


def yaml_scalar(value: object) -> str:
    """Format a Python value as a YAML scalar line fragment.

    Bools and ints emit unquoted; strings get double-quoted with embedded
    quotes escaped. Empty strings and None emit as ``""``.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not value:
        return '""'
    return f'"{str(value).replace(chr(34), chr(92) + chr(34))}"'


def patch_field(text: str, field: str, value: object) -> str:
    """Upsert a frontmatter field. ``value`` is any Python scalar — it's
    formatted via :func:`yaml_scalar` (ints stay bare, strings get quoted).

    Replaces the value if the field exists, otherwise inserts before the
    closing ``---``.
    """
    escaped = re.escape(field)
    yaml_val = yaml_scalar(value)
    if re.search(rf'^{escaped}:', text, flags=re.MULTILINE):
        pat_val, pat_empty = _match_field_line(field)
        replacement = rf'\1 {yaml_val}'
        new_text = re.sub(pat_val, replacement, text, count=1, flags=re.MULTILINE)
        if new_text != text:
            return new_text
        return re.sub(pat_empty, replacement, text, count=1, flags=re.MULTILINE)
    return insert_before_closing_fence(text, field, value)


def insert_field_after(
    text: str, after_field: str, new_field: str, value: object,
) -> str:
    """Insert a new frontmatter field after an existing one."""
    yaml_val = yaml_scalar(value)
    replacement = rf'\1\n{new_field}: {yaml_val}'
    pat_val, pat_empty = _match_field_line(after_field)
    new_text = re.sub(pat_val, replacement, text, count=1, flags=re.MULTILINE)
    if new_text == text:
        new_text = re.sub(pat_empty, replacement, text, count=1, flags=re.MULTILINE)
    return new_text


def insert_before_closing_fence(text: str, field: str, value: object) -> str:
    """Insert a field before the closing --- of frontmatter."""
    parts = text.split("---", 2)
    if len(parts) >= _FM_PARTS_EXPECTED:
        fm = parts[1].rstrip("\n")
        return f"---{fm}\n{field}: {yaml_scalar(value)}\n---{parts[2]}"
    return text


# --- Body helpers ---

def add_inline_embed(text: str, image_filename: str) -> str:
    """Add or update ![[image|600]] after the [!summary] callout.

    If an existing embed is found (any ![[*.webp|600]]), replace it.
    Otherwise insert after the [!summary] callout block, or after
    frontmatter if no summary exists.
    """
    embed = f"![[{image_filename}|600]]"

    existing = re.search(r'^!\[\[.*\.webp\|600\]\]$', text, flags=re.MULTILINE)
    if existing:
        if existing.group() == embed:
            return text
        return text[:existing.start()] + embed + text[existing.end():]

    lines = text.split("\n")
    in_frontmatter = False
    fm_end_idx: int | None = None
    breadcrumb_idx: int | None = None
    summary_found = False
    insert_idx: int | None = None

    for i, line in enumerate(lines):
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
            else:
                fm_end_idx = i
            continue
        if fm_end_idx is None:
            continue
        if breadcrumb_idx is None and "]] · [[" in line:
            breadcrumb_idx = i
        if "[!summary]" in line:
            summary_found = True
            continue
        if summary_found and line.startswith(">"):
            continue
        if summary_found and not line.startswith(">"):
            insert_idx = i
            break

    if insert_idx is None:
        if breadcrumb_idx is not None:
            insert_idx = breadcrumb_idx + 1
        elif fm_end_idx is not None:
            insert_idx = fm_end_idx + 1

    if insert_idx is not None:
        lines.insert(insert_idx, "")
        lines.insert(insert_idx + 1, embed)
        return "\n".join(lines)

    return text


# --- File discovery ---

def find_images_dir(file_path: Path) -> Path:
    """Walk up from the file to find the trip root, return its images/ dir."""
    rel = file_path.relative_to(TRAVEL_DIR)
    trip_name = rel.parts[0]
    images_dir = TRAVEL_DIR / trip_name / "images"
    images_dir.mkdir(exist_ok=True)
    return images_dir


def _tags_of(post: frontmatter.Post) -> list[str]:
    """Extract the tags list from a post, handling string/list/None shapes."""
    raw = post.metadata.get("tags", [])
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        items = cast(list[object], raw)
        return [t for t in items if isinstance(t, str)]
    return []


def find_entry_files(
    trip_dir: Path,
    categories: list[str] | frozenset[str],
    valid_tags: set[str] | frozenset[str],
) -> list[tuple[Path, frontmatter.Post, str, str]]:
    """Discover tagged entry files. Returns (path, post, category, raw_text)
    tuples. Raw text is included so callers doing regex operations don't
    need to re-read each file. Skips hub notes, .base files, and files
    without a matching tag.
    """
    hub_files = {f"{c}.md" for c in categories}
    files: list[tuple[Path, frontmatter.Post, str, str]] = []
    for category in categories:
        cat_dir = trip_dir / category
        if not cat_dir.exists():
            continue
        for f in sorted(cat_dir.rglob("*.md")):
            if f.name in hub_files or f.suffix == ".base":
                continue
            try:
                text = f.read_text(encoding="utf-8")
                post = frontmatter.loads(text)
            except (yaml.YAMLError, OSError):
                continue
            if any(t in valid_tags for t in _tags_of(post)):
                files.append((f, post, category, text))
    return files


# --- Display ---

def rel_path(p: Path) -> Path:
    """Vault-relative path for display. Falls back to absolute if outside vault."""
    return p.relative_to(VAULT) if p.is_relative_to(VAULT) else p
