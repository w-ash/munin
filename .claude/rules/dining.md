---
description: Schema and icon mapping for trip dining research files
globs: Travel/*/Dining/**
---

# Trip Dining

Trip dining files in `Travel/<Trip>/Dining/entries/` use the `dining-option` tag. Distinct from `Restaurants/` (local restaurant tracking).

## Category-specific frontmatter

Shared fields in `.claude/rules/travel.md`. On top of those:

```yaml
type: restaurant       # see icon table
icon: LiUtensilsCrossed
cuisine: ""            # the food, not the venue category
price_range: ""
meal: lunch            # breakfast | lunch | dinner | late-night | any
reservation: false
website: ""
```

Always set both `type` and `icon` in sync.

## Type → Icon

| type | icon | covers |
|---|---|---|
| `restaurant` | `LiUtensilsCrossed` | Sushi, ramen, kaiseki, izakaya, yakitori, tonkatsu, tempura |
| `cafe` | `LiCoffee` | Coffee shops, tea houses |
| `bar` | `LiWine` | Sake, cocktail, wine bars |
| `bakery` | `LiCroissant` | Bakeries |
| `sweets` | `LiCakeSlice` | Wagashi, dessert spots |
| `food-hall` | `LiStore` | Depachiku, food complexes |
| `kissaten` | `LiDisc` | Retro Japanese coffee houses |
| `street-food` | `LiFlame` | Market stalls, monjayaki streets, ekiben |

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → What to order → Practical details → Friend notes → Sources
