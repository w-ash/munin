---
description: Schema and icon mapping for trip dining research files
paths:
  - "Travel/*/Dining/**"
---

# Trip Dining

Trip dining files in `Travel/<Trip>/Dining/entries/` use the `dining-option` tag. Distinct from `Restaurants/` (local restaurant tracking).

## Category-specific frontmatter

Shared fields in `.claude/rules/travel.md`. On top of those:

```yaml
type: restaurant       # see icon table
icon: LiUtensilsCrossed
cuisine: ""            # one value, no slashes
specialty: ""          # optional sub-specialty (e.g. "Sourdough" under Bakery)
price_range: ""
meal: lunch            # breakfast | lunch | dinner | late-night | any
reservation: false
website: ""
```

Always set both `type` and `icon` in sync.

### Cuisine

One value, no slashes. Beverage program, service format, and vibe go in `vibe` / `type` / body. Sub-specialty within a cuisine uses the optional `specialty` field, e.g. `cuisine: "Bakery"` + `specialty: "Sourdough"`. Slashes break Bases filtering.

**`notes:` is user-reserved** (see `.claude/rules/travel.md`). Don't write to it unless Ash asks.

`tier` is on the shared frontmatter; see the **Tier list** section in `.claude/rules/travel.md` for definitions and the **Sourcing gate** that gates SS/S. For dining specifically, bucket by `type`; for `type: restaurant`, sub-bucket by `cuisine` (sushi, ramen, kaiseki, etc. each get their own SS slot). Per-tier signals for dining are in **What makes a high tier (Dining)** below.

## Type → Icon

| type | icon | covers |
|---|---|---|
| `restaurant` | `LiUtensilsCrossed` | Sit-down meal venues with table service: kaiseki (room format), izakaya, French, Italian, Western, Chinese, Korean, vegan/shojin, tonkatsu, casual curry, tendon, yakiniku, sukiyaki, sushi (casual / standing / heritage sit-down), yakitori (à la carte), oden |
| `counter-omakase` | `LiChefHat` | Apex chef-counter omakase formats: sushi-omakase, tempura-omakase, yakitori counter-course, counter-format kappo / kaiseki. The chef directs the meal from the counter; no menu choice; multi-course; reservation-typically; ¥10k+ |
| `noodle-shop` | `LiSoup` | Noodle-led quick-eat: ramen, udon, soba, tsukemen, mazemen, tantanmen. Single-dish primary, walk-in friendly, ¥800–3,000 typically. Includes heritage soba sit-downs (Honke Owariya, Kanda Yabu Soba) where the dish IS the visit |
| `coffee-shop` | `LiCoffee` | Specialty coffee, indie roasters, espresso bars; venues where the coffee craft is the visit |
| `tea-house` | `LiLeaf` | Matcha rooms, tea-ceremony venues, Japanese tea specialists |
| `cafe` | `LiCookie` | Food-led cafes: bookstore cafes, vegan cafes, atmospheric cafes where food/space is at least co-equal to the drink |
| `bar` | `LiWine` | Sake, cocktail, wine, whisky, listening bars |
| `bakery` | `LiCroissant` | Bakeries |
| `sweets` | `LiCakeSlice` | Wagashi, dessert spots |
| `food-hall` | `LiStore` | Depachiku, food complexes |
| `kissaten` | `LiDisc` | Retro Japanese coffee houses (pre-1990 founding, preserved interior) |
| `street-food` | `LiFlame` | Market stalls, monjayaki streets, ekiben |

**Restaurant / counter-omakase / noodle-shop distinction.** Three meal-format types replace what was one `restaurant` catchall. Test: ask "what shape is the meal?"
- *Chef-at-counter, multi-course, no menu, reservation-formal* → `counter-omakase` (Sushi Saito, Mikawa Zezankyo, Yakitori Imai, Den-counter format)
- *Single noodle dish, walk-in, quick eat* → `noodle-shop` (Maruka udon, Soba Osame, Ginza Hachigo ramen, Honke Owariya; even though heritage sit-down, the soba dish IS the visit)
- *Sit-down meal with menu choice and table service* → `restaurant` (kaiseki proper, izakaya, French, Italian, all Western, casual curry/tonkatsu/tendon, casual sushi)

Heritage noodle shops with table seating still file as `noodle-shop` (Kanda Yabu Soba, Honke Owariya, Tawaraya Udon); the dish is the visit, not the room.

**Coffee/tea typing distinction.** `coffee-shop` and `tea-house` are *drink-craft venues* (the bar discipline applied to coffee or tea). `cafe` is broader: when food and space are at least as much of the visit as the cup. `kissaten` is its own thing (Showa-era retro Japanese coffee houses). When a venue genuinely straddles two types (Café de l'Ambre crosses coffee-shop ↔ kissaten; Songbird Coffee crosses coffee-shop ↔ cafe), file once in the more-trip-relevant bucket per the cross-bucket rule.

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → What to order → Practical details → Friend notes → Sources

## Diet preferences

Diet preferences for Ash and Kew live in `.claude/rules/diet.md`. That rule covers what to investigate, what to flag, and how to surface options. Apply it when filing every dining venue here.

In short: don't filter venues out for being meat-forward, but always document the vegetarian and pescatarian options (real local-language menu names), and flag octopus-signature or beef-required dishes explicitly.

## Venue selection

Gate picks on genuine quality and vibe, not proximity or convenience. When the nearby options are mediocre, say so plainly and widen the search radius instead of padding the list; label any convenient fallback as a last resort. Name the vibe directly, not just the food.

## Curated sources

Curated editorial lists (a city's food magazines, local "best of" features) beat aggregator scores; search local-language editorial as well as English, and cite the source the recommendation actually came from in the venue file's Sources section.

## What makes a high tier (Dining)

The universal **Sourcing gate** in `travel.md` is the minimum eligibility for S/SS. Within that, dining-specific signals (strongest first):

- **Current-year industry badges**: Michelin star or Bib Gourmand, Michelin Green Star, Asia's 50 Best, OAD Top 100, Sprudge "Notable Roaster" for coffee, **World's 100 Best Coffee Shops** for coffee, **World Brewers Cup / World Barista Champion** for coffee operators, **Plant-Forward Global 50** for vegetable-forward chefs. Multi-year reselection > one-time.
- **Whole-issue / cover-treatment editorial features**: when a major editorial dedicates an entire issue or special section to a single venue, treat that as a near-badge-strength signal, heavier than a one-of-many roundup placement.
- **Recent editorial coverage**: current or prior year feature in a trusted editorial source (a city's food magazine or curated dining list). Stale citations (3+ years old) only support A or below.
- **Multi-source consensus**: same venue named by 3+ *independent* reputable editorials in recent coverage is the SS signal. Required for SS.
- **Named-friend rec** with a specific dish/experience, especially Kew or a repeat recommender for the cuisine.
- **Craft / pedigree**: heritage continuity (founding year + preserved technique + family/apprentice lineage), chef trained at a named SS/S kitchen.

**SS specifically** requires *both* recent multi-source editorial consensus *and* the SS being the singular best-in-bucket for the trip. A single old badge is not SS. If only one current source backs a venue, S is the ceiling.

**Tie-breakers** (not gate-clearers): reservation feasibility for our dates, neighborhood density with other planned stops, diet fit per `.claude/rules/diet.md`.

### Bucket caveats

- **Multi-location coffee brands**: flagship + neighborhood-relevant branches frequently both warrant separate files. When the flagship is contested, file the most-trip-relevant variant + apply `related_locations:` mirror per `travel.md`.
- **Cross-bucket / multi-genre venues**: Some shops genuinely span two `type` slots. **File once in the more-trip-relevant bucket; cross-reference from the other bucket's tracker section.** Don't double-file unless the formats differ meaningfully.
