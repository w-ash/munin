---
description: Conventions for trip neighborhood files in Travel/<Trip>/Neighborhoods/
paths:
  - "Travel/**/Neighborhoods/**"
---

# Trip Neighborhoods

Trip neighborhood files in `Travel/<Trip>/Neighborhoods/entries/` use the `neighborhood-option` tag. The Neighborhoods folder is the **geographic backbone** of the trip — every `dining-option`, `experience-option`, `shopping-option`, and `accommodation-option` entry's `neighborhood:` frontmatter field wikilinks into this folder.

Same folder shape as the other category subfolders:

```
<Trip>/Neighborhoods/
├── Neighborhoods.md         ← hub (read first)
├── Neighborhoods.base       ← Bases view across entries
└── entries/                 ← one file per neighborhood
```

## Frontmatter

```yaml
created: YYYY-MM-DD
tags: [travel, <trip-tag>, neighborhood-option]
neighborhood: ""             # plain string here, not a wikilink (this IS the neighborhood)
name_jp: ""                  # native script for non-English destinations
destination: ""              # quoted Obsidian wikilink to the parent destination file: "[[<Destination>]]"
ward: ""                     # admin ward or district as a plain string, in the destination's local form.
                             # Single value only — never compound. For straddles, pick the canonical primary
                             # and acknowledge the secondary in the body. Slashes break Bases filtering.
energy: ""                   # one-line feel of the area
walkability: ""              # low | moderate | high
food_scene: ""               # low | moderate | high
nightlife: ""                # low | moderate | high
shopping: ""                 # low | moderate | high
art_culture: ""              # low | moderate | high
nearest_stations: []         # list of "Station (Lines)" strings
time_from_<base>: ""         # <base> is the trip's home-base neighborhood, lowercased
best_time: ""                # morning | afternoon | evening | all-day | etc.
status: ""                   # stub | needs-flesh-out | considering | active | visited
priority:                    # must-do | want-to | if-time
recommended_by: [Claude]
cover: ""
```

## Body

`[!summary]` TL;DR (1–3 lines), then:
Character & What to Expect → Key Streets & Areas → Getting There → What's Here (Restaurants & Cafes / Experiences / Nightlife / Shopping subsections, cross-linking the option files in this neighborhood) → Recent Changes (YYYY–YYYY) → When to Visit → Sources

For canonical structure, mirror the most-fleshed-out neighborhood file in the trip's folder (`Travel/<Trip>/Neighborhoods/entries/<Neighborhood>.md`).

## Single-neighborhood files only — no compounds

**One file = one neighborhood.** Never `X & Y.md`, `X / Y.md`, `X-Y.md`, or any other combo. If two areas walk together, pick the more specific anchor for the canonical file and create the second as its own file with cross-references in the body — don't bundle them.

This applies retroactively. If you find a compound file, split it via `obsidian rename` (which auto-updates inbound wikilinks) and create the second half as a new stub before adding new entries that point at it.

## Granularity — the middle ground

Neighborhoods should be **walkable as a unit but not so narrow that a single venue gets a file with no peers nearby**. Three calibration anchors:

- **Too broad** — ward-scale or directional names. A single ward can contain multiple distinct walking areas; file each separately when they accumulate venues.
- **Too narrow** — single-block sub-pockets where there's nothing else to do nearby. Fold these into the established adjacent neighborhood.
- **Right** — the named walking destination people use to plan a half-day.

Famous specialty streets get their own file even when geographically inside a larger area, because the street IS the destination.

When unsure, search `"<destination> neighborhoods walking guide"` — published walking guides reflect how the city is actually traversed and provide the best calibration.

## Stub workflow

When an option entry's `neighborhood:` would point at a file that doesn't exist:

1. **Create a stub** at `Travel/<Trip>/Neighborhoods/entries/<Name>.md` using the schema above. Minimal body is fine: summary + getting-there + sources.
2. **Set `status: stub`**.
3. **If ≥4 option entries point at this neighborhood**, set `status: needs-flesh-out` and add a callout at the top of the body:

   ```markdown
   > [!todo] Flesh-out needed
   > Linked from N+ <category> entries. Pull character, station info, key streets, recent changes from <category-rule curated sources>.
   ```

The threshold matters: a one-off venue doesn't warrant rich neighborhood content, but four-plus entries means we'll plan a half-day there and need walking-area context. When the count crosses the threshold for an existing simple stub, bump it to `needs-flesh-out` and add the callout.

## Linking convention (cross-cutting)

Every option file's `neighborhood:` is a **single quoted Obsidian wikilink**:

```yaml
neighborhood: "[[<Name>]]"
```

- Never plaintext (`neighborhood: <Name>`)
- Never compound (`neighborhood: "<Name> / <Other>"`)
- Never a list (`neighborhood: ["[[A]]", "[[B]]"]`) — one venue lives in one neighborhood
- The target must resolve to an existing file in `Travel/<Trip>/Neighborhoods/entries/`

If a venue genuinely straddles two neighborhoods (rare — usually it has a primary), file it in the more trip-relevant one and add a body line acknowledging the secondary association.

The `destination:` field on neighborhood files (and on every option file) is the same shape — a quoted wikilink to the parent destination:

```yaml
destination: "[[<Destination>]]"
```

The target must resolve to a file in `Travel/<Trip>/Destinations/entries/`. Never plaintext.

## Rules

<important>
1. **Wikilinks only.** Every option file's `neighborhood:` is `"[[<Name>]]"`. The `destination:` field is the same shape — `"[[<Destination>]]"` pointing at the parent file in `Travel/<Trip>/Destinations/entries/`.
2. **Single neighborhood per entry.** Split compound neighborhood files when found, via `obsidian rename` so inbound wikilinks update atomically.
3. **Stub before linking.** Never write a frontmatter wikilink to a non-existent file. Create the stub first.
4. **Move, don't delete.** Use `obsidian rename` for compound splits; never delete + recreate (loses creation date and breaks links).
5. **Don't write to `notes:`** — same convention as other option files (see `.claude/rules/travel.md`).
</important>
