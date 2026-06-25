"""Shared utilities for vault_scripts.

Frontmatter patching, file discovery, and display helpers. Imported by
the package's entry-point scripts. Env loading is handled upstream by
``scripts/vault-tool`` via ``uv run --env-file .env``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
import functools
import json
import os
from pathlib import Path
import re
import sys
from typing import cast
from urllib.parse import urlparse, urlunparse

import frontmatter
import requests
import yaml

# Keep __pycache__ out of the iCloud-synced vault tree
sys.pycache_prefix = str(Path.home() / ".cache" / "pycache")

_PACKAGE_DIR = Path(__file__).resolve().parent  # scripts/vault_scripts/
_SCRIPTS_DIR = _PACKAGE_DIR.parent  # scripts/

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
GEO_CATEGORIES: frozenset[str] = frozenset({
    "Dining",
    "Experiences",
    "Shopping",
    "Accommodations",
})
GEO_FIELDS: tuple[str, ...] = (
    "coordinates",
    "google_maps_url",
    "address",
    "address_local",
)


# --- Env helpers ---


def parse_typed_args[T: argparse.Namespace](
    parser: argparse.ArgumentParser,
    cls: type[T],
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


@functools.cache
def user_agent(client: str = "vault-tools") -> str:
    """Wikimedia/Nominatim-compliant User-Agent.

    Format per the Wikimedia Foundation User-Agent Policy and Nominatim's
    usage policy: ``<client> (<contact>) <library>/<version>``. Version
    segment omitted (policy says "parts that are not applicable can be
    omitted") to avoid drift between a hardcoded constant and the actual
    package version.

    Contact email comes from ``VAULT_CONTACT_EMAIL``; missing env var hard-
    fails via :func:`require_env`. Cached so the env check fires once on
    first call (still after ``--help`` and other no-network paths) instead
    of mid-batch on call N.
    """
    contact = require_env("VAULT_CONTACT_EMAIL")
    return f"{client} (mailto:{contact}) requests/{requests.__version__}"


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


# --- Wikimedia URL helpers ---

# /thumb/ is edge-cached and on a more permissive rate-limit tier than
# full-res — auto-rewrite per Wikimedia's media-reuse guide.
_WIKIMEDIA_HOST = "upload.wikimedia.org"
_WIKIMEDIA_FULL_RES_RE = re.compile(
    r"^/wikipedia/commons/(?P<a>[0-9a-f])/(?P<ab>[0-9a-f]{2})/(?P<file>[^/]+)$",
)
# CDN-blessed widths: 320, 640, 960, 1280, 1920, 3840. Anything else 400s.
WIKIMEDIA_THUMB_WIDTH = 1280


def rewrite_wikimedia_to_thumb(url: str, width: int = WIKIMEDIA_THUMB_WIDTH) -> str:
    """Rewrite full-res ``upload.wikimedia.org`` URLs to ``/thumb/.../{N}px-`` form.

    Pass-through for non-Wikimedia URLs and URLs already on the ``/thumb/``
    path. SVG sources get a ``.png`` suffix on the thumb filename — Wikimedia's
    thumbor renders SVG to PNG, and Pillow can decode the result natively
    (it can't open SVG sources directly anyway).
    """
    parts = urlparse(url)
    if parts.netloc != _WIKIMEDIA_HOST:
        return url
    m = _WIKIMEDIA_FULL_RES_RE.match(parts.path)
    if m is None:
        return url
    file = m["file"]
    thumb_file = f"{width}px-{file}"
    if file.lower().endswith(".svg"):
        thumb_file = f"{thumb_file}.png"
    new_path = f"/wikipedia/commons/thumb/{m['a']}/{m['ab']}/{file}/{thumb_file}"
    return urlunparse(parts._replace(path=new_path))


# --- Frontmatter helpers ---


def fm_str(metadata: dict[str, object], field: str) -> str:
    """Strips YAML quoting artifacts — frontmatter values sometimes retain
    surrounding double-quotes after parsing depending on the quoting style.
    """
    return str(metadata.get(field, "")).strip().strip('"')


_WIKILINK_RE = re.compile(r"^\[\[(?P<target>[^|\]]+)(?:\|(?P<alias>[^\]]+))?\]\]$")


def strip_wikilink(value: str) -> str:
    """Reduce an Obsidian wikilink to its display value.

    ``[[Tokyo]]`` → ``Tokyo``; ``[[Tokyo|TYO]]`` → ``TYO``. Non-wikilink
    input is returned unchanged (modulo surrounding whitespace). Use at
    sites that compose the value into external queries / URLs where the
    raw bracket syntax would corrupt the result.
    """
    m = _WIKILINK_RE.match(value.strip())
    if not m:
        return value.strip()
    alias = m.group("alias")
    target = m.group("target")
    return (alias if alias is not None else target).strip()


def _match_field_line(field: str) -> tuple[str, str]:
    """Return (pattern_with_value, pattern_empty) regexes for a frontmatter field."""
    escaped = re.escape(field)
    return rf"^({escaped}:) .*$", rf"^({escaped}:)\s*$"


def _frontmatter_body(text: str) -> str | None:
    """Return the YAML between the opening and closing ``---`` fences, or None
    when ``text`` has no frontmatter block. Field scans/edits run on this region
    only — a ``key:`` line in the note body must never be mistaken for a field."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS_EXPECTED:
        return None
    return parts[1]


def _edit_frontmatter(text: str, transform: Callable[[str], str]) -> str:
    """Apply ``transform`` to the frontmatter body only and rebuild the document.
    Returns ``text`` unchanged when there's no frontmatter block."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS_EXPECTED:
        return text
    before, body, after = parts
    return f"{before}---{transform(body)}---{after}"


def has_field(text: str, field: str) -> bool:
    """Whether a frontmatter field key is present — scoped to the YAML block, so
    a matching ``key:`` line in the note body is ignored."""
    body = _frontmatter_body(text)
    if body is None:
        return False
    return re.search(rf"^{re.escape(field)}:", body, flags=re.MULTILINE) is not None


def yaml_scalar(value: object) -> str:
    """Format a Python value as a YAML scalar line fragment.

    Bools and ints emit unquoted; strings get double-quoted with embedded
    backslashes and quotes escaped. Empty strings and None emit as ``""``.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not value:
        return '""'
    # Escape backslashes before quotes so a value like ``C:\temp`` or a trailing
    # ``\`` survives the YAML double-quoted scalar round-trip (``\t`` would
    # otherwise read back as a TAB, and a trailing ``\`` would escape the quote).
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def patch_field(text: str, field: str, value: object) -> str:
    """Upsert a frontmatter field. ``value`` is any Python scalar — it's
    formatted via :func:`yaml_scalar` (ints stay bare, strings get quoted).

    Replaces the value if the field exists, otherwise inserts before the
    closing ``---``.
    """
    if not has_field(text, field):
        return insert_before_closing_fence(text, field, value)
    yaml_val = yaml_scalar(value)
    pat_val, pat_empty = _match_field_line(field)
    # Function replacement, not a string: the value is inserted literally so a
    # backslash sequence in it (\1, \d) can't be read as a backref/escape.

    def repl(m: re.Match[str]) -> str:
        return f"{m[1]} {yaml_val}"

    def transform(body: str) -> str:
        new_body = re.sub(pat_val, repl, body, count=1, flags=re.MULTILINE)
        if new_body != body:
            return new_body
        return re.sub(pat_empty, repl, body, count=1, flags=re.MULTILINE)

    # has_field is True, so a frontmatter block exists; edit only that region.
    return _edit_frontmatter(text, transform)


def insert_field_after(
    text: str,
    after_field: str,
    new_field: str,
    value: object,
) -> str:
    """Insert a new frontmatter field after an existing one.

    Preserves the anchor's full line — value and all — by capturing the
    entire line in the regex and re-emitting it before the new field. The
    earlier ``_match_field_line`` patterns are intended for ``patch_field``
    (replace-value semantics) and would erase the anchor's value here.
    """
    yaml_val = yaml_scalar(value)
    escaped = re.escape(after_field)
    pat = rf"^({escaped}:.*)$"
    # Function replacement so a backslash sequence in the anchor line or value
    # is inserted literally rather than expanded (see :func:`patch_field`).

    def repl(m: re.Match[str]) -> str:
        return f"{m[1]}\n{new_field}: {yaml_val}"

    def transform(body: str) -> str:
        return re.sub(pat, repl, body, count=1, flags=re.MULTILINE)

    return _edit_frontmatter(text, transform)


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

    existing = re.search(r"^!\[\[.*\.webp\|600\]\]$", text, flags=re.MULTILINE)
    if existing:
        if existing.group() == embed:
            return text
        return text[: existing.start()] + embed + text[existing.end() :]

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
            except yaml.YAMLError, OSError:
                continue
            if any(t in valid_tags for t in _tags_of(post)):
                files.append((f, post, category, text))
    return files


# --- Display ---


def rel_path(p: Path) -> Path:
    """Vault-relative path for display. Falls back to absolute if outside vault."""
    return p.relative_to(VAULT) if p.is_relative_to(VAULT) else p
