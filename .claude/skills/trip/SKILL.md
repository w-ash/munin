---
name: trip
description: Start a vacation planning session. Loads trip context, shows current state, asks what to work on.
user_invocable: true
---

# Trip Planning Session

Load context for a trip so you don't have to re-explain everything each session.

## Steps

1. **Parse the trip name** from `$ARGUMENTS`. If none given, list folders in `Travel/` and ask.

2. **Load trip context:**
   - `Travel/$ARGUMENTS/$ARGUMENTS.md` (hub: traveler profile, goals, open decisions)
   - `Travel/Research Schemas.md` (file structure + frontmatter schemas)
   - List files across all category subfolders (`Destinations/`, `Experiences/`, `Dining/`, `Shopping/`, `Accommodations/`, `Neighborhoods/`). Item files live in each category's `entries/`.
   - Read hub notes for active categories.

3. **Present current state:** trip dates + travelers, what's decided, what's open, what research exists (counts per category), time-sensitive items.

4. **Ask** what to work on this session.

## Research workflow

When the user asks to research options:

- **Present frameworks, not decisions.** Lay out viable options with honest pros/cons. Don't narrow the field or push toward a recommendation unless asked.
- **Search in the local language too** (`WebSearch`, not curl). Label non-English sources with the language, e.g. `(FR)`.
- **Cite sources**: every rec needs a Sources section with English + local-language links.
- **Track provenance** via `recommended_by` (list): `Claude`, friend names, or both.

## Creating option files

1. Create one file per option in `<Category>/entries/` with the correct `<category>-option` tag. Never dump multiple options into one file.
2. Hub note and `.base` live at the category root (trip-wide; `.base` views filter by city). Create them if starting a new category; see `Travel/Research Schemas.md` for the hub pattern and `.base` format.
3. Include the schema's local-language name field (`name_jp` in the option-file schema; see `.claude/rules/travel.md`) for venues in non-English destinations.
4. Style Guide conventions on every option file: breadcrumb, `[!summary]` TL;DR, cover image embed.
5. Geocode: `scripts/vault-tool geocode lookup --file "<path>" --write --stations`
6. Add cover image: `scripts/vault-tool cover_image --file "<path>" --url "<image-url>" --write`

## File operations

Use the `obsidian` CLI where possible (respects the index, auto-updates wikilinks). After editing a `.base`, verify it parses:

```bash
obsidian base:query path="<path>.base" view="<view name>" format=json
```
