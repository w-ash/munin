"""Audit and update travel option files against the Style Guide.

Usage:
    scripts/vault-tool style_audit Rome27
    scripts/vault-tool style_audit Rome27 --update
    scripts/vault-tool style_audit Rome27 --update --write
    scripts/vault-tool style_audit Rome27 --extract-summaries
    scripts/vault-tool style_audit Rome27 --apply-summaries /tmp/out.txt
    scripts/vault-tool style_audit Rome27 --dir Dining
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import frontmatter

from vault_scripts._utils import (
    GEO_CATEGORIES,
    GEO_FIELDS,
    TRAVEL_DIR,
    add_inline_embed,
    find_entry_files,
    fm_str,
    parse_typed_args,
    rel_path,
)

ALL_CATEGORIES: list[str] = [
    "Dining",
    "Experiences",
    "Destinations",
    "Shopping",
    "Accommodations",
    "Neighborhoods",
]

CATEGORY_TAGS: dict[str, str] = {
    "Dining": "dining-option",
    "Experiences": "experience-option",
    "Destinations": "destination-option",
    "Shopping": "shopping-option",
    "Accommodations": "accommodation-option",
    "Neighborhoods": "neighborhood-option",
}

# Category-specific fields surfaced in --extract-summaries
EXTRACT_FIELDS: dict[str, list[str]] = {
    "Dining": ["name", "type", "cuisine", "vibe", "neighborhood", "destination"],
    "Experiences": ["name", "type", "focus", "vibe", "neighborhood", "destination"],
    "Shopping": ["name", "type", "vibe", "neighborhood", "destination"],
    "Accommodations": ["name", "type", "vibe", "neighborhood", "destination"],
    "Destinations": ["destination", "vibe"],
    "Neighborhoods": ["neighborhood", "energy", "destination"],
}

COVER_MAX_KB = 300
SNIPPET_MAX_CHARS = 200
_FM_PARTS = 3


# --- Checks ---


def check_breadcrumb(text: str, trip_name: str, category: str) -> str | None:
    """Check for [[Trip]] · [[Category]] after frontmatter."""
    expected = f"[[{trip_name}]] · [[{category}]]"
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS:
        return "no frontmatter"
    body = parts[2]
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if expected in stripped:
            return None
        break
    for line in body.split("\n")[:10]:
        if expected in line:
            return None
    return "missing"


def check_summary(text: str) -> str | None:
    """Check for [!summary] callout."""
    return None if "> [!summary]" in text else "missing"


def check_cover_fm(metadata: dict[str, object]) -> str | None:
    """Check that cover: field is non-empty."""
    return None if fm_str(metadata, "cover") else "missing"


def check_cover_file(metadata: dict[str, object], trip_dir: Path) -> str | None:
    """Check that the cover image file exists."""
    cover = fm_str(metadata, "cover")
    if not cover:
        return None
    if (trip_dir / "images" / cover).exists():
        return None
    return f"file not found: {cover}"


def check_cover_embed(text: str, metadata: dict[str, object]) -> str | None:
    """Check for ![[Name.webp|600]] in body when cover is set."""
    cover = fm_str(metadata, "cover")
    if not cover:
        return None
    embed = f"![[{cover}|600]]"
    return None if embed in text else "missing"


def check_cover_size(metadata: dict[str, object], trip_dir: Path) -> str | None:
    """Check that cover image is under 300KB."""
    cover = fm_str(metadata, "cover")
    if not cover:
        return None
    img_path = trip_dir / "images" / cover
    if not img_path.exists():
        return None
    size_kb = img_path.stat().st_size / 1024
    if size_kb < COVER_MAX_KB:
        return None
    return f"{size_kb:.0f}KB (max {COVER_MAX_KB}KB)"


def check_fm_dupes(text: str) -> str | None:
    """Detect duplicate top-level YAML keys via regex."""
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS:
        return None
    keys: list[str] = []
    for line in parts[1].split("\n"):
        m = re.match(r"^([a-z_][a-z_0-9]*):", line)
        if m:
            keys.append(m.group(1))
    seen: set[str] = set()
    dupes: list[str] = []
    for k in keys:
        if k in seen:
            dupes.append(k)
        seen.add(k)
    return f"duplicate keys: {', '.join(dupes)}" if dupes else None


def check_geo_fields(metadata: dict[str, object]) -> str | None:
    """Check all geo fields are present and non-empty."""
    missing = [f for f in GEO_FIELDS if not fm_str(metadata, f)]
    return f"missing: {', '.join(missing)}" if missing else None


# --- Update operations ---


def add_breadcrumb(text: str, trip_name: str, category: str) -> str:
    """Insert [[Trip]] · [[Category]] after frontmatter if not present."""
    if check_breadcrumb(text, trip_name, category) is None:
        return text
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS:
        return text
    expected = f"[[{trip_name}]] · [[{category}]]"
    body = parts[2].lstrip("\n")
    return f"---{parts[1]}---\n\n\n{expected}\n\n{body}"


def add_summary(text: str, summary_text: str, trip_name: str, category: str) -> str:
    """Insert > [!summary] callout after breadcrumb (or after frontmatter)."""
    if "> [!summary]" in text:
        return text
    callout = f"> [!summary]\n> {summary_text}"
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS:
        return text
    lines = parts[2].split("\n")
    breadcrumb = f"[[{trip_name}]] · [[{category}]]"
    insert_idx: int | None = None
    for i, line in enumerate(lines):
        if breadcrumb in line:
            insert_idx = i + 1
            break
    if insert_idx is not None:
        lines.insert(insert_idx, "")
        lines.insert(insert_idx + 1, callout)
    else:
        lines.insert(0, "")
        lines.insert(1, callout)
    return f"---{parts[1]}---" + "\n".join(lines)


# --- Audit mode ---

CHECK_NAMES: tuple[str, ...] = (
    "breadcrumb",
    "summary",
    "cover_fm",
    "cover_file",
    "cover_embed",
    "cover_size",
    "fm_dupes",
    "geo_fields",
)


def run_audit(trip_name: str, categories: list[str]) -> None:
    trip_dir = TRAVEL_DIR / trip_name
    valid_tags = {CATEGORY_TAGS[c] for c in categories}
    files = find_entry_files(trip_dir, categories, valid_tags)

    if not files:
        print("No entry files found.", file=sys.stderr)
        return

    by_category: dict[str, list[tuple[Path, frontmatter.Post, str]]] = {}
    for f, post, cat, text in files:
        by_category.setdefault(cat, []).append((f, post, text))

    all_failures: list[tuple[Path, str, list[tuple[str, str]]]] = []

    for cat in categories:
        cat_files = by_category.get(cat, [])
        if not cat_files:
            continue

        counts: dict[str, int] = {}
        totals: dict[str, int] = {}

        for f, post, text in cat_files:
            meta = post.metadata

            checks: list[tuple[str, str | None]] = [
                ("breadcrumb", check_breadcrumb(text, trip_name, cat)),
                ("summary", check_summary(text)),
                ("cover_fm", check_cover_fm(meta)),
                ("cover_file", check_cover_file(meta, trip_dir)),
                ("cover_embed", check_cover_embed(text, meta)),
                ("cover_size", check_cover_size(meta, trip_dir)),
                ("fm_dupes", check_fm_dupes(text)),
            ]
            if cat in GEO_CATEGORIES:
                checks.append(("geo_fields", check_geo_fields(meta)))

            failures = [(name, msg) for name, msg in checks if msg is not None]
            if failures:
                all_failures.append((f, cat, failures))

            for name, msg in checks:
                totals[name] = totals.get(name, 0) + 1
                if msg is None:
                    counts[name] = counts.get(name, 0) + 1

        print(f"\n=== {cat} ({len(cat_files)} files) ===")
        for name in CHECK_NAMES:
            if name in totals:
                passed = counts.get(name, 0)
                total = totals[name]
                status = "  OK" if passed == total else "FAIL"
                print(f"  {status}  {name}: {passed}/{total}")

    if all_failures:
        print(f"\n--- Failures ({len(all_failures)} files) ---\n")
        for f, _cat, failures in all_failures:
            print(f"{rel_path(f)}:")
            for name, msg in failures:
                print(f"  FAIL {name}: {msg}")
            print()
    else:
        print("\nAll checks passed!")


# --- Update mode ---


def run_update(trip_name: str, categories: list[str], *, write: bool) -> None:
    trip_dir = TRAVEL_DIR / trip_name
    valid_tags = {CATEGORY_TAGS[c] for c in categories}
    files = find_entry_files(trip_dir, categories, valid_tags)

    if not files:
        print("No entry files found.", file=sys.stderr)
        return

    updated = 0
    skipped = 0

    for f, post, cat, original in files:
        new_text = original
        cover = fm_str(post.metadata, "cover")
        if cover and (trip_dir / "images" / cover).exists():
            new_text = add_inline_embed(new_text, cover)
        new_text = add_breadcrumb(new_text, trip_name, cat)

        if new_text != original:
            updated += 1
            if write:
                f.write_text(new_text)
                print(f"  Updated: {rel_path(f)}")
            else:
                print(f"  Would update: {rel_path(f)}")
        else:
            skipped += 1

    verb = "updated" if write else "would be updated"
    print(f"\n{updated} files {verb}, {skipped} already up to date.", file=sys.stderr)
    if not write and updated:
        print("\nDry run. Pass --write to apply.", file=sys.stderr)


# --- Extract summaries mode ---


def _extract_body_snippet(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """Extract first ~2 sentences of prose from body, skipping structure."""
    parts = text.split("---", 2)
    if len(parts) < _FM_PARTS:
        return ""
    prose_lines: list[str] = []
    for line in parts[2].split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("[[") and "]] · [[" in stripped:
            continue
        if stripped.startswith("> [!"):
            continue
        if stripped.startswith("![["):
            continue
        if stripped.startswith("> "):
            prose_lines.append(stripped[2:])
            continue
        prose_lines.append(stripped)
        if len(" ".join(prose_lines)) > max_chars:
            break

    snippet = " ".join(prose_lines)[:max_chars]
    for end in (". ", "! ", "? "):
        idx = snippet.rfind(end)
        if idx > max_chars // 2:
            snippet = snippet[: idx + 1]
            break
    return snippet


def run_extract_summaries(trip_name: str, categories: list[str]) -> None:
    trip_dir = TRAVEL_DIR / trip_name
    valid_tags = {CATEGORY_TAGS[c] for c in categories}
    files = find_entry_files(trip_dir, categories, valid_tags)

    need_summary: list[tuple[Path, frontmatter.Post, str, str]] = []
    for f, post, cat, text in files:
        if check_summary(text) is not None:
            need_summary.append((f, post, cat, text))

    if not need_summary:
        print("All files already have summaries.", file=sys.stderr)
        return

    print(f"# {len(need_summary)} files need summaries\n", file=sys.stderr)

    for f, post, cat, text in need_summary:
        meta = post.metadata
        fields = EXTRACT_FIELDS.get(cat, ["name", "vibe"])
        field_parts = [f"{k}: {fm_str(meta, k)}" for k in fields if fm_str(meta, k)]
        body_snippet = _extract_body_snippet(text)
        rel = f.relative_to(trip_dir)
        print(f"---\nfile: {rel}")
        print(" | ".join(field_parts))
        if body_snippet:
            print(f"body: {body_snippet}")


# --- Apply summaries mode ---


def _parse_summaries(path: Path) -> dict[str, str]:
    """Parse 'filename: summary text' format, one per line."""
    summaries: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.+\.md):\s*(.+)$", line)
        if m:
            summaries[m.group(1)] = m.group(2)
    return summaries


def run_apply_summaries(
    trip_name: str,
    categories: list[str],
    summaries_path: Path,
    *,
    write: bool,
) -> None:
    trip_dir = TRAVEL_DIR / trip_name
    valid_tags = {CATEGORY_TAGS[c] for c in categories}
    files = find_entry_files(trip_dir, categories, valid_tags)

    file_map: dict[str, tuple[Path, str, str]] = {}
    for f, _post, cat, text in files:
        file_map[f.name] = (f, cat, text)

    summaries = _parse_summaries(summaries_path)
    if not summaries:
        print("No summaries found in input file.", file=sys.stderr)
        return

    applied = 0
    skipped = 0
    not_found = 0

    for filename, summary_text in summaries.items():
        if filename not in file_map:
            print(f"  NOT FOUND: {filename}", file=sys.stderr)
            not_found += 1
            continue

        f, cat, text = file_map[filename]

        if "> [!summary]" in text:
            skipped += 1
            continue

        new_text = add_summary(text, summary_text, trip_name, cat)
        applied += 1

        if write:
            f.write_text(new_text)
            print(f"  Applied: {rel_path(f)}")
        else:
            print(f"  Would apply: {rel_path(f)}")

    verb = "applied" if write else "would apply"
    print(
        f"\n{applied} {verb}, {skipped} already had summary, {not_found} not found.",
        file=sys.stderr,
    )
    if not write and applied:
        print("\nDry run. Pass --write to apply.", file=sys.stderr)


# --- CLI ---


class _Args(argparse.Namespace):
    trip: str
    dir: str | None
    update: bool
    write: bool
    extract_summaries: bool
    apply_summaries: str | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit and update travel option files against the Style Guide.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    _ = parser.add_argument(
        "trip", help="Trip folder name under Travel/ (e.g. Rome27)"
    )
    _ = parser.add_argument(
        "--dir", choices=ALL_CATEGORIES, help="Limit to one category"
    )
    _ = parser.add_argument(
        "--update",
        action="store_true",
        help="Apply breadcrumbs and cover embeds (dry-run without --write)",
    )
    _ = parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes to disk (requires --update or --apply-summaries)",
    )
    _ = parser.add_argument(
        "--extract-summaries",
        action="store_true",
        help="Output compact data for LLM summary generation",
    )
    _ = parser.add_argument(
        "--apply-summaries",
        metavar="FILE",
        help="Inject summaries from a file into entries",
    )

    args = parse_typed_args(parser, _Args)

    trip_dir = TRAVEL_DIR / args.trip
    if not trip_dir.exists():
        print(f"Error: Trip '{args.trip}' not found in Travel/", file=sys.stderr)
        sys.exit(1)

    categories = [args.dir] if args.dir else ALL_CATEGORIES

    if args.extract_summaries:
        run_extract_summaries(args.trip, categories)
    elif args.apply_summaries:
        run_apply_summaries(
            args.trip, categories, Path(args.apply_summaries), write=args.write
        )
    elif args.update:
        run_update(args.trip, categories, write=args.write)
    else:
        run_audit(args.trip, categories)


if __name__ == "__main__":
    main()
