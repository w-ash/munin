---
description: Conventions for vacation planning docs in Travel/
globs: Travel/**
---

# Travel Planning

Ash and Kew: Oakland, CA. Value authentic over fancy, soul over spectacle. Burners drawn to art, counterculture, underground electronic music, creative communities.

## Structure

Each trip: `Travel/<Trip>/` with a hub note linking sub-docs. Read the hub first.

Planning docs (itinerary, budget, logistics, packing) live flat at trip root. Collections of comparable options get a **subfolder**:

```
<Trip>/
├── <Trip>.md           ← hub (read first)
├── Itinerary.md        ← planning docs (flat at root)
├── Destinations/
│   ├── Destinations.md ← hub (comparison + decision)
│   ├── Destinations.base
│   └── entries/        ← comparable options with frontmatter
├── Experiences/
├── Dining/
└── Shopping/
```

**Hub notes** frame the category and embed the `.base` for auto-generated listings. Don't hand-maintain option lists in hubs.

**Individual option files**: one per option in `entries/`, Bases-compatible frontmatter, tagged `<category>-option`.

## Shared option-file frontmatter

Every trip option file (`dining-option`, `experience-option`, `shopping-option`, `accommodation-option`) uses these fields. Category rules add their own on top.

```yaml
created: YYYY-MM-DD
tags: [travel, <trip-tag>, <category>-option]
name: ""
name_jp: ""
neighborhood: ""
nearest_station: ""          # station name only, e.g. "Kayabacho"
walk_time_to_station:        # integer minutes (null if unknown / not walkable)
station_lines: ""            # comma-separated, e.g. "Hibiya, Tozai"
destination: ""
vibe: ""                     # one-line feel of the place
coordinates: ""
google_maps_url: ""
address: ""                  # romanized
address_local: ""            # native script (non-English destinations)
recommended_by: [Claude]     # Claude, friend names, or both
status: considering          # considering | shortlist | chosen | booked | ruled-out | sold-out
                             # sold-out = can't book (dates unavailable or permanently closed).
                             # Treat as final — don't suggest reviving.
priority:                    # must-do | want-to | if-time (n/a on accommodations)
book_by:                     # deadline date if applicable
booking_status:              # (n/a on accommodations — they use booking_link)
cover: ""                    # filename in Travel/<Trip>/images/, e.g. "Name.webp"
```

See `.claude/rules/geo.md` for geo/station field sourcing via `vault-tool geocode`.

## Formatting

Key rules (full reference in `Travel/Style Guide.md`):

- **Purpose sentence** first on every planning/hub/option file
- **`[!summary]`** callout at top
- **`[!question]`** callout near top of hub docs for open decisions
- **Foldable callouts** (`[!type]-`) for reference material, skip lists, resolved items
- **Never collapse "What We're Looking For"** — it's the soul of each hub
- **Bold the anchor** in table rows for scanning
- **`obsidianUIMode: preview`** on hub and planning docs
- **Breadcrumbs** on option files: `[[<Trip>]] · [[<Hub>]]`
- **`---` separators** between major sections
- **Cover image**: `cover` frontmatter + `![[Name.webp|600]]` after summary. Images in `Travel/<Trip>/images/`, WebP, under 300KB. Use `scripts/vault-tool cover_image --file <path> --url <url> --write`.

## Rules

- One file per option — never dump research into a monolithic doc
- Practical info (prices, hours, reservations) required
- Track provenance via `recommended_by`
- Use "destination" not "city" (mountains, islands, trails aren't cities)
- Pay cash for hotels, not points
- Don't duplicate across planning docs — cross-reference with `[[Doc#Section]]`
- **Prefer flagships** when a brand has multiple locations; pick a branch only for a specific reason (better access, different experience, flagship closed)
