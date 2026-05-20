---
description: Schema and conventions for trip shopping research files
paths:
  - "Travel/*/Shopping/**"
---

# Trip Shopping

Trip shopping files in `Travel/<Trip>/Shopping/entries/` use the `shopping-option` tag. Two modes:

1. **Experience shopping** — stores worth visiting for the spectacle (flagship Tokyu Hands, Don Quijote). Prefer flagships over random branches.
2. **Treasure hunting** — handcrafted, made-in-Japan items to bring home. Ceramics, textiles (indigo, shibori, Nishijin-ori), artisan single-craft specialists, records (vinyl, Japanese pressings, ambient/electronic), flea/temple markets.

Skip: mass-produced souvenirs, branded streetwear resale, department store floors as a destination.

## Category-specific frontmatter

Shared fields in `.claude/rules/travel.md`. On top of those:

```yaml
type: vintage        # see vocabulary below
hours: ""
closed: ""
website: ""
```

**`type` vocabulary** (fine-grained — bucket-by-type drives tier comparison, so each type should hold genuinely comparable venues):

- *Crafts / made-by-hand* — `bags`, `shoes`, `ceramics`, `textiles`, `paper`, `knives`, `chopsticks`, `lacquer`, `fans`, `brushes`, `books`
- *Single-product specialists* — `tea`, `food`, `records`, `gachapon`, `electronics`
- *Lifestyle / fashion* — `clothing`, `homewares`
- *Mode-of-shopping* — `vintage`, `market`, `department`, `antiques`, `art-supplies`
- *Last-resort fallback* — `crafts`, `specialty` — only when a venue genuinely doesn't fit a product bucket (e.g., multi-shop retail complex, multi-floor everything-store). Prefer adding a new fine-grained type over reaching for these.

**`notes:` is user-reserved** (see `.claude/rules/travel.md`). Don't write to it unless Ash asks.

`tier` is on the shared frontmatter — see the **Tier list** section in `.claude/rules/travel.md` for definitions and the **Sourcing gate** that gates SS/S. Bucket by `type`; each type holds the comparable peer set (HERZ competes with other `bags`, not with Hakuchikudo's fans). Shopping-specific tier signals will be added once we've learned from the Tokyo dining tier pass.

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → What to look for → Practical details → Friend notes → Sources
