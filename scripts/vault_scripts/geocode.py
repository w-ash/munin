"""Geocode travel venue files in the Obsidian vault.

Usage:
    scripts/vault-tool geocode lookup "Pantheon Rome"
    scripts/vault-tool geocode lookup --file "Travel/Rome27/Dining/entries/Trattoria Da Enzo.md" --write
    scripts/vault-tool geocode lookup --file ... --write --enrich
    scripts/vault-tool geocode lookup --file ... --write --stations
    scripts/vault-tool geocode batch Rome27                # dry-run
    scripts/vault-tool geocode batch Rome27 --write        # apply
    scripts/vault-tool geocode batch Rome27 --write --dir Dining
    scripts/vault-tool geocode batch Rome27 --write --stations
    scripts/vault-tool geocode batch Rome27 --write --lines         # Overpass pass
    scripts/vault-tool geocode batch Rome27 --write --stations --lines
    scripts/vault-tool geocode batch Rome27 --write --refresh-urls   # rewrite malformed URLs

Tiers:
    Default      → Essentials SKU (10k free/month): coordinates, address, maps URL
    --enrich     → Pro SKU (5k free/month): + website, opening hours
    --stations   → Places Nearby (5k free/month) + Routes (10k free/month):
                   fills nearest_station + walk_time_to_station. Fast, stable.
    --lines      → Overpass/OSM (free, ~1s throttle, flaky): fills station_lines
                   only. Slow; runs as a separate pass. Can combine with
                   --stations, or run alone when nearest_station is already set.
    --refresh-urls → Re-classify any google_maps_url that isn't a CID URL
                     (`https://maps.google.com/?cid=<n>`) as a gap, so the
                     Places API rewrites it. CID is the form Google's own
                     Share button generates and the only shape the iOS
                     Google Maps app handles reliably. Closed venues /
                     Nominatim-only matches are surfaced as URL skips at
                     the end of the run.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys
import time
import unicodedata

import frontmatter
from pydantic import BaseModel
import requests

from vault_scripts._retry import (
    APIError,
    OverpassUnavailableError,
    google_retry,
    overpass_retry,
    request_validated_json,
)
from vault_scripts._types import (
    Enrichment,
    GapReason,
    GeocodeOptions,
    GeoResult,
    NominatimResponse,
    OverpassResponse,
    PlacesPlace,
    PlacesResponse,
    RoutesResponse,
    Station,
    StationInfo,
    VenueOutcome,
)
from vault_scripts._utils import (
    GEO_CATEGORIES,
    GEO_FIELDS,
    TRAVEL_DIR,
    find_entry_files,
    fm_str,
    format_coords,
    insert_before_closing_fence,
    insert_field_after,
    parse_coords,
    parse_typed_args,
    patch_field,
    rel_path,
    require_env,
    resolve_file_arg,
    strip_wikilink,
    user_agent,
    yaml_scalar,
)

VENUE_TAGS: frozenset[str] = frozenset({
    "dining-option",
    "experience-option",
    "shopping-option",
    "accommodation-option",
})
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
OVERPASS_MIRRORS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OVERPASS_TIMEOUT_S = 60
OVERPASS_MIN_INTERVAL_S = 1.1
STATION_TYPES: list[str] = ["subway_station", "train_station", "light_rail_station"]
# Places Nearby uses rankPreference=DISTANCE + maxResultCount=1, so widening
# the radius doesn't pick a farther station over a closer one; it only
# catches genuinely-remote venues where no station sits within a shorter
# walk. 2000m ≈ 25 min walk, wide enough to cover station-sparse
# neighborhoods (e.g., Murasakino in north Kyoto, where the nearest
# Karasuma-line station is ~1.5km away).
STATION_RADIUS_M = 2000
NON_LATIN_THRESHOLD = 0.4
GOOGLE_TIMEOUT_S = 10
# Addresses shorter than this are probably business names, not street addresses
ADDRESS_MIN_LEN = 10
GOOGLE_STATION_FIELDS: tuple[str, ...] = ("nearest_station", "walk_time_to_station")
OVERPASS_STATION_FIELDS: tuple[str, ...] = ("station_lines",)
STATION_FIELDS: tuple[str, ...] = GOOGLE_STATION_FIELDS + OVERPASS_STATION_FIELDS

# Coord-bucketed caches coalesce lookups for venues that share a station.
# Null values mean "confirmed absent from OSM" and are cached; "all mirrors
# failed" results aren't cached so a later retry can succeed.
_STATION_LINES_CACHE: dict[tuple[float, float, str], str | None] = {}
_NEAREST_STATION_CACHE: dict[tuple[float, float], Station | None] = {}
# Geocoded coords for named stations (case-folded key). Populated when we
# anchor to a pre-existing nearest_station field.
_STATION_BY_NAME_CACHE: dict[str, tuple[float, float] | None] = {}
# Stations must be within this many decimal degrees of the venue for us to
# trust a name-based geocode match. ~5km at Tokyo latitude.
STATION_NAME_MAX_DEG = 0.05
# Tracks the last Overpass request time across the run, so the fair-use
# throttle only blocks when we actually made a prior call.
_overpass_last_request: float = 0.0

# Country code (from Google response) → language for address_local
COUNTRY_LANG: dict[str, str] = {
    "JP": "ja",
    "CN": "zh",
    "TW": "zh-TW",
    "KR": "ko",
    "TH": "th",
    "IT": "it",
    "FR": "fr",
    "ES": "es",
    "DE": "de",
    "PT": "pt",
    "GR": "el",
    "TR": "tr",
    "VN": "vi",
    "ID": "id",
    "MX": "es",
}


def has_non_latin_text(text: str) -> bool:
    """True when text is predominantly non-Latin-script (CJK, Cyrillic,
    Greek, Arabic, Thai, etc.) and should be treated as needing romanization.

    Uses a 40% non-ASCII threshold rather than any-match because Google's
    romanized results often include small amounts of native script for
    untranslatable building/street names (e.g. "2-chome−24 須藤ビル" or
    "Avenida Café-Filho 12"). Diacritics alone (French/Spanish/German/
    Portuguese accents) stay well below the threshold, so Latin-script
    addresses with a few accented characters aren't misflagged.
    """
    if not text:
        return False
    non_ascii = sum(1 for c in text if not c.isascii())
    return non_ascii / len(text) > NON_LATIN_THRESHOLD


# --- HTTP helpers ---


@google_retry
def _google_post[M: BaseModel](
    url: str,
    body: dict[str, object],
    field_mask: str,
    *,
    response_model: type[M],
) -> M:
    """POST to a Google Maps Platform endpoint. Retries transient failures."""
    return request_validated_json(
        "POST",
        url,
        response_model=response_model,
        json=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": require_env("GOOGLE_MAPS_API_KEY"),
            "X-Goog-FieldMask": field_mask,
        },
        timeout=GOOGLE_TIMEOUT_S,
    )


@google_retry
def _nominatim_get[M: BaseModel](
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
    *,
    response_model: type[M],
) -> M:
    """GET Nominatim (OSM) with tenacity retries."""
    return request_validated_json(
        "GET",
        url,
        response_model=response_model,
        params=params,
        headers=headers,
        timeout=GOOGLE_TIMEOUT_S,
    )


def _is_json_response(resp: requests.Response) -> bool:
    return "json" in resp.headers.get("Content-Type", "")


@overpass_retry
def _overpass_post[M: BaseModel](
    url: str,
    query: str,
    *,
    response_model: type[M],
) -> M:
    """POST a single Overpass QL query with tenacity retries. HTML-in-200
    responses (OSM3S "server busy" pages) raise ``OverpassBusyError`` so
    the retry decorator backs off."""
    return request_validated_json(
        "POST",
        url,
        response_model=response_model,
        data={"data": query},
        headers={"User-Agent": user_agent()},
        timeout=OVERPASS_TIMEOUT_S,
        ok=_is_json_response,
    )


def _overpass_wait() -> None:
    """Enforce fair-use throttle against the actual last-call time, so the
    first call of a run doesn't pay a 1.1s tax for no reason."""
    global _overpass_last_request  # noqa: PLW0603 (module-scope throttle timestamp)
    elapsed = time.monotonic() - _overpass_last_request
    if elapsed < OVERPASS_MIN_INTERVAL_S:
        time.sleep(OVERPASS_MIN_INTERVAL_S - elapsed)
    _overpass_last_request = time.monotonic()


# --- Places API (New): text search ---

FIELDS_ESSENTIALS = (
    "places.id,places.formattedAddress,places.displayName,"
    "places.location,places.addressComponents,"
    "places.googleMapsUri,places.businessStatus,places.types"
)
# Only the fields the enrichment actually persists (website + hours/closed).
# rating/userRatingCount/priceLevel/primaryType are billable Atmosphere-tier
# fields that nothing writes, so requesting them just paid for discarded data.
FIELDS_ENRICHED = (
    FIELDS_ESSENTIALS + ",places.websiteUri,places.regularOpeningHours"
)


def places_search(
    query: str,
    *,
    lang: str = "en",
    enrich: bool = False,
) -> tuple[PlacesPlace, int] | None:
    """Calls Places API (New) REST endpoint directly: the ``googlemaps``
    Python package only supports the legacy Places API which Google is
    deprecating. FieldMask is mandatory; omitting it returns an error.

    Default uses Essentials SKU only (10k free/month). ``enrich=True``
    adds Pro-tier fields (website, opening hours) the enrichment persists.

    Returns (top hit, total candidate count) or None.
    """
    try:
        response = _google_post(
            PLACES_SEARCH_URL,
            body={"textQuery": query, "languageCode": lang},
            field_mask=FIELDS_ENRICHED if enrich else FIELDS_ESSENTIALS,
            response_model=PlacesResponse,
        )
    except APIError as e:
        print(f"  Places API error: {e}", file=sys.stderr)
        return None

    if not response.places:
        return None
    top = response.places[0]
    if top.location is None:
        return None
    return top, len(response.places)


def detect_country_code(place: PlacesPlace) -> str | None:
    """Extracts country code to auto-detect the local language for ``address_local``."""
    for component in place.addressComponents:
        if "country" in component.types:
            return component.shortText
    return None


def is_malformed_maps_url(url: str) -> bool:
    """A URL needs ``--refresh-urls`` when it's not the CID form Google ships
    via its Share button and returns from the Places API's ``googleMapsUri``.

    CID is the Google Business Profile identifier: the most permanent
    anchor (survives owner / address / name changes) and the only shape
    the iOS Google Maps app handles reliably. Both the legacy
    ``?q=place_id:<id>`` form and the briefly-used ``query_place_id=<id>``
    form fail on iOS, so we flag everything except ``cid=`` for refresh.
    """
    return bool(url) and "cid=" not in url


def validate_for_url(place: PlacesPlace) -> str | None:
    """Return None when it's safe to write ``place.googleMapsUri`` as the
    venue's URL, or a human-readable refusal reason. Refusal cases:

    - ``place.businessStatus`` is ``CLOSED_PERMANENTLY`` / ``CLOSED_TEMPORARILY``
    - Google matched but returned an empty ``googleMapsUri``

    Surfaced to the user so they can delete the entry or refile; silently
    writing a URL for a closed venue was the complaint that drove this
    pipeline change. A Nominatim fallback is *not* a refusal: it geocoded
    fine, just without a Google URL, and its low ``confidence``/``source``
    already say so.
    """
    name = place.displayName.text if place.displayName else ""
    address = place.formattedAddress
    if place.businessStatus == "CLOSED_PERMANENTLY":
        return (
            f"Venue is permanently closed per Google Places. Matched: '{name}' "
            f"at {address}. Delete this entry or refile with the current open "
            f"location."
        )
    if place.businessStatus == "CLOSED_TEMPORARILY":
        return (
            f"Venue is temporarily closed per Google Places. Matched: '{name}' "
            f"at {address}. Confirm reopening or refile with more context."
        )
    if not place.googleMapsUri:
        return (
            f"Google matched '{name}' at {address} but returned no Maps URL. "
            f"Set google_maps_url manually or refile with more context."
        )
    return None


def format_hours(descriptions: list[str]) -> tuple[str, str]:
    """Converts Places API weekdayDescriptions into ``hours`` and ``closed`` strings."""
    if not descriptions:
        return "", ""
    closed_days = [d.split(":")[0] for d in descriptions if "Closed" in d]
    return "; ".join(descriptions), ", ".join(closed_days)


def _enrichment_from(place: PlacesPlace) -> Enrichment:
    hours, closed = format_hours(
        place.regularOpeningHours.weekdayDescriptions
        if place.regularOpeningHours
        else []
    )
    return Enrichment(website=place.websiteUri, hours=hours, closed=closed)


def geocode_google(query: str, options: GeocodeOptions) -> GeoResult | None:
    """Two API calls: one for English, one for the local script (auto-detected
    from country code via ``COUNTRY_LANG``). Pass ``need_local=False`` when
    only coordinates/URL are needed; each call costs money.
    """
    en = places_search(query, lang="en", enrich=options.enrich)
    if en is None:
        return None
    place_en, candidates = en
    assert place_en.location is not None  # places_search guarantees this  # noqa: S101

    lat = round(place_en.location.latitude, 4)
    lng = round(place_en.location.longitude, 4)

    address_local = ""
    if options.need_local:
        country_code = detect_country_code(place_en)
        local_lang = COUNTRY_LANG.get(country_code, "") if country_code else ""
        if local_lang:
            local = places_search(query, lang=local_lang, enrich=False)
            if local is not None:
                address_local = local[0].formattedAddress

    result: GeoResult = {
        "coordinates": format_coords(lat, lng),
        "address": place_en.formattedAddress,
        "address_local": address_local,
        "google_maps_url": place_en.googleMapsUri,
        "place_id": place_en.id,
        "confidence": "high" if candidates == 1 else "medium",
        "candidates": candidates,
        "source": "google-places",
    }

    refusal = validate_for_url(place_en)
    if refusal is not None:
        result["url_validation_failed"] = refusal
        result["google_maps_url"] = ""

    if options.enrich:
        result["enrichment"] = _enrichment_from(place_en)

    return result


def geocode_nominatim(query: str) -> GeoResult | None:
    """Free fallback (no API key needed). Can't provide ``address_local`` or
    ``place_id``; only useful for coordinates and a rough address.
    Nominatim's usage policy requires max 1 req/sec and a User-Agent.
    """
    try:
        response = _nominatim_get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": "3"},
            headers={"User-Agent": user_agent()},
            response_model=NominatimResponse,
        )
    except APIError as e:
        print(f"  Nominatim error: {e}", file=sys.stderr)
        return None

    if not response.root:
        return None
    top = response.root[0]
    lat = round(float(top.lat), 4)
    lng = round(float(top.lon), 4)

    return {
        "coordinates": format_coords(lat, lng),
        "address": top.display_name,
        "address_local": "",
        "google_maps_url": "",
        "place_id": "",
        "confidence": "low",
        "candidates": len(response.root),
        "source": "nominatim",
    }


def geocode(query: str, options: GeocodeOptions | None = None) -> GeoResult | None:
    """Google Places → Nominatim fallback chain. The 1.1s sleep before
    Nominatim is required by their usage policy (max 1 req/sec).

    When ``options.stations`` or ``options.lines`` is True and Google
    geocoding succeeded (coords known), also attaches station info under
    ``result["station"]``: ``stations`` drives the Google name+walk
    lookup, ``lines`` drives the Overpass transit-lines lookup.
    """
    opts = options or GeocodeOptions()
    result = geocode_google(query, opts)
    if result is None:
        print("  Places miss, trying Nominatim...", end="", file=sys.stderr)
        time.sleep(1.1)
        result = geocode_nominatim(query)
        if result is None:
            return None

    coords = (
        parse_coords(result["coordinates"])
        if (opts.stations or opts.lines) and result.get("coordinates")
        else None
    )
    if coords is not None:
        station_info = get_station_info(
            coords[0],
            coords[1],
            anchor_name=opts.existing_station_name,
            fetch_walk=opts.stations,
            fetch_lines=opts.lines,
        )
        if station_info is not None:
            result["station"] = station_info
    return result


# --- Station lookup ---


def find_nearest_station(lat: float, lng: float) -> Station | None:
    """Calls Places API (New) Nearby Search for the single closest transit
    station. Returns a :class:`Station` or None.

    Station types covered: subway, heavy rail, light rail. Trailing
    " Station" is stripped from the display name to match our convention.

    Results are cached by coord bucket (~11m precision) so venues on the
    same block don't each re-query.
    """
    cache_key = (round(lat, 4), round(lng, 4))
    if cache_key in _NEAREST_STATION_CACHE:
        return _NEAREST_STATION_CACHE[cache_key]

    try:
        response = _google_post(
            PLACES_NEARBY_URL,
            body={
                "includedTypes": STATION_TYPES,
                "maxResultCount": 1,
                "rankPreference": "DISTANCE",
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": float(STATION_RADIUS_M),
                    },
                },
            },
            field_mask=(
                "places.displayName,places.location,places.types,places.primaryType"
            ),
            response_model=PlacesResponse,
        )
    except APIError as e:
        print(f"  Nearby error: {e}", file=sys.stderr)
        return None

    if not response.places:
        return None
    top = response.places[0]
    name = (top.displayName.text if top.displayName else "").strip()
    name = _canonicalize_station_name(name)
    if not name or top.location is None:
        return None
    station = Station(
        name=name,
        lat=top.location.latitude,
        lng=top.location.longitude,
        types=top.types,
    )
    _NEAREST_STATION_CACHE[cache_key] = station
    return station


def walk_duration_minutes(
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
) -> int | None:
    """Calls Routes API ``computeRoutes`` with travelMode=WALK.

    Returns walking duration in minutes (ceiling so we don't understate).
    Google's walking route follows the street network, not a straight-line
    estimate.
    """
    try:
        response = _google_post(
            ROUTES_URL,
            body={
                "origin": {
                    "location": {
                        "latLng": {"latitude": from_lat, "longitude": from_lng}
                    }
                },
                "destination": {
                    "location": {"latLng": {"latitude": to_lat, "longitude": to_lng}}
                },
                "travelMode": "WALK",
                "units": "METRIC",
            },
            field_mask="routes.duration,routes.distanceMeters",
            response_model=RoutesResponse,
        )
    except APIError as e:
        print(f"  Routes error: {e}", file=sys.stderr)
        return None

    if not response.routes:
        return None
    # Routes serializes duration as a protobuf Duration string, which may carry
    # fractional seconds (e.g. "512.5s"); accept them so a valid route isn't
    # silently dropped.
    m = re.match(r"(\d+(?:\.\d+)?)s$", response.routes[0].duration)
    if not m:
        return None
    seconds = float(m.group(1))
    return max(1, math.ceil(seconds / 60))


def _overpass_query(query: str) -> list[dict[str, str]]:
    """Execute an Overpass QL query with mirror fallback. Tenacity retries
    each mirror internally (see ``overpass_retry``); this function switches
    to the next mirror when all retries are exhausted.

    Returns the ``tags`` dicts of all matching elements (empty list when the
    query succeeded but had no matches; callers can cache that as
    "confirmed empty"). Raises :class:`OverpassUnavailableError` if every
    mirror failed; distinct from empty so callers don't treat transient
    outages as authoritative "no data".
    """
    errors: list[str] = []
    for url in OVERPASS_MIRRORS:
        _overpass_wait()
        try:
            response = _overpass_post(url, query, response_model=OverpassResponse)
        except APIError as e:
            host = url.split("/")[2]
            errors.append(f"{host}: {e}")
            print(f"  Overpass {host}: {e}", file=sys.stderr)
            continue
        return [e.tags for e in response.elements]
    raise OverpassUnavailableError("; ".join(errors) or "no mirrors configured")


def fetch_station_lines(
    lat: float,
    lng: float,
    anchor_name: str | None = None,
) -> str | None:
    """Queries Overpass (OSM) for transit line/operator info at station coords.

    Google Places returns station types but never line/operator names. OSM
    stations carry ``network``/``operator``/``line`` tags with variable
    coverage by region (best where local mappers are active). Aggregates
    across all station nodes within a small radius (large interchange
    stations have one OSM node per platform/line).

    When ``anchor_name`` is given, only aggregates from OSM nodes whose
    ``name`` matches the anchor (accent/case-insensitive). Prevents mixing
    tags from adjacent stations that share coords (e.g. two lines meeting
    above/below ground at the same intersection).

    Raises :class:`OverpassUnavailableError` if every mirror failed; don't
    cache so a later retry can succeed, and refresh-mode callers must
    preserve existing values instead of clearing them. A cached/returned
    ``None`` means "OSM confirmed no Latin-script line/network data".
    """
    cache_key = (round(lat, 4), round(lng, 4), anchor_name or "")
    if cache_key in _STATION_LINES_CACHE:
        return _STATION_LINES_CACHE[cache_key]

    query = (
        f"[out:json][timeout:25];"
        f'node(around:150,{lat},{lng})[railway~"^(station|halt)$"];'
        f"out tags;"
    )

    tags_list = _overpass_query(query)
    if not tags_list:
        _STATION_LINES_CACHE[cache_key] = None
        return None

    # When anchored to a specific station name, filter out neighboring
    # stations so we don't mix in their lines (e.g. Yoyogi-kōen + Yoyogi-
    # Hachiman are 200m apart but serve different operators).
    if anchor_name:
        anchor_norm = _normalize_station_name(anchor_name)
        tags_list = [
            t
            for t in tags_list
            if any(
                _normalize_station_name(t.get(k, "")) == anchor_norm
                for k in ("name:en", "name")
            )
        ]
        if not tags_list:
            _STATION_LINES_CACHE[cache_key] = None
            return None

    # Prefer `line` (most specific, e.g. "Toei Oedo Line") over `network`
    # (broader system, e.g. "Toei subway") or `operator` (the authority).
    # Skip predominantly non-Latin values: they don't match the vault's
    # romanized convention and forcing the user to translate is worse than
    # leaving empty. The `:en` suffix prefers English tags when present.
    line_keys = ("line:en", "line", "network:en", "network", "operator:en", "operator")
    collected: list[str] = []
    seen: set[str] = set()

    for tags in tags_list:
        for key in line_keys:
            v = tags.get(key, "").strip()
            if not v or has_non_latin_text(v):
                continue
            for raw in v.split(";"):
                p = re.sub(
                    r"\s+lines?\s*$", "", raw.strip(), flags=re.IGNORECASE
                ).strip()
                if p and p not in seen:
                    seen.add(p)
                    collected.append(p)
            break

    result = ", ".join(collected) if collected else None
    _STATION_LINES_CACHE[cache_key] = result
    return result


def _canonicalize_station_name(name: str) -> str:
    """Strip trailing annotations Google adds to station displayNames.

    Removes parenthetical context ("(Nijo-jo Castle)"), quoted aliases
    ("'Harajuku'", curly or straight), and the "Station"/"Sta."/"Sta"
    suffix, iteratively, since names may stack all three (e.g.
    "Meiji-jingumae 'Harajuku' Sta."). The result is the core station
    name suitable for storing in frontmatter.
    """
    prev = ""
    while name != prev:
        prev = name
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
        name = re.sub(
            r"\s*[\u2018\u2019'\"][^\u2018\u2019'\"]+[\u2018\u2019'\"]\s*$",
            "",
            name,
        )
        name = re.sub(r"\s+sta\.?$|\s+station$", "", name, flags=re.IGNORECASE)
        name = name.strip()
    return name


def _normalize_station_name(s: str) -> str:
    """Case-fold + strip diacritics, punctuation, and the word 'station'.

    Strips parenthetical context Google adds to some displayNames
    (e.g. "Nijojo-mae Sta.(Nijo-jo Castle)") and expands the "Sta." /
    "Sta" abbreviation to "station" before the suffix removal.

    Also collapses Hepburn m-before-m/b/p to n (Gaiemmae → Gaienmae,
    Shimbashi → Shinbashi); Google and OSM disagree on this Japanese
    romanization variant. The transform is applied universally (not
    gated on country) because it's symmetry-preserving for matching:
    we apply it to both sides of every comparison, so even on names
    where the rule is technically wrong ("Campbell" → "canpbell"), both
    the Google and OSM forms get the same transformation and the
    equality check still holds.
    """
    # Drop parenthetical annotations and expand "Sta."/"Sta" abbreviations
    # before the suffix strip, so "Nijojo-mae Sta.(Nijo-jo Castle)" and the
    # plain "Nijojo-mae" anchor normalize to the same token.
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\bsta\.?\b", "station", s, flags=re.IGNORECASE)

    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )
    out = (
        stripped
        .casefold()
        .replace("station", "")
        .replace("-", "")
        .replace(" ", "")
        .replace("'", "")
        .replace(".", "")
        .strip()
    )
    return re.sub(r"m(?=[mpb])", "n", out)


def _geocode_station_by_name(
    name: str, near_lat: float, near_lng: float
) -> tuple[float, float] | None:
    """Geocode a station by name. Returns (lat, lng) or None.

    Verifies the returned place's display name matches ``name`` (accent/
    case/punctuation-insensitive) and that it's within
    ``STATION_NAME_MAX_DEG`` of the venue. Rejects near-miss matches
    (e.g. "Yoyogi-kōen" geocoding to nearby "Yoyogi-Hachiman") because
    they'd corrupt the downstream walk/lines lookups.

    Cached by case-folded name.
    """
    key = name.casefold().strip()
    if key in _STATION_BY_NAME_CACHE:
        return _STATION_BY_NAME_CACHE[key]

    hit = places_search(f"{name} Station", lang="en")
    if hit is None:
        _STATION_BY_NAME_CACHE[key] = None
        return None
    place, _candidates = hit
    if place.location is None or place.displayName is None:
        _STATION_BY_NAME_CACHE[key] = None
        return None

    lat, lng = place.location.latitude, place.location.longitude
    if (
        abs(lat - near_lat) > STATION_NAME_MAX_DEG
        or abs(lng - near_lng) > STATION_NAME_MAX_DEG
    ):
        _STATION_BY_NAME_CACHE[key] = None
        return None

    if _normalize_station_name(place.displayName.text) != _normalize_station_name(name):
        _STATION_BY_NAME_CACHE[key] = None
        return None

    coords = (lat, lng)
    _STATION_BY_NAME_CACHE[key] = coords
    return coords


def get_station_info(
    lat: float,
    lng: float,
    *,
    anchor_name: str | None,
    fetch_walk: bool,
    fetch_lines: bool,
) -> StationInfo | None:
    """Returns station info for a venue. Either ``fetch_walk`` or
    ``fetch_lines`` (or both) must be True; otherwise returns None.

    When ``anchor_name`` is given (file already has ``nearest_station`` set),
    geocode *that* station by name and compute walk/lines from its coords;
    preserves the pre-populated name authoritatively. If the anchor can't
    be geocoded near the venue, returns None rather than risk mismatched
    data from a different nearby station.

    Otherwise finds the nearest transit station via Places Nearby.

    ``station_lines_fetched`` is True only when Overpass actually delivered
    an answer (which may itself be None, meaning OSM confirmed no English
    data). False when ``fetch_lines`` is False or when every Overpass mirror
    failed; refresh-mode callers preserve existing values on False.
    """
    if not (fetch_walk or fetch_lines):
        return None
    # Lines-only on a file with no anchor can't run: we'd do a full Google
    # Nearby search only to discard its result (nearest_station isn't in
    # gaps). Caller should re-run with --stations to set the anchor first.
    if fetch_lines and not fetch_walk and not anchor_name:
        return None

    if anchor_name:
        coords = _geocode_station_by_name(anchor_name, lat, lng)
        if coords is None:
            return None
        station_lat, station_lng = coords
        name = anchor_name
    else:
        station = find_nearest_station(lat, lng)
        if station is None:
            return None
        name, station_lat, station_lng = station.name, station.lat, station.lng

    walk = (
        walk_duration_minutes(lat, lng, station_lat, station_lng)
        if fetch_walk
        else None
    )

    lines: str | None = None
    lines_fetched = False
    if fetch_lines:
        try:
            lines = fetch_station_lines(station_lat, station_lng, name)
            lines_fetched = True
        except OverpassUnavailableError as e:
            print(f"  Overpass unavailable for {name}: {e}", file=sys.stderr)

    return StationInfo(
        nearest_station=name,
        walk_time_to_station=walk,
        station_lines=lines,
        station_lines_fetched=lines_fetched,
    )


# --- Query construction ---


def build_query(metadata: dict[str, object]) -> str:
    """Prefers ``name`` + ``locality`` + ``address`` in that order, so the
    Places API returns the *business* result rather than the building or
    address. Address-led searches return the address's own place_id, which
    is anchored to the building, not to the establishment inside.

    Checks both ``destination`` (travel files) and ``city`` (restaurant files).
    A precise ``address`` pins the spot well enough that ``neighborhood`` adds
    only noise, so neighborhood is stacked in as context only when no usable
    address is present. Wikilink-typed fields (``destination``, ``neighborhood``)
    are reduced to their display value before composition; raw ``[[Tokyo]]`` in
    the query string makes Places return zero results.
    """
    name = fm_str(metadata, "name") or fm_str(metadata, "name_jp")
    neighborhood = strip_wikilink(fm_str(metadata, "neighborhood"))
    locality = strip_wikilink(fm_str(metadata, "destination")) or fm_str(
        metadata, "city"
    )
    address = fm_str(metadata, "address")
    precise_address = bool(address) and len(address) > ADDRESS_MIN_LEN

    def stack(*candidates: str) -> str:
        """Comma-join non-empty candidates, dropping any that a kept part
        already contains (so 'Tokyo' isn't repeated after 'Tokyo Station')."""
        kept: list[str] = []
        for c in candidates:
            if c and all(c.lower() not in k.lower() for k in kept):
                kept.append(c)
        return ", ".join(kept)

    if name:
        if precise_address:
            return stack(name, locality, address)
        return stack(name, neighborhood, locality)
    if address:
        return stack(address, locality)
    return stack(neighborhood, locality)


# --- Frontmatter I/O ---

# Anchor chains: when inserting a new field, try these existing fields in
# order. The first one present becomes the insertion anchor; if none exist,
# the field appends before the closing ---. Coordinates falls back to
# prepending before google_maps_url or address (geo fields cluster together).
FIELD_ANCHORS: dict[str, list[str]] = {
    "address_local": ["address"],
    "nearest_station": ["neighborhood", "name_jp", "name"],
    "walk_time_to_station": ["nearest_station", "neighborhood", "name_jp", "name"],
    "station_lines": [
        "walk_time_to_station",
        "nearest_station",
        "neighborhood",
        "name_jp",
        "name",
    ],
}


def apply_geo_updates(text: str, updates: dict[str, object]) -> str:
    """Apply geo/station/enrichment updates to frontmatter, preserving
    existing values and ordering. Processes fields in canonical order so
    insertions chain correctly (address_local after address even if address
    was just added).

    Falls back to inserting before the closing ``---`` when no anchor
    fields exist.
    """
    field_order = [
        "coordinates",
        "google_maps_url",
        "address",
        "address_local",
        "nearest_station",
        "walk_time_to_station",
        "station_lines",
        "website",
        "hours",
        "closed",
    ]

    def _has_value(k: str, v: object) -> bool:
        # walk_time: 0 is a legitimate value (direct station connection);
        # "" is a refresh-mode clear signal. Same for station_lines: "" clears.
        if k in {"walk_time_to_station", "station_lines"}:
            return v is not None
        return bool(v)

    ordered = [
        (f, updates[f])
        for f in field_order
        if f in updates and _has_value(f, updates[f])
    ]

    for field_name, value in ordered:
        if re.search(rf"^{re.escape(field_name)}:", text, re.MULTILINE):
            text = patch_field(text, field_name, value)
            continue

        anchored = False
        for anchor in FIELD_ANCHORS.get(field_name, ()):
            if re.search(rf"^{re.escape(anchor)}:", text, re.MULTILINE):
                text = insert_field_after(text, anchor, field_name, value)
                anchored = True
                break
        if anchored:
            continue

        # coordinates prefers to land just before google_maps_url or address
        if field_name == "coordinates":
            placed = False
            # Bind the scalar as a default arg so the value is inserted
            # literally, never re-read as a backref (see patch_field).
            coord_scalar = yaml_scalar(value)
            for anchor in ("google_maps_url", "address"):
                if re.search(rf"^{re.escape(anchor)}:", text, re.MULTILINE):
                    text = re.sub(
                        rf"^({re.escape(anchor)}:)",
                        lambda m, v=coord_scalar: f"coordinates: {v}\n{m[1]}",
                        text,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    placed = True
                    break
            if not placed:
                text = insert_before_closing_fence(text, field_name, value)
        else:
            text = insert_before_closing_fence(text, field_name, value)

    return text


# --- Gap detection and update building ---


def detect_gaps(
    metadata: dict[str, object],
    *,
    include_stations: bool = False,
    include_lines: bool = False,
    refresh_stations: bool = False,
    refresh_urls: bool = False,
) -> dict[str, GapReason]:
    """Detect which geo fields need filling. Returns {field: reason}.

    When ``include_stations`` is True, also checks ``nearest_station`` and
    ``walk_time_to_station`` (Google path: fast). When ``include_lines``
    is True, checks ``station_lines`` (Overpass path: slow, optional).
    ``refresh_stations`` forces populated station fields into the gaps
    (behind the matching include flag) so `build_geo_updates` will
    overwrite with anchor-aware fresh lookups. ``nearest_station`` is
    never refreshed: it's the anchor. ``refresh_urls`` re-classifies
    any non-CID ``google_maps_url`` values as gaps so they get rewritten
    to the CID form Google's API returns.
    """
    gaps: dict[str, GapReason] = {}
    if not fm_str(metadata, "address_local"):
        gaps["address_local"] = "missing"
    url = fm_str(metadata, "google_maps_url")
    if not url:
        gaps["google_maps_url"] = "empty"
    elif refresh_urls and is_malformed_maps_url(url):
        gaps["google_maps_url"] = "malformed"
    if "coordinates" not in metadata or not fm_str(metadata, "coordinates"):
        gaps["coordinates"] = "missing"
    address = fm_str(metadata, "address")
    if not address:
        gaps["address"] = "empty"
    elif has_non_latin_text(address):
        gaps["address"] = "non_latin"

    if include_stations:
        if not fm_str(metadata, "nearest_station"):
            gaps["nearest_station"] = "missing"
        walk = metadata.get("walk_time_to_station")
        if walk is None or (isinstance(walk, str) and not walk.strip()):
            gaps["walk_time_to_station"] = "missing"
        elif refresh_stations:
            gaps["walk_time_to_station"] = "refresh"
    if include_lines:
        if not fm_str(metadata, "station_lines"):
            gaps["station_lines"] = "missing"
        elif refresh_stations:
            gaps["station_lines"] = "refresh"
    return gaps


def build_geo_updates(
    metadata: dict[str, object],
    result: GeoResult,
    gaps: dict[str, GapReason],
) -> dict[str, object]:
    """Never overwrites existing populated values; only fills gaps. When
    the existing ``address`` is predominantly non-Latin script
    (``non_latin``), replaces it with the API's romanized version and
    moves the original to ``address_local`` (preferring the API's
    local-language result when available, since the original may be a
    mix of scripts).
    """
    updates: dict[str, object] = {}

    if "coordinates" in gaps and result.get("coordinates"):
        updates["coordinates"] = result["coordinates"]
    if "google_maps_url" in gaps and result.get("google_maps_url"):
        updates["google_maps_url"] = result["google_maps_url"]

    if gaps.get("address") in {"empty", "non_latin"} and result.get("address"):
        updates["address"] = result["address"]

    if gaps.get("address") == "non_latin":
        # Replacing a non-Latin address: prefer API's local-language
        # result over the old (possibly mixed-script) text.
        updates["address_local"] = result.get("address_local") or fm_str(
            metadata, "address"
        )
    elif "address_local" in gaps and result.get("address_local"):
        updates["address_local"] = result["address_local"]

    # Enrichment fields: only fill empty frontmatter, never overwrite
    enrichment = result.get("enrichment")
    if enrichment:
        if enrichment.get("website") and not fm_str(metadata, "website"):
            updates["website"] = enrichment["website"]
        if enrichment.get("hours") and not fm_str(metadata, "hours"):
            updates["hours"] = enrichment["hours"]
        if enrichment.get("closed") and not fm_str(metadata, "closed"):
            updates["closed"] = enrichment["closed"]

    # Station fields. Missing gaps skip on null; "refresh" overwrites even
    # with empty (clears stale data). walk_time accepts 0 (direct connection).
    station = result.get("station")
    if station:
        if station["nearest_station"] and "nearest_station" in gaps:
            updates["nearest_station"] = station["nearest_station"]
        walk_reason = gaps.get("walk_time_to_station")
        walk = station["walk_time_to_station"]
        if walk_reason == "refresh":
            updates["walk_time_to_station"] = walk if walk is not None else ""
        elif walk_reason and walk is not None:
            updates["walk_time_to_station"] = walk
        # Only write station_lines when Overpass actually answered; on
        # mirror exhaustion we preserve existing data rather than clear it.
        lines_reason = gaps.get("station_lines")
        lines = station["station_lines"]
        if station["station_lines_fetched"]:
            if lines_reason == "refresh":
                updates["station_lines"] = lines or ""
            elif lines_reason and lines:
                updates["station_lines"] = lines

    return updates


# --- Per-venue primitive ---


def process_venue(
    path: Path,
    post: frontmatter.Post,
    text: str,
    gaps: dict[str, GapReason],
    *,
    enrich: bool,
    stations: bool,
    lines: bool,
    write: bool,
) -> VenueOutcome:
    """Per-venue pipeline: geocode, build updates, optionally write.

    Takes ``gaps`` pre-computed so callers can share the cheap detection
    step (e.g. batch dry-run summary) without firing API calls, and so
    phase-gating (``want_stations``/``want_lines``) and ``need_local``
    derivation have a single authoritative site.
    """
    if not gaps:
        return VenueOutcome(path=path, gaps=gaps, kind="no_gaps")

    need_local = "address_local" in gaps or gaps.get("address") == "non_latin"
    want_stations = stations and any(k in gaps for k in GOOGLE_STATION_FIELDS)
    want_lines = lines and any(k in gaps for k in OVERPASS_STATION_FIELDS)
    existing_station = fm_str(post.metadata, "nearest_station")

    opts = GeocodeOptions(
        enrich=enrich,
        need_local=need_local,
        stations=want_stations,
        lines=want_lines,
        existing_station_name=existing_station or None,
    )
    query = build_query(post.metadata)
    result = geocode(query, opts)
    if result is None:
        return VenueOutcome(path=path, gaps=gaps, kind="not_found", query=query)

    updates = build_geo_updates(post.metadata, result, gaps)
    if not updates:
        return VenueOutcome(
            path=path,
            gaps=gaps,
            kind="no_new_data",
            query=query,
            result=result,
        )

    written = False
    if write:
        path.write_text(apply_geo_updates(text, updates), encoding="utf-8")
        written = True

    return VenueOutcome(
        path=path,
        gaps=gaps,
        kind="updated",
        query=query,
        result=result,
        updates=updates,
        written=written,
    )


# --- Subcommands ---


class _Args(argparse.Namespace):
    command: str
    # lookup
    query: list[str]
    file: str | None
    # batch
    trip: str
    only_missing: str | None
    dir: str | None
    # shared
    write: bool
    enrich: bool
    stations: bool
    lines: bool
    refresh_stations: bool
    refresh_urls: bool


def cmd_lookup(args: _Args) -> None:
    """Single venue geocode lookup.

    Two modes:
    - ``--file <path>``: n=1 case of the batch pipeline; shares phase
      gating and ``need_local`` derivation with :func:`cmd_batch` via
      :func:`process_venue`. With ``--write``, updates the file in-place.
    - Raw query string (no ``--file``): debug-style one-off geocode call.
      No gaps, no gating, no writes: just "show me what Google returns".
    """
    if args.file is not None:
        _lookup_file(args)
    else:
        _lookup_raw_query(" ".join(args.query), args)


def _lookup_file(args: _Args) -> None:
    assert args.file is not None  # noqa: S101 (dispatcher guarantees this)
    file_path = resolve_file_arg(args.file)
    text = file_path.read_text(encoding="utf-8")
    post = frontmatter.loads(text)
    query = build_query(post.metadata)
    print(f"Querying: {query}", file=sys.stderr)

    gaps = detect_gaps(
        post.metadata,
        include_stations=args.stations,
        include_lines=args.lines,
        refresh_stations=args.refresh_stations,
        refresh_urls=args.refresh_urls,
    )
    outcome = process_venue(
        file_path,
        post,
        text,
        gaps,
        enrich=args.enrich,
        stations=args.stations,
        lines=args.lines,
        write=args.write,
    )
    _render_lookup_outcome(outcome, fallback_query=query)


def _print_ok_json(query: str, result: GeoResult | None) -> None:
    """Print the shared "status ok" JSON envelope for lookup output."""
    output: dict[str, object] = {"status": "ok", "query": query}
    if result is not None:
        output.update(result)
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _lookup_raw_query(query: str, args: _Args) -> None:
    print(f"Querying: {query}", file=sys.stderr)
    opts = GeocodeOptions(
        enrich=args.enrich,
        stations=args.stations,
        lines=args.lines,
    )
    result = geocode(query, opts)
    if result is None:
        print(
            json.dumps({"status": "not_found", "query": query, "error": "No results"})
        )
        return
    _print_ok_json(query, result)


def _render_lookup_outcome(outcome: VenueOutcome, *, fallback_query: str) -> None:
    """Render a VenueOutcome as JSON output for ``cmd_lookup --file``."""
    query = outcome.query or fallback_query

    if outcome.kind == "no_gaps":
        print("All geo fields already populated, nothing to fetch.", file=sys.stderr)
        print(json.dumps({"status": "no_gaps", "path": str(rel_path(outcome.path))}))
        return
    if outcome.kind == "not_found":
        print(
            json.dumps({"status": "not_found", "query": query, "error": "No results"})
        )
        return
    if outcome.kind == "no_new_data":
        print(
            "All requested fields already populated, nothing to update.",
            file=sys.stderr,
        )
    elif outcome.kind == "updated" and outcome.written:
        print(
            f"Updated {rel_path(outcome.path)}: {', '.join(outcome.updates.keys())}",
            file=sys.stderr,
        )
    elif outcome.kind == "updated":
        print(
            f"Would update {rel_path(outcome.path)}: {', '.join(outcome.updates.keys())}"
            " (use --write to apply)",
            file=sys.stderr,
        )

    _render_url_skip(outcome)
    _print_ok_json(query, outcome.result)


def _url_skip_reason(outcome: VenueOutcome) -> str:
    """The URL-pipeline refusal reason for a venue, or '' when it emitted a URL.

    Suppressed when ``google_maps_url`` wasn't a gap: a closed-venue refusal is
    raised on every geocode, but if the file already has a URL we never touched
    it, so the "delete this entry" warning would be a false alarm.
    """
    if "google_maps_url" not in outcome.gaps:
        return ""
    return (outcome.result or {}).get("url_validation_failed", "")


def _render_url_skip(outcome: VenueOutcome) -> None:
    """Stderr warning when the URL pipeline refused to emit a google_maps_url."""
    reason = _url_skip_reason(outcome)
    if not reason:
        return
    print(
        f"\n⚠  google_maps_url SKIPPED for {rel_path(outcome.path)}\n"
        f"   reason: {reason}\n"
        f"   action: delete this entry, or refile with updated address/name context\n",
        file=sys.stderr,
    )


def cmd_batch(args: _Args) -> None:
    """Batch geocode travel venue files."""
    trip_dir = TRAVEL_DIR / args.trip
    if not trip_dir.exists():
        available = (
            sorted(
                d.name
                for d in TRAVEL_DIR.iterdir()
                if d.is_dir() and any((d / cat).exists() for cat in GEO_CATEGORIES)
            )
            if TRAVEL_DIR.exists()
            else []
        )
        print(f"Error: Trip '{args.trip}' not found in Travel/", file=sys.stderr)
        if available:
            print(f"Available trips: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    scope: list[str] | frozenset[str] = [args.dir] if args.dir else GEO_CATEGORIES
    venue_files = find_entry_files(trip_dir, scope, set(VENUE_TAGS))

    if not venue_files:
        print("No venue files found.", file=sys.stderr)
        return

    file_gaps: list[tuple[Path, frontmatter.Post, str, dict[str, GapReason]]] = []
    gap_counts: dict[str, int] = {}

    for f, post, _category, text in venue_files:
        gaps = detect_gaps(
            post.metadata,
            include_stations=args.stations,
            include_lines=args.lines,
            refresh_stations=args.refresh_stations,
            refresh_urls=args.refresh_urls,
        )
        if args.only_missing:
            # pyright widens the comprehension's value type to str; re-annotate
            # to preserve GapReason invariance for downstream callers.
            gaps: dict[str, GapReason] = {
                k: v for k, v in gaps.items() if k == args.only_missing
            }
        if gaps:
            file_gaps.append((f, post, text, gaps))
            for field_name in gaps:
                gap_counts[field_name] = gap_counts.get(field_name, 0) + 1

    print(
        f"\nScanned {len(venue_files)} venue files in Travel/{args.trip}/",
        file=sys.stderr,
    )
    if not file_gaps:
        print("All geo fields are populated!", file=sys.stderr)
        return

    print(f"Found {len(file_gaps)} files with gaps:", file=sys.stderr)
    for field, count in sorted(gap_counts.items()):
        print(f"  {field}: {count}", file=sys.stderr)

    if not args.write:
        print("\nDry run. Use --write to apply changes.", file=sys.stderr)
        print("\nFiles that need updates:", file=sys.stderr)
        for f, _post, _text, gaps in file_gaps:
            gap_desc = ", ".join(f"{k} ({v})" for k, v in gaps.items())
            print(f"  {rel_path(f)}: {gap_desc}", file=sys.stderr)
        return

    errors: list[dict[str, str]] = []
    url_skips: list[tuple[Path, str]] = []
    updated = 0
    skipped = 0

    for i, (f, post, text, gaps) in enumerate(file_gaps, 1):
        name = fm_str(post.metadata, "name") or f.stem
        locality = fm_str(post.metadata, "destination") or fm_str(post.metadata, "city")
        print(
            f"  [{i:3d}/{len(file_gaps)}] {name} ({locality}) ", end="", file=sys.stderr
        )

        outcome = process_venue(
            f,
            post,
            text,
            gaps,
            enrich=args.enrich,
            stations=args.stations,
            lines=args.lines,
            write=args.write,
        )

        if outcome.kind == "not_found":
            print("NOT FOUND", file=sys.stderr)
            errors.append({
                "file": str(rel_path(f)),
                "query": outcome.query,
                "error": "No results",
            })
            skipped += 1
        elif outcome.kind == "updated":
            result = outcome.result
            conf = result.get("confidence", "?") if result else "?"
            src = result.get("source", "?") if result else "?"
            print(
                f"OK ({src}, {conf}) [{', '.join(outcome.updates.keys())}]",
                file=sys.stderr,
            )
            updated += 1
        else:  # no_new_data (no_gaps can't occur: pre-filtered)
            print("SKIP (no new data)", file=sys.stderr)
            skipped += 1

        url_skip_reason = _url_skip_reason(outcome)
        if url_skip_reason:
            url_skips.append((f, url_skip_reason))

    print(f"\nDone: {updated} updated, {skipped} skipped", file=sys.stderr)

    if url_skips:
        print(
            f"\nURL skips ({len(url_skips)}); files needing manual review:",
            file=sys.stderr,
        )
        for path, reason in url_skips:
            print(f"  - {rel_path(path)}\n      {reason}", file=sys.stderr)

    if errors:
        error_path = Path(__file__).resolve().parent / "geocode_errors.json"
        error_path.write_text(json.dumps(errors, ensure_ascii=False, indent=2))
        print(f"Errors logged to: {error_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Geocode travel venue files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    lookup_parser = subparsers.add_parser("lookup", help="Geocode a single query")
    _ = lookup_parser.add_argument(
        "query", nargs="*", help="Search query (e.g. 'Pantheon Rome')"
    )
    _ = lookup_parser.add_argument(
        "--file", help="Read query from a venue file's frontmatter"
    )
    _ = lookup_parser.add_argument(
        "--write",
        action="store_true",
        help="Write results back to the file (requires --file)",
    )
    _ = lookup_parser.add_argument(
        "--enrich",
        action="store_true",
        help="Pull website + opening hours (Pro SKU, 5k free/month)",
    )
    _ = lookup_parser.add_argument(
        "--stations",
        action="store_true",
        help="Fill nearest_station + walk_time_to_station via Google (fast)",
    )
    _ = lookup_parser.add_argument(
        "--lines",
        action="store_true",
        help="Fill station_lines via Overpass/OSM (slow, ~1s/call). Combine with --stations, or run alone when nearest_station is already set",
    )
    _ = lookup_parser.add_argument(
        "--refresh-stations",
        action="store_true",
        help="Force-overwrite walk_time_to_station and station_lines even when already set (nearest_station is preserved as the anchor)",
    )
    _ = lookup_parser.add_argument(
        "--refresh-urls",
        action="store_true",
        help="Re-classify any google_maps_url that isn't a CID URL (https://maps.google.com/?cid=...) as a gap, so it gets rewritten to the form Google's API returns.",
    )

    batch_parser = subparsers.add_parser("batch", help="Batch geocode venue files")
    _ = batch_parser.add_argument(
        "trip", help="Trip folder name under Travel/ (e.g. Rome27)"
    )
    _ = batch_parser.add_argument(
        "--write", action="store_true", help="Apply changes (default is dry-run)"
    )
    _ = batch_parser.add_argument(
        "--enrich",
        action="store_true",
        help="Pull website + opening hours (Pro SKU, 5k free/month)",
    )
    _ = batch_parser.add_argument(
        "--stations",
        action="store_true",
        help="Fill nearest_station + walk_time_to_station via Google (fast)",
    )
    _ = batch_parser.add_argument(
        "--lines",
        action="store_true",
        help="Fill station_lines via Overpass/OSM (slow, ~1s/call). Combine with --stations, or run alone when nearest_station is already set",
    )
    _ = batch_parser.add_argument(
        "--refresh-stations",
        action="store_true",
        help="Force-overwrite walk_time_to_station and station_lines even when already set",
    )
    _ = batch_parser.add_argument(
        "--refresh-urls",
        action="store_true",
        help="Re-classify any google_maps_url that isn't a CID URL (https://maps.google.com/?cid=...) as a gap, so it gets rewritten to the form Google's API returns.",
    )
    _ = batch_parser.add_argument(
        "--only-missing",
        choices=list(GEO_FIELDS) + list(STATION_FIELDS),
        help="Only fill this specific field",
    )
    _ = batch_parser.add_argument(
        "--dir", choices=sorted(GEO_CATEGORIES), help="Limit to one category directory"
    )

    args = parse_typed_args(parser, _Args)
    if args.command == "lookup":
        if not args.query and not args.file:
            lookup_parser.error("Provide a query string or --file")
        cmd_lookup(args)
    elif args.command == "batch":
        cmd_batch(args)


if __name__ == "__main__":
    main()
