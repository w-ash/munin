---
description: Conventions for vacation planning docs in Travel/
paths:
  - "Travel/**"
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
├── Neighborhoods/      ← geographic backbone — every option's `neighborhood:` wikilinks here (see `.claude/rules/neighborhoods.md`)
├── Accommodations/
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
neighborhood: ""             # quoted Obsidian wikilink to a single neighborhood file: "[[Aoyama]]" — see `.claude/rules/neighborhoods.md`
nearest_station: ""          # station name only, e.g. "Kayabacho"
walk_time_to_station:        # integer minutes (null if unknown / not walkable)
station_lines: ""            # comma-separated, e.g. "Hibiya, Tozai"
destination: ""              # quoted Obsidian wikilink to the parent destination file: "[[Tokyo]]" — must resolve to Travel/<Trip>/Destinations/entries/
vibe: ""                     # one-line feel of the place
coordinates: ""
google_maps_url: ""
address: ""                  # romanized
address_local: ""            # native script (non-English destinations)
recommended_by: [Claude]     # Claude, friend names, or both
status: considering          # considering | shortlist | planned | booked | visited | ruled-out | sold-out
                             # sold-out = can't book (dates unavailable or permanently closed).
                             # Treat as final — don't suggest reviving.
last_visited:                # YYYY-MM-DD of most-recent visit. Required when status == "visited".
                             # All visit dates also listed in the body ## Visits section.
priority:                    # must-do | want-to | if-time (n/a on accommodations)
tier: ""                     # SS | S | A | B | C | "" — see Tier list below
book_by:                     # deadline date if applicable
booking_status:              # (n/a on accommodations — they use booking_link)
cover: ""                    # filename in Travel/<Trip>/images/, e.g. "Name.webp"
notes: ""                    # USER-RESERVED — do not write unless Ash explicitly asks
```

**`notes:` is user-reserved.** Ash's free-text commentary on the venue — reservation friction, friend feedback, personal verdict, anything that isn't sourced or structured. Agents must not write to this field unless he explicitly asks. Agent-relevant context (sourcing rationale, re-tier flags, multi-location commentary, opening dates) belongs in the body, not in `notes:`. The same convention applies to any other free-text field Ash marks as his own.

See `.claude/rules/geo.md` for geo/station field sourcing via `vault-tool geocode`.

See `.claude/rules/neighborhoods.md` for the `Neighborhoods/` folder schema, the single-neighborhood-per-file rule, granularity guidelines (sub-area folds), and the stub workflow when an option entry references a neighborhood file that doesn't exist yet.

## Tier list

Every option file (dining, experiences, shopping, accommodations) carries a `tier` ranking, scoped to **its destination + its `type` field**. Tier exists to surface what's worth the trip's limited slots — not a measure of the venue's absolute quality. A C-tier kissaten can still be a great kissaten; it just isn't the one we'd burn a coffee slot on. Same for a C-tier vintage shop or a C-tier garden.

- **SS** — Singular best-in-category for the destination. The one option that *defines* the category for this trip; if we did nothing else in the bucket, this is it. **Only one SS per destination per `type`.** Leave empty if nothing rises to the level — don't force it.
- **S** — Top tier. Highlight-of-the-trip caliber — would be a story we tell when we get back. Multiple allowed.
- **A** — Excellent. Going if scheduling allows; no regrets if we skip for an S/SS.
- **B** — Solid backup. Good if we're already in the neighborhood or it fits a logistical hole.
- **C** — Marginal interest. Keep on file, but a strong nudge toward `status: ruled-out` next pass.
- *(blank)* — Not yet evaluated. Default for new entries until they've been read against the rest of the bucket.

Tier is a **relative** judgment — hold the whole bucket in view and rank against each other. Re-rank when adding a new SS/S candidate that displaces an existing one. The single-SS constraint forces choice: if you find yourself wanting two SSs in a bucket, the bucket is telling you which to demote to S.

Tier is **independent of `status`**. A `planned` / `booked` / `visited` option can be any tier (sometimes you book a B because the SS doesn't fit the day; a `visited` venue's tier reflects what we thought going in). A `ruled-out` option keeps its tier as a record of how it stacked up. `sold-out` is final regardless of tier.

**Bucket granularity by category:**
- **Dining** — bucket by `type` (`restaurant`, `cafe`, `kissaten`, `bakery`, `sweets`, `bar`, `food-hall`, `street-food`). For `type: restaurant`, sub-bucket by `cuisine` — sushi, ramen, kaiseki, izakaya, soba, etc. each get their own SS slot, since comparing a sushi bar to a soba shop for one slot isn't meaningful.
- **Experiences** — bucket by `type` (`museum`, `gallery`, `temple`, `garden`, `nightlife`, etc.). Don't sub-bucket by `focus` unless a single type contains genuinely incomparable sub-genres.
- **Shopping** — bucket by `type` (`vintage`, `crafts`, `market`, `department`, `specialty`, `art-supplies`, `antiques`).
- **Accommodations** — bucket by destination only (no sub-type); usually one is booked, so tier is mostly an evaluation record.

### Sourcing gate (required for SS / S)

Tier ranks above A are **gated by external validation**. SS or S requires *at least one* of:

1. **Named friend recommendation** in `recommended_by` — a real person (e.g., `[Kew, Shervin]`), not `[Claude]` or `[AI]` alone.
2. **≥1 citation in the file's Sources section** from a category-recognized reputable editorial — the curated source lists in each category rule (`dining.md` "Curated sources", and the equivalent in `experiences.md` / `shopping.md` / `accommodations.md`) are the canonical "reputable" reference. Examples for dining: Sprudge, Tabelog *editorial* (magazine/Hyakumeiten — not user score), Time Out Tokyo, Inside Kyoto, dancyu, Tokyo Calendar, Hanako, BRUTUS, Casa BRUTUS, Japan Times Food & Drink.
3. **A recognized industry badge** — Michelin star or Bib Gourmand, Tabelog Hyakumeiten (with year), OAD top-100, Asia's 50 Best, Sprudge "Notable Roaster," etc.

**Disqualifiers** — these alone are *not* enough to reach S/SS, no matter how compelling the writeup sounds:
- Aggregator-only sourcing: Tabelog **user score**, Google Maps rating, TripAdvisor rank, Yelp, Foursquare
- Generic SEO travel blogs: jw-webmagazine, japanesetaste.com, Magical Trip, Ninja Food Tours, magical-trip, going-awesome-places, e-housing, Will Fly for Food, savorjapan.com, machiya-inn-japan, restaurants-guide.tokyo, and the like
- `recommended_by: [Claude]` *and* no editorial citation *and* no industry badge

A/B/C tiers have **no** sourcing gate — those are the working space for Claude-suggested options that haven't yet earned editorial backing or a friend's stamp. The gate forces upward mobility (more rigor) for high tiers while letting the long tail breathe.

The Sources section + `recommended_by` field carry the evidence — no separate `tier_evidence:` field needed. When you set or upgrade a tier to S/SS, leave a one-line `tier-rationale:` frontmatter note (optional) or note the qualifying signals in the file body so future passes can re-check the gate without re-reading the entire Sources section.

### Source-driven curation (methodology)

For "rank these / tier these / curate / find the best" tasks, default to **source-driven**: walk the credible editorial source lists first and let inclusion drive what gets ranked or created. The vault grows toward the best-of, not the other way around. Inventory-ranking what's already filed is a fallback for domains with no credible source list. Pair this with the per-category source lists (`dining.md` § Curated sources, etc.).

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

## Visits — when status: visited

When an option becomes `status: visited`, the file accumulates a body record of every visit:

1. Set `last_visited:` in frontmatter to the most-recent visit date (YYYY-MM-DD).
2. Append a `## Visits` section at the bottom of the body, listing every visit in chronological order:

   ```markdown
   ## Visits
   - **2026-05-15** — [[2026-05-15|daily]]
   - **2026-05-16** — [[2026-05-16|daily]]
   ```

Re-visits append a new line; never replace earlier dates. The most-recent date in the list must match `last_visited:`. The wikilink resolves to the daily journal entry — `[[YYYY-MM-DD|daily]]`. The same pattern works for cross-trip visits and (with a small naming variant) for local `Restaurants/` notes.

## Rules

- One file per option — never dump research into a monolithic doc
- Practical info (prices, hours, reservations) required
- Track provenance via `recommended_by`
- **`neighborhood:` is always a quoted wikilink** (`"[[Aoyama]]"`) to a file in `Travel/<Trip>/Neighborhoods/entries/`. Never plaintext, never compound (`X / Y`), never a list. Create a neighborhood stub first if the target doesn't exist — see `.claude/rules/neighborhoods.md`.
- **`destination:` is always a quoted wikilink** (`"[[Tokyo]]"`) to a file in `Travel/<Trip>/Destinations/entries/`. Never plaintext. Same applies to neighborhood files themselves — they wikilink up to their parent destination.
- **Cite editorial domain sources, not generic tourist aggregators** — see § Sourcing gate (above) for the formal disqualifier list and per-category rules (`dining.md` § Curated sources, etc.) for named source lists
- **Don't write to `notes:`** — that field is reserved for Ash's commentary; only touch it when he asks
- Use "destination" not "city" (mountains, islands, trails aren't cities)
- Pay cash for hotels, not points
- Don't duplicate across planning docs — cross-reference with `[[Doc#Section]]`
- **Prefer flagships** when a brand has multiple locations — the flagship gets the canonical file. Add a separate file for a branch when it's in a *different trip-relevant neighborhood* (so we don't miss it when planning a day in that area), is *separately starred / awarded*, or offers a *meaningfully different experience* (different chef, different format, different reservation channel). Link the files via a `related_locations:` frontmatter list of wikilinks (mirror on both files) and call out which is the flagship in the body.
