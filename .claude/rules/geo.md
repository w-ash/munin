---
description: How to find and set geo-location fields on travel and restaurant files
paths:
  - "Travel/**"
  - "Restaurants/**"
---

# Geo-Location

All travel venue and restaurant files should have these geo fields:

```yaml
coordinates: "51.5136, -0.1365"   # "lat, lng" decimal degrees
google_maps_url: ""
address: ""                        # romanized
address_local: ""                  # native script (show to taxi, match signage)
```

`address_local` is only relevant for non-English-speaking destinations.

Travel venue files (not local restaurants) also have three station fields:

```yaml
nearest_station: "Baker Street"      # station name only
walk_time_to_station: 2               # integer minutes (real walking route)
station_lines: "Bakerloo, Jubilee"    # optional, comma-separated
```

## How to fill fields

Use `geocode` via the script dispatcher. It only fills missing/empty fields — never overwrites.

```bash
# Single file (after creating a venue/restaurant note)
scripts/vault-tool geocode lookup --file "path/to/file.md" --write

# Batch across a trip (dry-run shows gaps; --write applies)
scripts/vault-tool geocode batch <Trip> [--write]
```

Station fields fill in two separately-controlled phases — Google is fast and stable; Overpass is slow and flaky, so it's opt-in as a second pass:

```bash
# Fast (Google): nearest_station + walk_time_to_station
scripts/vault-tool geocode batch <Trip> --stations --write

# Slow (Overpass): station_lines only
scripts/vault-tool geocode batch <Trip> --lines --write

# Both at once
scripts/vault-tool geocode batch <Trip> --stations --lines --write
```

`--lines` uses the existing `nearest_station` as the anchor for the OSM lookup — run `--stations` first (or ensure station names are set) before `--lines`. On `--refresh-stations`, an Overpass outage preserves existing `station_lines` values rather than clearing them.

Add `--enrich` to pull website/hours/rating (uses the Enterprise SKU — 1k free/month; verify hours against the venue's website, Google often has stale data for international venues).

### Rediscovering `nearest_station` across a category

The refresh flow anchors to existing `nearest_station`. To force fresh Places Nearby lookups (e.g. after widening the search radius, or when you suspect the anchor is wrong), clear the two fields first, then run the Google pass:

```python
# In a uv shell: clear nearest_station + walk_time_to_station on a whole category
from vault_scripts._utils import patch_field, find_entry_files, TRAVEL_DIR
for path, _, _, text in find_entry_files(TRAVEL_DIR / "<Trip>", ["<Category>"], {"<tag>"}):
    t = patch_field(patch_field(text, "nearest_station", ""), "walk_time_to_station", "")
    path.write_text(t, encoding="utf-8")
```

Then `scripts/vault-tool geocode batch <Trip> --dir <Category> --stations --write`.

## Data sources

- **coordinates / address** — Google Places API (New), Nominatim fallback
- **walk_time_to_station** — Google Routes API, `travelMode: WALK` (actual street-network route)
- **station_lines** — Overpass (OpenStreetMap), `line` tag preferred; mirror fallback

Requires **Places API (New)** + **Routes API** enabled on the Google Cloud project behind `GOOGLE_MAPS_API_KEY`. Any field can fail gracefully; the script leaves it unchanged.
