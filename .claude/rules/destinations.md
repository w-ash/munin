---
description: Schema and conventions for trip destination research files
globs: Travel/*/Destinations/**
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
spiritual: low         # low | moderate | high
nature: low            # low | moderate | high
art: low               # low | moderate | high
onsen: false
nights_needed: ""      # e.g. "2-3"
transit_from_kyoto: "" # e.g. "2.5-3h"
transit_from_tokyo: "" # e.g. "4-5h"
logistics: low         # lowest | low | medium | high | highest
google_maps_url: ""
cover: ""
```

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → Why it fits → Getting there → What to do → Practical details → Sources
