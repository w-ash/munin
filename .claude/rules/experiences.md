---
description: Schema and conventions for trip experience research files
paths:
  - "Travel/*/Experiences/**"
---

# Trip Experiences

Trip experience files in `Travel/<Trip>/Experiences/entries/` use the `experience-option` tag. Covers museums, galleries, immersive art, nightlife, cultural activities.

**Filter:** would we tell a friend about this when we got home? Spaces with a point of view, not box-checking. Contemplative spaces you sit with, not rush through. Nightlife about sound and scene, not spectacle. Quality and vibe over proximity: widen the radius rather than settle for a convenient mediocre option.

What hits: contemporary art, design, media art, immersive/experiential, contemplative gardens, underground electronic (local DJs), food-as-culture.

What doesn't: fame-only landmarks, spectacle nightlife, survey-collection museums, anything that's mostly a queue.

The test for immersive and spectacle art is heart, soul, and point of view, not aesthetic register. Ash and Kew are burners; large-scale immersive art is core taste, and Meow Wolf (one of their favorite things in the US) is the calibration anchor. Kawaii or spectacle presentation doesn't make a venue off-vibe; soulless does. The nightlife spectacle filter below is about rooms that sell bottle service over sound, not about art.

## Category-specific frontmatter

Shared fields in `.claude/rules/travel.md`. On top of those:

```yaml
type: museum              # museum | gallery | theater | park | garden | cultural | immersive | nightlife | festival | fireworks | walk | tour | ride | shopping
focus: contemporary-art   # contemporary-art | design | photography | craft | traditional | media-art | folk-art | architecture | cinema | live-music | food-tour | bar-hopping | jazz | sport | stroll | hike | food-market | tea-sweets | cycling | animation
hours: ""
closed: ""
admission: ""
booking_required: false
duration: ""
may_2026_exhibition: ""   # for museums/galleries with rotating exhibitions overlapping trip
website: ""
```

**`notes:` is user-reserved** (see `.claude/rules/travel.md`). Don't write to it unless Ash asks.

### Type scope notes

The canonical types break down by experience-shape:

- **museum / gallery**: curated indoor venues with rotating or permanent collections.
- **garden**: designed gardens. Strolls *through* a garden as the experience belong here, not under `walk`.
- **park**: park-as-destination (the park itself is the draw, not a walk through it). Reserve for hangout-park cases. Most "stroll in a park" entries belong under `walk`.
- **cultural**: stationary cultural experiences (workshops, tea ceremonies, dinners with performance, day-trips that combine train + walking + sights).
- **immersive**: site-specific or sensory installations (projection-mapping, immersive theatre).
- **walk**: **self-guided** walking experiences: river strolls, neighborhood walks, mountain hikes, forest bathing, cycling routes. `focus` differentiates (`stroll` / `hike` / `cycling` / `food-tour` for a self-guided crawl / etc.). The unifying signal: no operator running it.
- **tour**: **guided** experiences led by a human guide doing cultural narration: walking tours, food tours, brewery / sewer / factory tours. The guide IS part of what makes it a tour. A pilot / driver / conductor doing pure transport is not a guide.
- **ride**: scenic vehicle journeys where the journey itself is the experience: trolleys, gondolas, cable cars / chair lifts, water buses, helicopter night flights, scenic river boats. Narration onboard doesn't promote a ride to a tour; the test is whether a guide is leading you somewhere on foot or whether the vehicle is the experience.
- **theater**: plays, opera, ballet, dance, etc.
- **nightlife**: clubs, listening bars, late-night cultural venues.
- **festival / fireworks**: date-bounded annual events.
- **shopping**: mall / retail-street / district experiences. Distinct from `Travel/<Trip>/Shopping/` which catalogs **individual shops** to buy specific things. **Department stores** live in `Travel/<Trip>/Shopping/` as `type: department`, not here; even though the architecture and food-hall floors are experience-grade, the venue is structurally a shop.

**Walk vs Tour vs Ride vs Cultural decision tree:**
1. Vehicle-borne + journey is the experience (regardless of narration)? → `ride`
2. Self-guided + walking is the experience? → `walk`
3. Human guide doing cultural narration on foot? → `tour`
4. Stationary (workshop / ceremony / dinner) or multi-mode (day-trip)? → `cultural`

`tier` is on the shared frontmatter; see the **Tier list** section in `.claude/rules/travel.md` for definitions and the **Sourcing gate** that gates SS/S. Bucket by `type` (museum, garden, walk, tour, etc.). Experiences-specific tier signals will be added once we've learned from the dining tier pass.

## Venues vs events

Two shapes of experience files:

- **Venue file**: evergreen place with no specific show attached (e.g. a museum, a club with no booked show yet). Filename is the venue name.
- **Event file**: a specific dated happening (a concert, a one-off exhibition, a seasonal festival). Filename describes the event, e.g. `Alan Licht + Otomo Yoshihide at Polaris.md`. Multiple events at the same venue get separate files.

Event files add two fields on top of the shared schema:

```yaml
date: YYYY-MM-DD          # event date
venue: ""                 # venue name (not a wikilink; a string for Bases filtering)
```

Set `book_by:` to the day before the event (or earlier if tickets sell out). Leave `may_2026_exhibition` empty; the event's own date is the source of truth.

## Filter rules

- **Techno/house briefs are strict.** When the brief is "techno / house," skip dubstep, drum and bass, jungle, footwork, juke, UK bass, breakbeat, gqom, and other bass-music or rhythmic-percussive lanes, even with high-credibility artists. House includes deep / tech / minimal / disco-house; techno includes industrial, dub-techno, minimal, tech-house; leftfield / experimental / ambient electronic counts as adjacent. Bass / footwork / dubstep nights get *mentioned* in the post-sweep summary so Ash knows what's happening, but don't get an event file unless he explicitly broadens scope.
- **Skip contact fighting sports** in must-do / cultural-experience / activity recommendations. Boxing, MMA, wrestling, etc.; the welfare-grounded objection is to physical-contact combat itself, not to whether it's packaged as ceremony or cultural tradition. Day-of walk-up is fine if Ash brings it up; don't propose it.
- **Group format over private for guided tours.** Ash and Kew dislike the level of attention a 1-on-1 private tour brings. When suggesting cultural / architecture / food guided tours, default to group-format (small-group with scheduled departures, free / donation walking tours, or group classes) over private guides, even if the private guide has a better résumé. Private only if Ash explicitly asks for it.
- **Language-accessibility filter.** When recommending guided experiences in non-English destinations, confirm English support before filing. Three viable shapes:
  1. **Group English tour** with scheduled departure (free-walking-tour collectives, Context Travel scholar-led, etc.)
  2. **Audio-guide / captioning service** at venues that don't tour-format (theater captioning services, museum audio guides)
  3. **Audio-visual / language-transcending experience**: visual / spatial / sensory media where language isn't load-bearing (photography festivals, dance, light installations, immersive art, architecture-as-experience, gardens, projection, sound art). Bilingual wall text is the standard at international-grade venues for international shows; visual performance traditions don't require language.
  
  Disqualifying without flag: local-language-only guided tours. When a major-sounding event fails the language filter, surface alternatives that hit the same intent (e.g., year-round group English tours on the same subject; private-tour operators when group isn't available; or bilingual museum exhibitions covering similar subject matter).

## Nightlife venue selection

The reference frame for `type: nightlife` is **music-first rooms**, not "the biggest club" or "the city's most famous." The SF analog set Ash uses: **Public Works / Monarch / Great Northern / 1015 Folsom**, places where the people who love the music go, not the people who just want to get drunk. Apply the same filter for any destination.

**Music-first signals (any one is positive):**
- Sound system is the lede in editorial coverage (Funktion-One, Taguchi, custom builds)
- Bookings are promoter-led rather than venue-led; the *promoter*, not the room, draws the crowd
- No bottle service, no table-booking systems, no dress code beyond "no sandals + ID required"
- Listed in domain editorial: Time Out (city) "best clubs by music genre," RA Guide, Mixmag city guides, local scene-guide equivalents

**Spectacle signals (any one is disqualifying for the music-first bucket):**
- Bottle service / table booking is prominent on the venue's own site
- Marketed as "best club in <city>" with no genre specificity
- Surfaces in TripAdvisor / Yelp / generic-tourist top-N listicles as the main signal
- Discotech / EDM-aggregator sites as the dominant inbound

**Bigger rooms are a special case.** Printworks-class rooms book serious music *some* nights and tourist-EDM *other* nights. The right filter is the **promoter, not the venue**: a respected-promoter night at a big room is in the music-first bucket; a commercial-tour / EDM-package night is not. Always verify the night, not just the room.

**Closed-venue SEO trap.** Tourist listicles routinely keep dead venues in their top-N for years. **Always verify open/closed status against** the venue's own current site or RA *before* recommending; generic SEO articles ("Top 10 \<City\> Clubs \<Year\>") regularly list demolished venues as active. Keep destination-specific known-closed lists and current venue maps in the trip's own notes, not here.

## Body

`[!summary]` TL;DR (1–3 lines), then:
Overview → The experience → Practical details → Combo suggestions → Friend notes → Sources
