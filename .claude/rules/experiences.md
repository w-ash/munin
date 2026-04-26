---
description: Schema and conventions for trip experience research files
globs: Travel/*/Experiences/**
---

# Trip Experiences

Trip experience files in `Travel/<Trip>/Experiences/entries/` use the `experience-option` tag. Covers museums, galleries, temples, immersive art, nightlife, cultural activities.

**Filter:** would we tell a friend about this when we got home? Spaces with a point of view, not box-checking. Contemplative temples you sit with, not rush through. Nightlife about sound and scene, not spectacle.

What hits: contemporary art, design, media art, immersive/experiential, Zen gardens, Shinto shrines in nature, underground electronic (local DJs), food-as-culture.

What doesn't: fame-only temples, spectacle nightlife, survey-collection museums, anything that's mostly a queue.

## Category-specific frontmatter

Shared fields in `.claude/rules/travel.md`. On top of those:

```yaml
type: museum              # museum | gallery | theater | park | garden | temple | cultural | immersive | nightlife | festival | fireworks
focus: contemporary-art   # contemporary-art | design | photography | craft | traditional | media-art | folk-art | architecture | ukiyo-e | food-tour | bar-hopping | sport | stroll | food-market | tea-sweets | cycling | shrine | zen | jodo | shinto | animation
hours: ""
closed: ""
admission: ""
booking_required: false
duration: ""
may_2026_exhibition: ""   # for museums/galleries with rotating exhibitions overlapping trip
website: ""
```

## Venues vs events

Two shapes of experience files:

- **Venue file** — evergreen place with no specific show attached (e.g. a temple, a club with no booked show yet). Filename is the venue name.
- **Event file** — a specific dated happening (a concert, a one-off exhibition, a seasonal festival). Filename describes the event, e.g. `Alan Licht + Otomo Yoshihide at Polaris.md`. Multiple events at the same venue get separate files.

Event files add two fields on top of the shared schema:

```yaml
date: YYYY-MM-DD          # event date
venue: ""                 # venue name (not a wikilink — a string for Bases filtering)
```

Set `book_by:` to the day before the event (or earlier if tickets sell out). Leave `may_2026_exhibition` empty — the event's own date is the source of truth.

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → The experience → Practical details → Combo suggestions → Friend notes → Sources
