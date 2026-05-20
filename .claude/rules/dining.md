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

One value, no slashes. Beverage program, service format, and vibe go in `vibe` / `type` / body. Sub-specialty within a cuisine uses the optional `specialty` field — e.g. `cuisine: "Bakery"` + `specialty: "Sourdough"`. Slashes break Bases filtering.

**`notes:` is user-reserved** (see `.claude/rules/travel.md`). Don't write to it unless Ash asks.

`tier` is on the shared frontmatter — see the **Tier list** section in `.claude/rules/travel.md` for definitions and the **Sourcing gate** that gates SS/S. For dining specifically, bucket by `type`; for `type: restaurant`, sub-bucket by `cuisine` (sushi, ramen, kaiseki, etc. each get their own SS slot). Per-tier signals for dining are in **What makes a high tier (Dining)** below.

## Type → Icon

| type | icon | covers |
|---|---|---|
| `restaurant` | `LiUtensilsCrossed` | Sit-down meal venues with table service — kaiseki (room format), izakaya, French, Italian, Western, Chinese, Korean, vegan/shojin, tonkatsu, casual curry, tendon, yakiniku, sukiyaki, sushi (casual / standing / heritage sit-down), yakitori (à la carte), oden |
| `counter-omakase` | `LiChefHat` | Apex chef-counter omakase formats — sushi-omakase, tempura-omakase, yakitori counter-course, counter-format kappo / kaiseki. The chef directs the meal from the counter; no menu choice; multi-course; reservation-typically; ¥10k+ |
| `noodle-shop` | `LiSoup` | Noodle-led quick-eat — ramen, udon, soba, tsukemen, mazemen, tantanmen. Single-dish primary, walk-in friendly, ¥800–3,000 typically. Includes heritage soba sit-downs (Honke Owariya, Kanda Yabu Soba) where the dish IS the visit |
| `coffee-shop` | `LiCoffee` | Specialty coffee, indie roasters, espresso bars — venues where the coffee craft is the visit |
| `tea-house` | `LiLeaf` | Matcha rooms, tea-ceremony venues, Japanese tea specialists |
| `cafe` | `LiCookie` | Food-led cafes — bookstore cafes, vegan cafes, atmospheric cafes where food/space is at least co-equal to the drink |
| `bar` | `LiWine` | Sake, cocktail, wine, whisky, listening bars |
| `bakery` | `LiCroissant` | Bakeries |
| `sweets` | `LiCakeSlice` | Wagashi, dessert spots |
| `food-hall` | `LiStore` | Depachiku, food complexes |
| `kissaten` | `LiDisc` | Retro Japanese coffee houses (pre-1990 founding, preserved interior) |
| `street-food` | `LiFlame` | Market stalls, monjayaki streets, ekiben |

**Restaurant / counter-omakase / noodle-shop distinction.** Three meal-format types replace what was one `restaurant` catchall. Test: ask "what shape is the meal?"
- *Chef-at-counter, multi-course, no menu, reservation-formal* → `counter-omakase` (Sushi Saito, Mikawa Zezankyo, Yakitori Imai, Den-counter format)
- *Single noodle dish, walk-in, quick eat* → `noodle-shop` (Maruka udon, Soba Osame, Ginza Hachigo ramen, Honke Owariya — even though heritage sit-down, the soba dish IS the visit)
- *Sit-down meal with menu choice and table service* → `restaurant` (kaiseki proper, izakaya, French, Italian, all Western, casual curry/tonkatsu/tendon, casual sushi)

Heritage noodle shops with table seating still file as `noodle-shop` (Kanda Yabu Soba, Honke Owariya, Tawaraya Udon) — the dish is the visit, not the room.

**Coffee/tea typing distinction.** `coffee-shop` and `tea-house` are *drink-craft venues* (the bar discipline applied to coffee or tea). `cafe` is broader — when food and space are at least as much of the visit as the cup. `kissaten` is its own thing (Showa-era retro Japanese coffee houses). When a venue genuinely straddles two types (Café de l'Ambre crosses coffee-shop ↔ kissaten; Songbird Coffee crosses coffee-shop ↔ cafe), file once in the more-trip-relevant bucket per the cross-bucket rule.

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → What to order → Practical details → Friend notes → Sources

## Diet preferences

Diet preferences for Ash and Kew live in the user-level rule at `~/.claude/rules/diet.md`. That rule covers what to investigate, what to flag, and how to surface options. Apply it when filing every dining venue here.

In short: don't filter venues out for being meat-forward, but always document the vegetarian and pescatarian options (Japanese + romaji menu names), and flag tako-signature or beef-required dishes explicitly.

## Curated sources — Tokyo & Kyoto

Search **both** English and Japanese sources for every venue. Japanese-language editorial regularly surfaces vegetable and pescatarian items, opening dates, and neighborhood context that English aggregators miss. Cite the source the recommendation actually came from in the venue file's Sources section — don't launder a Tabelog-discovered place as a Time Out find.

### English-language

- **Time Out Tokyo** — [timeout.com/tokyo](https://www.timeout.com/tokyo). Closest direct equivalent to Eater. Editorial "best of" lists by neighborhood and category (best coffee, best ramen, best new openings), updated frequently. Strong on cafés and new openings.
- **Tokyo Weekender** — [tokyoweekender.com](https://www.tokyoweekender.com). Magazine-style features on new restaurants and cafés. Recurring "must-try new coffee shops" and seasonal restaurant roundups, very Eater-adjacent.
- **Truly Tokyo / Inside Kyoto** — [trulytokyo.com](https://trulytokyo.com), [insidekyoto.com](https://insidekyoto.com). Run by Chris Rowthorn (former Lonely Planet Kyoto author, decades-long resident). Less glossy than Eater, but the most thorough English curation: lists organized by cuisine, neighborhood, and budget, with a strong "eat like a local" angle and regular updates. **Inside Kyoto is the single best English-language resource for Kyoto dining and kissaten.** Newsletter form at [trulytokyo.substack.com](https://trulytokyo.substack.com) for ongoing updates.
- **Tabelog English** — [tabelog.com/en](https://tabelog.com/en). Not editorial, but the 百名店 (Hyakumeiten / "Top 100") annual awards are essentially Japan's curated "best in category" lists for ramen, sushi, yakitori, cafés, etc. The English version is partial but usable.
- **The Japan Times Food & Drink** — [japantimes.co.jp/life/food-drink](https://www.japantimes.co.jp/life/food-drink/). Long-running editorial restaurant criticism (Robbie Swinnerton's column ran for 20+ years). Best for evaluating individual venues with depth, not for discovery lists.
- **OAD (Opinionated About Dining)** — [opinionatedaboutdining.com](https://www.opinionatedaboutdining.com). Diner-survey rankings of fine-dining restaurants worldwide. Stronger signal than Michelin for chef-driven, ingredient-forward kaiseki/sushi spots; weights repeat international visits, so leans toward the polished and reservation-hard.
- **Asia's 50 Best Restaurants** — [theworlds50best.com/asia](https://www.theworlds50best.com/asia/en/). Annual industry list (jury-voted, S.Pellegrino-sponsored). Useful as a benchmark for what the global restaurant industry currently rates highest in Tokyo/Kyoto/Osaka. Less useful for casual or coffee picks.
- **Coffee-specific:**
  - **World's 100 Best Coffee Shops** — annual industry list (expert panel 70% + public vote 30%). Tokyo entries are *the* clean SS-gate signal for coffee — equivalent in trust to a Michelin-star or Tabelog-Gold signal for sushi. Cross-check Time Out Tokyo's annual coverage of the list for the Tokyo entries.
  - **Sprudge** — [sprudge.com](https://sprudge.com) plus [sprudge.substack.com](https://sprudge.substack.com). The leading specialty-coffee publication globally. Neighborhood-by-neighborhood Tokyo guides (Sangenjaya, Shibuya, Harajuku, etc.) and ongoing roaster coverage. Use this first for coffee picks; the "Sprudge Notable Roaster" tag is a real per-venue signal (search venue name + Sprudge — there's no roll-up list).
  - **Time Out Tokyo "30 best coffee shops"** — [timeout.com/tokyo/restaurants/the-best-coffee-in-tokyo](https://www.timeout.com/tokyo/restaurants/the-best-coffee-in-tokyo). Comprehensive curated 30-venue list, regularly refreshed. Highest-trust English coffee survey for Tokyo.
  - **Tokyo Weekender — international coffee roundups** — annual "must-try new coffee shops" features highlighting recent international transplants (Australian, Italian, Taiwanese, etc.). Useful for current-year openings; single-source signal.
  - **Casa BRUTUS issue-level features** — every few years Casa BRUTUS dedicates a whole issue to coffee. Whole-issue features carry near-badge editorial weight — a venue named in Casa BRUTUS's special-section / cover treatment counts much heavier than a one-of-many roundup placement.
  - **Yokogao Magazine** — [yokogaomag.com](https://www.yokogaomag.com). Mid-trust English curation with periodic 10-venue Tokyo coffee lists; useful for cross-source confirmation.
  - **Beean Coffee** — [beeancoffee.com](https://beeancoffee.com). Neighborhood-organized specialty coffee guides for Tokyo. Short curated picks (4-6 roasters); single trusted-curator signal.
  - **Barista Magazine** — [baristamagazine.com](https://www.baristamagazine.com). Trade-publication curated Tokyo/Kyoto café features. Industry-side editorial, high signal for craft and championship-pedigree picks.
  - **Coffee Guide JP** — [coffee-guide.jp/en](https://coffee-guide.jp/en). *Title-vs-content trap*: the "Top 10 by Neighborhood" article describes 10 *neighborhoods* but does not name specific cafes — useful as a neighborhood-orientation map, **disqualified by the gate as a venue source**.

### Japanese-language

- **食べログ (Tabelog)** — [tabelog.com](https://tabelog.com). Dominant restaurant platform. Beyond user reviews, the 百名店 (Hyakumeiten) annual awards are highly trusted curation. Also see **食べログマガジン** ([magazine.tabelog.com](https://magazine.tabelog.com)) for editorial features — including the well-known annual 『東京最高のレストラン』 roundup by veteran critics.
- **東京カレンダー (Tokyo Calendar)** — [tokyo-calendar.jp](https://tokyo-calendar.jp). Major monthly gourmet/lifestyle magazine. Editor-curated "新店" (new openings), seasonal specials, and category roundups (e.g. "2026年の旬の美食"). Premium-leaning but the editorial team is genuinely opinionated. Reservation arm at [gourmet-calendar.com](https://gourmet-calendar.com) doubles as a discovery surface for the magazine's picks.
- **dancyu (ダンチュウ)** — [dancyu.jp](https://dancyu.jp). The most respected Japanese food magazine. Searchable shop database (うまい店案内), serialized columns like 【明日、どこに食べに行こう？】 and 【京都で飲みたい】. What serious Japanese food people actually read.
- **Hanako** — [hanako.tokyo](https://hanako.tokyo). Lifestyle magazine that runs an annual Kyoto food special. Curated lists with a stylish, design-aware lens. The `/tags/kyoto/` archive is a goldmine.
- **BRUTUS / Casa BRUTUS** — [brutus.jp](https://brutus.jp), [casabrutus.com](https://casabrutus.com). Magazine House publications. BRUTUS's recurring restaurant special issues (おいしい店) and Casa BRUTUS's café/architecture-leaning features are widely cited.
- **ことりっぷ (co-trip)** — [co-trip.jp](https://co-trip.jp). Travel-magazine curation, particularly good for café roundups in Kyoto by area.
- **Leaf KYOTO** — [leafkyoto.net](https://www.leafkyoto.net). Local Kyoto editorial magazine. Very current on Kyoto-specific openings; the annual café roundup and "新店" coverage are good entry points.
- **OZmagazine** — [ozmall.co.jp](https://www.ozmall.co.jp). Stronger on cafés, sweets, and afternoon-tea style coverage; women's-lifestyle angle.

### Avoid as primary sources

Skip TripAdvisor, Yelp, Magical Trip, Ninja Food Tours, "jw-webmagazine," "japanesetaste.com," and similar SEO-driven aggregators — they recycle the same dozen tourist-trail venues and miss the local creative scene entirely. Use them only to cross-check basic facts (hours, address) when the venue's own site is down. The universal **Sourcing gate** in `travel.md` formally disqualifies these from supporting an S/SS tier.

## What makes a high tier (Dining)

The universal **Sourcing gate** in `travel.md` is the minimum eligibility for S/SS. Within that, dining-specific signals (strongest first):

- **Current-year industry badges** — Tabelog Hyakumeiten 百名店 (cite year + category), Michelin star or Bib Gourmand, Michelin Green Star, Asia's 50 Best, OAD Top 100, Sprudge "Notable Roaster" for coffee, **World's 100 Best Coffee Shops** for coffee, **World Brewers Cup / World Barista Champion** for coffee operators, **Plant-Forward Global 50** for shojin / vegetable-forward chefs. Multi-year reselection > one-time.
- **Whole-issue / cover-treatment editorial features** — when a major editorial dedicates an entire issue or special section to a single venue, treat that as a near-badge-strength signal — heavier than a one-of-many roundup placement.
- **Recent editorial coverage** — current or prior year feature in dancyu, Tokyo Calendar, Hanako, BRUTUS/Casa BRUTUS, 食べログマガジン『東京最高のレストラン』, Leaf KYOTO, Time Out Tokyo, Inside Kyoto / Truly Tokyo, Japan Times Food & Drink. Stale citations (3+ years old) only support A or below.
- **Multi-source consensus** — same venue named by 3+ *independent* reputable editorials in recent coverage is the SS signal. Required for SS.
- **Named-friend rec** with a specific dish/experience, especially Kew or a repeat recommender for the cuisine.
- **Craft / pedigree** — heritage continuity (founding year + preserved technique + family/apprentice lineage), chef trained at a named SS/S kitchen.

**SS specifically** requires *both* recent multi-source editorial consensus *and* the SS being the singular best-in-bucket for the trip. A single old badge is not SS. If only one current source backs a venue, S is the ceiling.

**Tie-breakers** (not gate-clearers): reservation feasibility for our dates, neighborhood density with other planned stops, diet fit per `~/.claude/rules/diet.md`.

### Bucket caveats

- **Coffee/cafe** — Hyakumeiten Cafe is split EAST/WEST (slug `cafe_east` / `cafe_west`, no Tokyo-specific list). It's also genre-promiscuous: hotel lounges, tea houses, bakery cafes, and chain cafes (Paul Bassett, Le Pain Quotidien, Rose Bakery) sit alongside specialty roasters. Treat Hyakumeiten Cafe as *one signal among many* for specialty coffee — never as the spine of the tier list. Cross-reference with Sprudge / Time Out / Barista Mag / World's 100 Best to find the specialty subset.
- **Multi-location coffee brands** — flagship + neighborhood-relevant branches frequently both warrant separate files (Koffee Mameya / Kakeru, Glitch Jinbocho / Ginza, Fuglen Tomigaya / Sangubashi, Sarutahiko Ebisu / Sengawa / The Bridge). When the flagship is contested, file the most-trip-relevant variant + apply `related_locations:` mirror per `travel.md`.
- **Kissaten** — Hyakumeiten Kissaten is a single national list (no EAST/WEST), and its **most recent edition is 2022** (Tabelog hasn't refreshed since). Every solo Hyakumeiten Kissaten cite is therefore stale and caps at A on its own. Lift to S requires a current trusted editorial cross-cite — Time Out Tokyo's "13 best retro Japanese coffee shops" is the heaviest current English signal; Tokyo Weekender, Japan Times, and BRUTUS round out the editorial ladder. Inside Kyoto is the canonical Kyoto English source.
- **Kissaten — weight heritage continuity above multi-source consensus.** Unlike most buckets where the dining-tier hierarchy puts editorial consensus first, kissaten signals are *primarily* heritage-driven: founding year, preserved interior, family lineage, original-furniture fidelity. A 1940 Kyoto kissaten (Inoda) with no Hyakumeiten badge but Inside Kyoto + Mirucollection + heritage architecture can clear S/SS, while a recently-opened "modern kissaten" with Time Out coverage stays at A. Architecture-as-recommendation is part of the venue's tier signal.
- **Cross-bucket / multi-genre venues** — Some shops genuinely span two `type` slots (e.g., Café de l'Ambre is both `cafe` per Sprudge/Time Out coffee coverage *and* `kissaten` per Hyakumeiten Kissaten 2022 + Time Out kissaten). **File once in the more-trip-relevant bucket; cross-reference from the other bucket's tracker section.** Don't double-file unless the formats differ meaningfully.
- **Vegan / Shojin** — No 精進料理 Hyakumeiten genre exists, and the major shojin venues (Daigo, Itosho, Sougo, Bon) are also absent from 日本料理 TOKYO Hyakumeiten. Skip Tabelog awards entirely for this bucket; lead with Michelin (the operative current badge — Daigo ★ + Green Star, Itosho ★, Ajiro Honten ★, Shigetsu Bib Gourmand) plus shojin-specialist editorial (Tokyo Weekender shojin guide, Inside Kyoto Best Shojin Ryori). Aggregator vegan rankings (HappyCow, Vegewel) cap at A regardless of position; vegan-only restaurants need editorial multi-source or Michelin to clear S.
