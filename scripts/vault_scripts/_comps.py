"""Comparable-sales store and RentCast fetcher for the Homes valuation model.

``Projects/Home Search/Homes/data/comps.csv`` is the shared comps store (canonical-files tier per the
trackers framework): one row per comparable sale, linked to a subject home by a
``subject`` slug. This module reads it (:func:`load_comps`), appends to it with
provenance-based dedupe (:func:`append_comps`), and fetches comps from the free
RentCast API tier (:func:`fetch_comps`).

The CSV is the seam the valuation logic reads, so this fetcher is one writer of
several: hand-entered rows and a buyer's-agent CMA append the same shape with
``source=manual``/``agent``. RentCast comparables are sale *listings*, so their
``price`` is a listing-derived approximation of sale price (``source=rentcast``);
confirmed recorded sales come from ``agent``/``county`` rows.

Reads use ``csv.reader`` (typed ``list[str]`` rows) and writes use
``csv.writerows`` (returns ``None``), so no stdlib ``Any`` enters the type graph.
"""

from __future__ import annotations

import csv
from pathlib import Path
import re

from vault_scripts._retry import google_retry, request_validated_json
from vault_scripts._types import Comp, RentCastValueResponse

COMPS_REL = "Projects/Home Search/Homes/data/comps.csv"

# The comps store schema, in column order. A shared store, so provenance
# (``source`` + ``source_id``) rides on every row and imports dedupe on it.
COMPS_COLUMNS: tuple[str, ...] = (
    "subject",
    "address",
    "sale_price",
    "sale_date",
    "beds",
    "baths",
    "sqft",
    "lot_sqft",
    "year_built",
    "dist_mi",
    "garage",
    "adu",
    "condition",
    "source",
    "source_id",
)

RENTCAST_BASE = "https://api.rentcast.io/v1"
_TIMEOUT_S = 20
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def subject_slug(path: Path) -> str:
    """Derive a comp-store subject slug from a home note filename.

    ``Projects/Home Search/Homes/entries/2117 Grant St.md`` → ``2117-grant-st``. The slug is the join
    key between a subject home and its comp rows."""
    return _SLUG_RE.sub("-", path.stem.lower()).strip("-")


# --- value parsing ---


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _as_int(value: str) -> int | None:
    f = _as_float(value)
    return int(f) if f is not None else None


def _fmt(value: float | int | None) -> str:
    """Format a numeric cell: blank for None, integer floats without a ``.0``."""
    if value is None:
        return ""
    f = float(value)
    return str(int(f)) if f.is_integer() else repr(f)


# --- CSV store ---


def _read_rows(path: Path) -> list[dict[str, str]]:
    """Read the comps CSV into per-row column dicts. Missing file or empty file
    yields no rows; short rows pad with empty strings."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        table = list(csv.reader(f))
    if not table:
        return []
    header = table[0]
    return [
        {col: (row[i] if i < len(row) else "") for i, col in enumerate(header)}
        for row in table[1:]
    ]


def _comp_from_row(row: dict[str, str]) -> Comp:
    return Comp(
        subject=row.get("subject", ""),
        address=row.get("address", ""),
        sale_price=_as_float(row.get("sale_price", "")),
        sale_date=row.get("sale_date", ""),
        beds=_as_float(row.get("beds", "")),
        baths=_as_float(row.get("baths", "")),
        sqft=_as_float(row.get("sqft", "")),
        lot_sqft=_as_float(row.get("lot_sqft", "")),
        year_built=_as_int(row.get("year_built", "")),
        dist_mi=_as_float(row.get("dist_mi", "")),
        garage=_as_int(row.get("garage", "")),
        adu=_as_int(row.get("adu", "")),
        condition=_as_int(row.get("condition", "")),
        source=row.get("source", ""),
        source_id=row.get("source_id", ""),
    )


def _row_from_comp(comp: Comp) -> list[str]:
    return [
        comp.subject,
        comp.address,
        _fmt(comp.sale_price),
        comp.sale_date,
        _fmt(comp.beds),
        _fmt(comp.baths),
        _fmt(comp.sqft),
        _fmt(comp.lot_sqft),
        _fmt(comp.year_built),
        _fmt(comp.dist_mi),
        _fmt(comp.garage),
        _fmt(comp.adu),
        _fmt(comp.condition),
        comp.source,
        comp.source_id,
    ]


def load_all_comps(path: Path) -> list[Comp]:
    """Every comp row in the store."""
    return [_comp_from_row(row) for row in _read_rows(path)]


def load_comps(subject: str, path: Path) -> list[Comp]:
    """The comps for one subject home, matched by slug."""
    return [c for c in load_all_comps(path) if c.subject == subject]


def _write_all(path: Path, comps: list[Comp]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows([list(COMPS_COLUMNS), *(_row_from_comp(c) for c in comps)])


def append_comps(new: list[Comp], path: Path) -> tuple[int, int]:
    """Append comps to the store, skipping rows that duplicate an existing
    ``(subject, source, source_id)``. Returns ``(added, skipped_duplicates)``.
    Rewrites the whole file (small store), creating it with a header if absent."""
    existing = load_all_comps(path)
    seen = {(c.subject, c.source, c.source_id) for c in existing}
    added: list[Comp] = []
    for comp in new:
        key = (comp.subject, comp.source, comp.source_id)
        if key in seen:
            continue
        seen.add(key)
        added.append(comp)
    if added:
        _write_all(path, [*existing, *added])
    return len(added), len(new) - len(added)


# --- RentCast fetcher ---


def _trim_date(value: str) -> str:
    """RentCast dates are ISO timestamps; keep the ``YYYY-MM-DD`` head."""
    return value[:10]


@google_retry
def _fetch_value(
    address: str, api_key: str, comp_count: int
) -> RentCastValueResponse:
    """Call RentCast ``GET /avm/value`` for a subject address; returns the typed
    response (estimate + comparables). ``google_retry`` is a generic 429/5xx
    backoff policy, reused here for RentCast."""
    return request_validated_json(
        "GET",
        f"{RENTCAST_BASE}/avm/value",
        response_model=RentCastValueResponse,
        timeout=_TIMEOUT_S,
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        params={"address": address, "compCount": str(comp_count)},
    )


def fetch_comps(
    address: str, api_key: str, subject: str, comp_count: int
) -> list[Comp]:
    """Fetch comparables for a subject address from RentCast and map them into
    store rows tagged with ``subject``. RentCast comparables are listings, so
    ``sale_price`` is their listed ``price`` and ``sale_date`` is the best of
    ``removedDate``/``lastSeenDate``/``listedDate``; garage/adu/condition are left
    blank (not provided) for later hand-rating."""
    response = _fetch_value(address, api_key, comp_count)
    comps: list[Comp] = []
    for comparable in response.comparables:
        sale_date = comparable.removedDate or comparable.lastSeenDate or comparable.listedDate
        comps.append(
            Comp(
                subject=subject,
                address=comparable.formattedAddress,
                sale_price=comparable.price,
                sale_date=_trim_date(sale_date),
                beds=comparable.bedrooms,
                baths=comparable.bathrooms,
                sqft=comparable.squareFootage,
                lot_sqft=comparable.lotSize,
                year_built=comparable.yearBuilt,
                dist_mi=(
                    round(comparable.distance, 3)
                    if comparable.distance is not None
                    else None
                ),
                garage=None,
                adu=None,
                condition=None,
                source="rentcast",
                source_id=comparable.id,
            )
        )
    return comps
