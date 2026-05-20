---
description: Schema for local restaurant notes in Restaurants/
paths:
  - "Restaurants/**"
---

# Restaurant Notes

Local restaurant tracking (Oakland, SF, etc.). Distinct from `Travel/*/Dining/` (trip research).

## Frontmatter

```yaml
created: YYYY-MM-DD
tags: [restaurant]
name: ""
cuisine: ""
neighborhood: ""
city: ""
status: "want-to-try"  # want-to-try | been | closed
rating:                 # 1-5, only after visiting
price: ""               # $ | $$ | $$$ | $$$$
vibe: ""
rec-for-friends: false
last-visited:
reservation: false
link: ""
coordinates: ""
google_maps_url: ""
address: ""
```

## Body

```markdown
## What to Order
## Notes
## Visits
- **YYYY-MM-DD** — Who ([[wikilinks]]), what, how it was.
```

## Creation

- Status defaults to `want-to-try`; change to `been` after a visit.
- Ask for rating and rec-for-friends after user describes experience.
- After creating the file, geocode it: `scripts/vault-tool geocode lookup --file "Restaurants/<Name>.md" --write`
