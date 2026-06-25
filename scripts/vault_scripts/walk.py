"""Compute walking time between two or more locations.

Uses Google's Routes API with travelMode=WALK — actual street-network walk,
not straight-line distance. Same SKU as ``geocode``'s ``walk_time_to_station``
pipeline (10k free/month). Reuses ``geocode``'s Places search to resolve
free-text queries.

Each location argument resolves in this order:

1. ``"lat, lng"`` coordinate string → used directly.
2. Path to an existing ``.md`` file (relative to the vault root or absolute) →
   read ``coordinates:`` from the file's frontmatter.
3. Anything else → geocoded via Google Places (free-text query).

Examples:

    # Hotel ↔ filed dining option
    scripts/vault-tool walk \\
      "Travel/Japan26/Accommodations/entries/BnA Alter Museum.md" \\
      "Travel/Japan26/Dining/entries/cité.md"

    # Hotel ↔ several free-text candidates
    scripts/vault-tool walk \\
      "Travel/Japan26/Accommodations/entries/BnA Alter Museum.md" \\
      "Blue Bottle Coffee Kyoto Kiyamachi" \\
      "% Arabica Fujii Daimaru Kyoto" \\
      "Goodman Roaster Kyoto"

    # Pure coordinates → free-text
    scripts/vault-tool walk "35.0045, 135.7688" "Goodman Roaster Kyoto"
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
import sys

import frontmatter
import yaml

from vault_scripts._utils import (
    VAULT,
    has_field,
    insert_field_after,
    parse_typed_args,
    patch_field,
)
from vault_scripts.geocode import GeocodeOptions, geocode, walk_duration_minutes

COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
MIN_LOCATIONS = 2
DEFAULT_ANCHOR_FIELD = "walk_time_to_station"
ROUTES_MAX_WORKERS = 10


def _write_walk_field(
    path: Path,
    field: str,
    minutes: int,
    anchor: str,
) -> str:
    """Upsert ``field: <minutes>`` into ``path``'s frontmatter, positioning
    it right after ``anchor`` whenever the anchor exists.

    Strips any existing instance of the field first, so re-running with a
    different anchor (or after a prior run that appended at the end) cleanly
    repositions the line instead of leaving duplicates. Falls back to
    appending before the closing fence when the anchor isn't present.
    Returns a short status string.
    """
    text = path.read_text(encoding="utf-8")
    # Drop any existing instance first so a re-run repositions cleanly instead
    # of leaving duplicates (``\n?`` tolerates a field on the file's last line).
    stripped = re.sub(
        rf"^{re.escape(field)}:[^\n]*\n?",
        "",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if anchor != field and has_field(stripped, anchor):
        new_text = insert_field_after(stripped, anchor, field, minutes)
        op = f"after {anchor}"
    else:
        new_text = patch_field(stripped, field, minutes)
        op = "set"
    if new_text == text:
        return "no change"
    path.write_text(new_text, encoding="utf-8")
    return op


@dataclass(frozen=True, slots=True)
class Resolved:
    label: str
    lat: float
    lng: float
    source: str
    path: Path | None = None


def _coords_from_string(s: str) -> tuple[float, float] | None:
    m = COORD_RE.match(s)
    if m is None:
        return None
    return float(m.group(1)), float(m.group(2))


def _resolve_file(path: Path) -> Resolved | None:
    """Read ``coordinates:`` and ``name:`` from a markdown file's frontmatter."""
    try:
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        print(f"  Could not read {path}: {e}", file=sys.stderr)
        return None
    coords_raw = post.metadata.get("coordinates")
    if not isinstance(coords_raw, str) or not coords_raw.strip():
        print(f"  {path}: no `coordinates:` in frontmatter", file=sys.stderr)
        return None
    parsed = _coords_from_string(coords_raw)
    if parsed is None:
        print(f"  {path}: malformed coordinates {coords_raw!r}", file=sys.stderr)
        return None
    name_raw = post.metadata.get("name")
    label = name_raw if isinstance(name_raw, str) and name_raw else path.stem
    return Resolved(
        label=label,
        lat=parsed[0],
        lng=parsed[1],
        source=f"file:{path.name}",
        path=path,
    )


def resolve_location(arg: str) -> Resolved | None:
    """Coords → file → geocode, in that order."""
    coords = _coords_from_string(arg)
    if coords is not None:
        return Resolved(label=arg, lat=coords[0], lng=coords[1], source="coords")

    candidate = Path(arg)
    if not candidate.is_absolute():
        candidate = VAULT / arg
    if candidate.is_file() and candidate.suffix == ".md":
        return _resolve_file(candidate)

    result = geocode(arg, options=GeocodeOptions(need_local=False))
    if result is None:
        return None
    parsed = _coords_from_string(result["coordinates"])
    if parsed is None:
        return None
    return Resolved(
        label=arg,
        lat=parsed[0],
        lng=parsed[1],
        source=f"geocode:{result['confidence']}",
    )


class _Args(argparse.Namespace):
    locations: list[str]
    write_field: str | None
    anchor_after: str


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute walking time between two or more locations via Google Routes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    _ = parser.add_argument(
        "locations",
        nargs="+",
        help="Two or more locations: vault file path, 'lat, lng', or free-text query.",
    )
    _ = parser.add_argument(
        "--write-field",
        metavar="FIELD",
        default=None,
        help=(
            "Write the walking minutes back to each destination file's frontmatter "
            "under this field name (e.g. walk_time_to_bna_alter). Only destinations "
            "resolved from .md files are written; coords/free-text destinations are "
            "printed but skipped."
        ),
    )
    _ = parser.add_argument(
        "--anchor-after",
        metavar="FIELD",
        default=DEFAULT_ANCHOR_FIELD,
        help=(
            "When --write-field inserts a NEW field, position it directly after this "
            f"existing frontmatter field (default: {DEFAULT_ANCHOR_FIELD}). If the "
            "anchor isn't present, the new field is appended before the closing "
            "fence. Updates to existing fields stay in place regardless."
        ),
    )
    args = parse_typed_args(parser, _Args)
    if len(args.locations) < MIN_LOCATIONS:
        parser.error("Provide at least two locations (from + to)")

    resolved: list[Resolved] = []
    for loc in args.locations:
        r = resolve_location(loc)
        if r is None:
            print(f"Could not resolve location: {loc}", file=sys.stderr)
            sys.exit(1)
        resolved.append(r)

    origin = resolved[0]
    print(f"From: {origin.label}  ({origin.lat}, {origin.lng})  [{origin.source}]")
    if args.write_field is not None:
        print(f"Writing field: {args.write_field}")
    print()

    destinations = resolved[1:]
    workers = min(ROUTES_MAX_WORKERS, max(1, len(destinations)))

    def route_to(dest: Resolved) -> int | None:
        return walk_duration_minutes(origin.lat, origin.lng, dest.lat, dest.lng)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        durations = list(pool.map(route_to, destinations))

    rows: list[tuple[str, str, str, str, str]] = []
    for dest, mins in zip(destinations, durations, strict=True):
        time_str = f"{mins} min" if mins is not None else "routes-failed"
        write_note = ""
        if args.write_field is not None and mins is not None and dest.path is not None:
            try:
                op = _write_walk_field(
                    dest.path,
                    args.write_field,
                    mins,
                    args.anchor_after,
                )
            except OSError as e:
                write_note = f" (write-failed: {e})"
            else:
                write_note = f" ✓ {op}" if op != "no change" else " (no change)"
        rows.append((
            dest.label,
            f"{dest.lat}, {dest.lng}",
            time_str,
            dest.source,
            write_note,
        ))

    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    w2 = max(len(r[2]) for r in rows)
    for label, coords, time_str, source, write_note in rows:
        print(
            f"  {label.ljust(w0)}  {coords.ljust(w1)}  "
            f"{time_str.rjust(w2)}  [{source}]{write_note}",
        )


if __name__ == "__main__":
    main()
