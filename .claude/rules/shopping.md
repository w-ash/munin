---
description: Schema and conventions for trip shopping research files
globs: Travel/*/Shopping/**
---

# Trip Shopping

Trip shopping files in `Travel/<Trip>/Shopping/entries/` use the `shopping-option` tag. Two modes:

1. **Experience shopping** — stores worth visiting for the spectacle (flagship Tokyu Hands, Don Quijote). Prefer flagships over random branches.
2. **Treasure hunting** — handcrafted, made-in-Japan items to bring home. Ceramics, textiles (indigo, shibori, Nishijin-ori), artisan single-craft specialists, records (vinyl, Japanese pressings, ambient/electronic), flea/temple markets.

Skip: mass-produced souvenirs, branded streetwear resale, department store floors as a destination.

## Category-specific frontmatter

Shared fields in `.claude/rules/travel.md`. On top of those:

```yaml
type: vintage        # vintage | crafts | market | department | specialty | art-supplies | antiques
hours: ""
closed: ""
website: ""
```

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → What to look for → Practical details → Friend notes → Sources
