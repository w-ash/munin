"""Shared types: Pydantic models for API responses, TypedDicts for
internal dict shapes, dataclasses for config.

Design split:
- **Pydantic** — external data at the boundary (API responses). Catches
  schema drift at runtime.
- **TypedDict** — dict shapes we produce internally. Typed access, no runtime cost.
- **@dataclass** — config and intermediate structures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, RootModel

# --- Pydantic models: external API responses ---


class _ExtraIgnore(BaseModel):
    """Base with tolerant parsing — APIs evolve, we ignore unknown keys."""
    model_config = ConfigDict(extra="ignore")


class PlacesLocation(_ExtraIgnore):
    latitude: float
    longitude: float


class PlacesAddressComponent(_ExtraIgnore):
    shortText: str = ""
    types: list[str] = []


class PlacesDisplayName(_ExtraIgnore):
    text: str = ""
    languageCode: str = ""


class PlacesHours(_ExtraIgnore):
    weekdayDescriptions: list[str] = []


class PlacesPlace(_ExtraIgnore):
    """One entry from places:searchText or places:searchNearby."""
    id: str = ""
    formattedAddress: str = ""
    location: PlacesLocation | None = None
    addressComponents: list[PlacesAddressComponent] = []
    displayName: PlacesDisplayName | None = None
    types: list[str] = []
    primaryType: str = ""
    googleMapsUri: str = ""
    websiteUri: str = ""
    businessStatus: str = ""
    rating: float | None = None
    userRatingCount: int | None = None
    priceLevel: str = ""
    regularOpeningHours: PlacesHours | None = None


class PlacesResponse(_ExtraIgnore):
    places: list[PlacesPlace] = []


class RoutesRoute(_ExtraIgnore):
    duration: str = ""
    distanceMeters: int = 0


class RoutesResponse(_ExtraIgnore):
    routes: list[RoutesRoute] = []


class OverpassElement(_ExtraIgnore):
    tags: dict[str, str] = {}


class OverpassResponse(_ExtraIgnore):
    elements: list[OverpassElement] = []


class NominatimResult(_ExtraIgnore):
    lat: str
    lon: str
    display_name: str = ""


class NominatimResponse(RootModel[list[NominatimResult]]):
    """Nominatim returns a JSON array, not an envelope object."""


# --- TypedDicts: internal dict shapes ---

GapReason = Literal["missing", "empty", "non_latin", "refresh", "malformed"]
Confidence = Literal["high", "medium", "low"]
Source = Literal["google-places", "nominatim"]


class StationInfo(TypedDict):
    """All four fields always present; values may be None when a given
    lookup failed (OSM had no line tags, Routes API errored, etc.).

    ``station_lines_fetched`` distinguishes "Overpass confirmed empty"
    (True + None) from "we never asked Overpass or it was unreachable"
    (False + None). Refresh mode preserves existing values on False so
    transient Overpass 504s don't clear hand-entered data.
    """
    nearest_station: str
    walk_time_to_station: int | None
    station_lines: str | None
    station_lines_fetched: bool


class Enrichment(TypedDict):
    """All fields always populated (empty strings / None when absent)."""
    website: str
    hours: str
    closed: str
    primary_type: str
    business_status: str
    rating: float | None
    rating_count: int | None
    price_level: str


class _GeoResultBase(TypedDict):
    coordinates: str
    address: str
    address_local: str
    google_maps_url: str
    place_id: str
    confidence: Confidence
    candidates: int
    source: Source


class GeoResult(_GeoResultBase, total=False):
    """Base fields always present; ``enrichment`` only when ``--enrich``,
    ``station`` only when ``--stations``. ``url_validation_failed`` is set
    when the URL pipeline refused to emit a ``google_maps_url`` — closed
    venue per ``businessStatus`` or no Places match (Nominatim fallback) —
    so callers can surface the issue to the user instead of silently
    dropping the field.
    """
    enrichment: Enrichment
    station: StationInfo
    url_validation_failed: str


# --- Config dataclasses ---

@dataclass(frozen=True, slots=True)
class GeocodeOptions:
    """Knobs for a geocoding call. Defaults match the cheapest SKU path.

    Station filling splits into two dimensions, each controlled independently
    so the slow Overpass path can be opted into separately from the fast
    Google path:

    - ``stations`` — Google only: ``nearest_station`` + ``walk_time_to_station``.
      Fast and stable.
    - ``lines`` — Overpass/OSM only: ``station_lines``. Slow (1.1s throttle,
      frequent 504s) and optional. Requires either ``stations=True`` or a
      pre-existing ``nearest_station`` anchor.
    """
    enrich: bool = False
    need_local: bool = True
    stations: bool = False
    lines: bool = False
    # If set, anchor station lookups to this existing name (geocode it and
    # compute walk/lines from its coords) instead of running Places Nearby.
    # Prevents mismatched data when the file already has a nearest_station.
    existing_station_name: str | None = None


@dataclass(slots=True)
class Station:
    """Candidate station from Places Nearby."""
    name: str
    lat: float
    lng: float
    types: list[str] = field(default_factory=list)


VenueOutcomeKind = Literal["no_gaps", "not_found", "no_new_data", "updated"]


@dataclass(slots=True)
class VenueOutcome:
    """Result of running the per-venue geocode pipeline on one file."""
    path: Path
    gaps: dict[str, GapReason]
    kind: VenueOutcomeKind
    query: str = ""
    result: GeoResult | None = None
    updates: dict[str, object] = field(default_factory=dict)
    # Distinguishes "updates computed, file written" from "updates computed,
    # write=False (dry-run)". Callers need both states to render correctly.
    written: bool = False
