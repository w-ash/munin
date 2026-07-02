---
name: weather
description: Refresh per-day weather forecast lines in a trip's day plans via `scripts/vault-tool weather` (Open-Meteo). Detects layout via glob, supporting single-file `Travel/<Trip>/Itinerary.md`, split flat `Travel/<Trip>/Days/*.md`, and split-nested `Travel/<Trip>/Itinerary/Days/*.md` layouts. Use when the user says "update the weather" / "refresh forecasts" / "/weather <trip>" / mentions a stale forecast in any trip. Handles single-location days and travel days (origin + destination).
user_invocable: true
---

# Trip itinerary weather

Refresh the italic forecast/conditions lines under each day heading. Idempotent: replace existing lines, never duplicate. Stamp `weather_updated:` in `Itinerary.md` frontmatter regardless of layout.

**Only today and future days.** Skip any day whose date is before today (in the trip's local timezone, vs the environment `currentDate`) before doing anything else. Past-day `Forecast:` / `Conditions:` lines are a frozen historical record of what the forecast said going in; leave them untouched. This rule applies at every step below.

The numeric work (fetching, WMO code mapping, rounding, % rain, threshold notes) is owned by `scripts/vault-tool weather`; this skill orchestrates the vault edits and writes the Conditions prose.

## Layout: two formats, three possible locations

Detect via glob before doing anything else. Day files and Itinerary can sit at the trip root or be nested under an `Itinerary/` subfolder.

- **Single-file**: Itinerary.md contains all day sections as `### <Month> DD …` H3 headings, nested under `## <Segment>` H2 section headings (e.g., `## <City A> I (May 13–16)`). The H2 segment provides single-location-day context.
- **Per-day**: A `Days/` folder exists with one file per day (e.g., `May 14 (Thu).md`), each with a `# <Month> DD …` H1 heading and a `date: "YYYY-MM-DD"` frontmatter field. Itinerary.md is shrunk to a Trip shape table + daily index + Bookings; the Trip shape table provides segment-to-date mapping for single-location-day context.

**Glob-based detection** (never hardcode paths):

| Glob | Resolves |
|---|---|
| `Travel/<Trip>/**/Days/*.md` | Per-day files. Non-empty match → per-day mode. |
| `Travel/<Trip>/**/Itinerary.md` | The Itinerary.md file (the canonical match; there should be exactly one). |

Layout cases this covers:
- `Travel/<Trip>/Itinerary.md` (no Days dir) → single-file mode.
- `Travel/<Trip>/Itinerary.md` + `Travel/<Trip>/Days/*.md` → per-day, flat.
- `Travel/<Trip>/Itinerary/Itinerary.md` + `Travel/<Trip>/Itinerary/Days/*.md` → per-day, nested under Itinerary/.

`weather_updated:` always lives in whichever `Itinerary.md` the glob resolved.

## Output format

Each location contributes a **pair**: the numeric `Forecast:` line (verbatim from the command) and a prose `Conditions:` line (written by you). No blank line between pair members. Travel days get two pairs (origin then destination).

<example name="single-location day">
```
*<City A> Forecast: 🌤 mainly clear, 74° / 57°, 27% rain.*
*<City A> Conditions: cloudier than the numeric reading suggests: cloud-led day with sunny breaks and a 30% shower risk. Coolest day of the segment; carry a folding umbrella.*
```
</example>

<example name="travel day">
```
*<City A> Forecast: ⛅ partly cloudy, 81° / 55°, 4% rain.*
*<City A> Conditions: clearest and warmest morning of the <City A> segment. Bright walk to the station; pack the lighter shell on top of the suitcase.*
*<City B> Forecast: ☀️ clear, 79° / 57°, 2% rain.*
*<City B> Conditions: sunny with cloud breaks, high closer to 84°F than the numeric read suggests. Warm afternoon on arrival; comfortable evening for a riverside walk.*
```
</example>

Conditions prose stays **neutral**: never name a data source. Use "the numeric reading" when referring to the Forecast line. Cap at three sentences.

## Grounding: every clause must trace to fetched data

The user makes real travel decisions from these lines. Treat every clause in the `Conditions:` prose as a claim you'd need to defend against the command's `--json` output.

**Permitted** from the command's daily values:
- Daily high/low, daily PoP, sky character from the daily weather code, total precip, max wind
- Cross-day comparisons within the same trip (coolest, wettest, clearest, warmest morning of segment)
- Divergence between Open-Meteo and the local met office when both were fetched
- Reliability flag from the local met source
- Practical implications that follow directly from those values (what layer to wear, whether to carry an umbrella, whether the day suits an indoor or outdoor plan)

**Not permitted** without additional fetched data:
- Intra-day shower timing or peak hours ("clears by mid-afternoon", "shower window 15:00–17:00"): those need hourly data
- Humidity, dew point, or "muggy" claims beyond the command's own hot-and-muggy note
- Activity-suitability judgments not directly supported by the daily values
- Climatological background from training knowledge ("the region's rainy season typically arrives in June"): that belongs in conversation, not in the file
- Wind feel, visibility, or atmospheric character not represented in the fetched variables

If a clause needs hourly data, drop the clause. When in doubt, write less.

<example name="grounded vs invented (daily values only)">
**Grounded:** *cloud-led day with sunny breaks, 30% shower risk, capping at 75°F. The coolest of the segment's days; pleasant for walking. A light layer in the morning.*

**Invented:** *cloud-led morning clearing by mid-afternoon, with peak humidity around 14:00 and a shower window between 15:00–17:00. Muggy along the river walk.*

The grounded version cites only daily high/low, daily PoP, daily weather code, and cross-day comparison. The invented version fabricates intra-day timing, humidity, and a feel judgment nothing in the daily response supports.
</example>

## Steps

1. **Resolve trip name** from `$ARGUMENTS`. If empty, list `Travel/*/` and ask. Then **detect layout** per § Layout: glob `Travel/<Trip>/**/Days/*.md` (non-empty means per-day mode) and `Travel/<Trip>/**/Itinerary.md`. Remember both resolved paths for the rest of the run.

2. **Read the day plans.** Always read the resolved `Itinerary.md` first (`weather_updated:` lives there). If ≥1 day old, mention "last updated N days ago"; if today, ask whether to refresh anyway. Then collect day entries per layout, dropping past days (per § header). If every day is past, stop and tell the user the trip is over; don't fetch, don't stamp.

   **Single-file mode**: iterate `### <Month> DD …` H3 headings within Itinerary.md. For each, parse the date and infer location(s):
   - **Travel day**: heading has `<A> → <B>`, `Arrive <X>`, `Depart <X>`, or `Fly to <X>`. Origin = left/Depart; destination = right/Arrive.
   - **Single-location day**: defaults to the nearest preceding `## <Place>` section heading.

   **Per-day mode**: use the day-file paths from the Step 1 `**/Days/*.md` glob and read each remaining (today-or-future) file. The `date:` frontmatter field is authoritative; the H1 `# <Month> DD …` provides the heading text for travel-day parsing.
   - **Travel day**: same heading parsing as above.
   - **Single-location day**: no `## <Place>` heading exists. Use the **Trip shape** table in `Itinerary.md` (segment name → date range) to look up which segment the date falls in. Map segment name to location (`<City A> I` / `<City A> II` → `<City A>`, etc.). If ambiguous, fall back to the daily index table's "Where" column.

3. **Fetch per unique location** with one command call covering the remaining date span (today through the latest remaining itinerary date, max 16 days):

   ```bash
   scripts/vault-tool weather --place "<City>" --start <today> --end <last-day> --json
   ```

   The JSON gives, per day: the finished `line` (emoji, sky label, rounded temps, % rain, and inline threshold notes, all handled by the command) plus the raw values (`high_f`, `low_f`, `rain_pct`, `precip_in`, `wind_mph`, `code`) for grounding Conditions prose. When `--place` resolves to the wrong city (rare; the command prints what it matched in `location`), re-run with explicit `--lat/--lon` and `--label "<City>"`. If the command exits non-zero, surface its stderr to the user and stop; don't hand-build forecast lines.

4. **Fetch local met office data** for each location whose country appears in § Local met offices: fetch the country's endpoint (WebFetch) and extract per-date weather code, PoP, reliability, and min/max temps. If the country isn't mapped, tell the user in the kickoff message to extend that section, then proceed with Open-Meteo-only Conditions prose.

5. **Use the command's `line` verbatim as the Forecast line**, prefixing nothing and reformatting nothing.

6. **Write the Conditions line**: one to three sentences of plain English describing how the day will feel, every clause traceable per § Grounding. Synthesize across sources:
   - **Sky character**: when the local met office is available, defer to its call (per the country's code mapping). When sources disagree, the local source wins; surface the divergence ("cloudier than the numeric reading suggests").
   - **Temperature divergence**: if the local high is ≥3°F off the numeric reading, mention it with both values implied.
   - **Reliability**: if the local source flags low confidence, append "Low-confidence outlook; recheck the morning of."
   - **Practical implication**: layer, umbrella, indoor-vs-outdoor fit, only when directly supported by the daily values.

7. **Insert / replace.** For each remaining day, replace the existing pair(s) if present, otherwise insert immediately after the heading's blank line and before any `**Time Sensitive:**` / callout / prose. Use Edit with a unique `old_string` anchored on the heading and the next stable line.
   - **Single-file mode**: anchor on the `### <Month> DD …` H3 inside Itinerary.md.
   - **Per-day mode**: anchor on the `# <Month> DD …` H1 inside the day file. The prev/next nav line sits *above* the H1; don't disturb it.

8. **Stamp `weather_updated:`** in `Itinerary.md` frontmatter with today's date as `"YYYY-MM-DD"`. Add it after `created:` if missing; replace the value if present. Leave other frontmatter untouched.

9. **Report a one-paragraph summary** flagging notable signals: rainy days affecting outdoor plans, heat peaks, wind for open-air events, low-confidence days, anything that should change a day's shape. Note any forecast values >10 days out as directional-only.

## Local met offices

Per-country mapping. When running the skill against a trip in an uncovered country, tell the user up front to update this section before the next run, then fall back to Open-Meteo-only Conditions prose.

### Per-country template (example of the pattern, not live config)

Each covered country gets its own `### <Country> (<met office>)` subsection in this shape:

- **Endpoint:** the office's forecast URL pattern, e.g. `https://<met-office-host>/forecast/<area_code>.json` (note auth requirements; fetch via WebFetch).
- **Parse:** where per-date weather code, PoP, reliability, and min/max temps sit in the response, plus unit conversions (e.g. °C → °F).
- **Code mapping:** how the office's weather codes map to sky character (sunny-led / cloudy-led / rain-led / snow-led) and how its reliability scale maps to a low-confidence flag.
- **Area codes:** a `| Place | Area code |` table for the trip's locations, plus where to look up new codes.

## Reliability caveat

Open-Meteo's daily forecast is reliable through ~day 7–10; past that, values are directional only. Local met office feeds often cut off around day 7. Mention dates >10 days out as directional in the post-run summary. When a local met office flags low reliability, surface that in the day's Conditions prose.

## Conventions to keep

- Past days are out of scope at every step (§ header).
- Only touch the italic `Forecast:` / `Conditions:` pair under day headings: `### <Month> DD …` (single-file) or `# <Month> DD …` (per-day). Leave Time Sensitive tables, callouts, prev/next nav lines, and prose alone.
- Skip non-day headings: in single-file mode that's `##` section headings (`## Bookings`, `## <City A> I`, `## Fly Home`); in per-day mode that's the daily-index / Bookings / Alternatives content in `Itinerary.md`. Day files in `Days/` always have exactly one `# <Month> DD …` H1; that's the anchor.
- One command call per unique location covering the full remaining span; index into that response across days.
- Keep Conditions prose neutral; refer to the numeric Forecast line as "the numeric reading" and never name a data source.
- Always emit the pair even without a local met source: write Conditions from the command's values alone and tell the user to extend § Local met offices for next time.
