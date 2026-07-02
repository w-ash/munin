---
description: Schema and conventions for trip destination research files
paths:
  - "Travel/*/Destinations/**"
---

# Trip Destinations

Trip destination files in `Travel/<Trip>/Destinations/entries/` use the `destination-option` tag. Potential cities, regions, or areas to visit — not individual venues. Shared venue frontmatter in `.claude/rules/travel.md` doesn't apply here; destinations have their own schema.

## Frontmatter

```yaml
created: YYYY-MM-DD
tags: [travel, <trip-tag>, destination-option]
status: considering    # considering | shortlist | chosen | ruled-out
destination: ""
vibe: ""
recommended_by: [Claude]
spiritual: low         # low | moderate | high; "high" means nature felt as
                       #   sacred (primeval forests, sacred groves, moss, mist,
                       #   waterfalls), NOT religious / monastery / meditation
nature: low            # low | moderate | high
art: low               # low | moderate | high
nights_needed: ""      # e.g. "2-3"
transit_from_base: ""  # e.g. "2.5-3h" from the trip's base city
logistics: low         # lowest | low | medium | high | highest
google_maps_url: ""
cover: ""
```

**`notes:` (if present) is user-reserved** (see `.claude/rules/travel.md`). Don't write to it unless Ash asks.

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → Why it fits → Getting there → What to do → Practical details → Sources
