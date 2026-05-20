---
name: weather
description: Refresh per-day weather forecast lines in a trip's day plans using the Open-Meteo MCP. Detects layout via glob — supports single-file `Travel/<Trip>/Itinerary.md`, split flat `Travel/<Trip>/Days/*.md`, and split-nested `Travel/<Trip>/Itinerary/Days/*.md` layouts. Use when the user says "update the weather" / "refresh forecasts" / "/weather <trip>" / mentions a stale forecast in any trip. Handles single-location days and travel days (origin + destination).
user_invocable: true
---

# Trip itinerary weather

Refresh the italic forecast/conditions lines under each day heading. Idempotent — replace existing lines, never duplicate. Stamp `weather_updated:` in `Itinerary.md` frontmatter regardless of layout.

**Only today and future days.** Forecasts for past dates are useless to the user and Open-Meteo's forecast endpoint won't return them anyway. Skip any day whose date is before today before doing anything else — don't read it, don't fetch for it, don't touch its existing `Forecast:` / `Conditions:` lines (those are now a historical record of what the forecast said going in). The cutoff is today's date (per the environment `currentDate`), evaluated in the trip's local timezone.

## Layout — two formats, three possible locations

Detect via glob before doing anything else. Day files and Itinerary can sit at the trip root or be nested under an `Itinerary/` subfolder.

- **Single-file** — Itinerary.md contains all day sections as `### <Month> DD …` H3 headings, nested under `## <Segment>` H2 section headings (e.g., `## Tokyo I (May 13–16)`). The H2 segment provides single-location-day context.
- **Per-day** — A `Days/` folder exists with one file per day (e.g., `May 14 (Thu).md`), each with a `# <Month> DD …` H1 heading and a `date: "YYYY-MM-DD"` frontmatter field. Itinerary.md is shrunk to a Trip shape table + daily index + Bookings; the Trip shape table provides segment-to-date mapping for single-location-day context.

**Glob-based detection** — never hardcode paths:

| Glob | Resolves |
|---|---|
| `Travel/<Trip>/**/Days/*.md` | Per-day files. Non-empty match → per-day mode. |
| `Travel/<Trip>/**/Itinerary.md` | The Itinerary.md file (the canonical match — there should be exactly one). |

Layout cases this covers:
- `Travel/<Trip>/Itinerary.md` (no Days dir) → single-file mode.
- `Travel/<Trip>/Itinerary.md` + `Travel/<Trip>/Days/*.md` → per-day, flat.
- `Travel/<Trip>/Itinerary/Itinerary.md` + `Travel/<Trip>/Itinerary/Days/*.md` → per-day, nested under Itinerary/.

`weather_updated:` always lives in whichever `Itinerary.md` the glob resolved.

## Output format

Each location contributes a **pair**: a numeric `Forecast:` line and a prose `Conditions:` line. No blank line between pair members. Travel days get two pairs (origin then destination).

<example name="single-location day">
```
*Tokyo Forecast: 🌤 mainly clear, 74° / 57°, 27% rain.*
*Tokyo Conditions: cloudier than the numeric reading suggests — cloud-led day with sunny breaks and a 30% shower risk. Morning likely soft and overcast, afternoon at peak shower probability (carry a folding umbrella along the Meguro River), evening trending dry.*
```
</example>

<example name="travel day">
```
*Tokyo Forecast: ⛅ partly cloudy, 81° / 55°, 4% rain.*
*Tokyo Conditions: clearest and warmest morning of Tokyo I — sunny with cloud breaks. Bright Yamanote-to-Shinkansen walk; pack the lighter shell on top of the suitcase.*
*Kyoto Forecast: ☀️ clear, 79° / 57°, 2% rain.*
*Kyoto Conditions: sunny with cloud breaks, high closer to 84°F than the numeric read suggests. Warm afternoon on arrival; comfortable evening walking the Kamogawa.*
```
</example>

Conditions prose stays **neutral** — never name a data source. Use "the numeric reading" when referring to the Forecast line. Cap at three sentences.

## Grounding — every clause must trace to fetched data

The user makes real travel decisions from these lines. A wrong inference can mean a missed booking, the wrong layer for the airport, or a soaked outdoor reservation. Treat every clause in the `Conditions:` prose as a claim you'd need to defend against the raw API response.

**Permitted** with the default daily-only fetch:
- Daily high/low, daily PoP, sky character from the daily weather code, total precip, max wind
- Cross-day comparisons within the same trip (coolest, wettest, clearest, warmest morning of segment)
- Divergence between Open-Meteo and the local met office when both were fetched
- Reliability flag from the local met source
- Practical implications that follow directly from those values (what layer to wear, whether to carry an umbrella, whether the day suits an indoor or outdoor plan)

**Not permitted** without additional fetched data:
- Intra-day shower timing or peak hours ("afternoon at peak shower probability", "clears by mid-afternoon", "shower window 15:00–17:00") — these require hourly data
- Humidity, dew point, or "muggy" claims outside the explicit 88°F-and-min-70°F rule
- Activity-suitability judgments that aren't directly supported by the daily values
- Climatological background or seasonal context from training knowledge ("Tokyo's tsuyu typically arrives in June") — that belongs in conversation, not in the file
- Wind feel, visibility, or atmospheric character not represented in the fetched variables

If a clause needs hourly data, fetch hourly first or drop the clause. When in doubt, write less.

<example name="grounded vs invented (daily-only fetch)">
**Grounded:** *cloud-led day with sunny breaks, 30% shower risk, capping at 75°F. The coolest of the Tokyo I days — pleasant for walking, no golden-hour visibility. A light layer in the morning.*

**Invented:** *cloud-led morning clearing by mid-afternoon, with peak humidity around 14:00 and a shower window between 15:00–17:00. Muggy along the Meguro River walk.*

The grounded version cites only daily high/low, daily PoP, daily weather code, and cross-day comparison — all in the fetched response. The invented version fabricates intra-day timing, humidity, and a feel judgment that nothing in the daily response supports.
</example>

Append an inline note to the `Forecast:` line when warranted:
- `precipitation_sum` ≥ 0.5" → `~X.X" expected.`
- `wind_speed_10m_max` ≥ 15 mph → `XX mph gusts.`
- `temperature_2m_max` ≥ 88°F and min ≥ 70°F → `Hot — muggy day.`
- Day clearly suits/contradicts a planned outdoor activity → one short clause (e.g. `Ideal cycling weather.`)

## Steps

1. **Resolve trip name** from `$ARGUMENTS`. If empty, list `Travel/*/` and ask. Then **detect layout** per § Layout: glob `Travel/<Trip>/**/Days/*.md` — non-empty match means per-day mode. Glob `Travel/<Trip>/**/Itinerary.md` to find the Itinerary.md file. Remember both resolved paths for the rest of the run.

2. **Read the day plans.** Always read the resolved `Itinerary.md` first — `weather_updated:` lives there. If ≥1 day old, mention "last updated N days ago"; if today, ask whether to refresh anyway. Then collect day entries per layout, **dropping any whose date is before today** — past days are out of scope (see § header). If every day in the trip is in the past, stop and tell the user the trip is over; don't fetch, don't stamp.

   **Single-file mode** — iterate `### <Month> DD …` H3 headings within Itinerary.md. For each, parse the date and infer location(s):
   - **Travel day** — heading has `<A> → <B>`, `Arrive <X>`, `Depart <X>`, or `Fly to <X>`. Origin = left/Depart; destination = right/Arrive.
   - **Single-location day** — defaults to the nearest preceding `## <Place>` section heading.

   **Per-day mode** — use the day-file paths from the Step 1 `**/Days/*.md` glob and read each. The `date:` frontmatter field is authoritative; the H1 `# <Month> DD …` provides the heading text for travel-day parsing. Skip past-dated day files entirely — don't even open them.
   - **Travel day** — same heading parsing as above (origin/destination from arrow / Arrive / Depart / Fly).
   - **Single-location day** — no `## <Place>` heading exists. Use the **Trip shape** table in `Itinerary.md` (segment name → date range) to look up which segment the date falls in. Map segment name to location (Tokyo I / Tokyo II → Tokyo, Kyoto → Kyoto, Kinosaki Onsen → Kinosaki Onsen, etc.). If the segment name is ambiguous, fall back to the daily index table's "Where" column.

3. **Resolve coordinates** for each unique location from the cache below. If missing, call `mcp__open-meteo__geocoding` and add the result to the cache by editing this SKILL.md in the same run.

4. **Pick the timezone** — IANA zone for the destination (`Asia/Tokyo`, etc.). The MCP takes one timezone per call; group locations by timezone if a trip crosses zones.

5. **Fetch Open-Meteo forecasts** — one `mcp__open-meteo__weather_forecast` call per unique location. `forecast_days` covers the span from today to the latest *remaining* (today-or-future) itinerary date (max 16). Never request historical days — the endpoint won't return them, and any past-dated itinerary entries were already filtered in Step 2. Pass:
   ```
   temperature_unit: fahrenheit
   precipitation_unit: inch
   wind_speed_unit: mph
   daily: ["weather_code", "temperature_2m_max", "temperature_2m_min",
           "precipitation_sum", "precipitation_probability_max",
           "wind_speed_10m_max"]
   ```

6. **Fetch local met office data** — for each location whose country appears in § Local met offices, fetch the country's endpoint (WebFetch) and extract per-date weather code, PoP, reliability, and min/max temps. If the country isn't mapped, **tell the user** in the kickoff message that they should update this skill to add coverage for the destination's local met office, then proceed with Open-Meteo-only Conditions prose for those locations.

7. **Build the Forecast line** from Open-Meteo. Map `weather_code` to emoji + label via the WMO table below. Round temps to whole °F. Use `precipitation_probability_max` for the `% rain` figure. Apply the inline-note rules above.

8. **Build the Conditions line** as one to three sentences of plain English prose describing how the day will feel. Every clause must trace to a value in the fetched data — see § Grounding above. Synthesize across sources:
   - **Sky character** — when the local met office is available, defer to its call (JMA `1xx` = sunny-led, `2xx` = cloudy-led, `3xx` = rain-led, `4xx` = snow-led). When sources disagree, the local source wins; surface the divergence ("cloudier than the numeric reading suggests").
   - **Temperature divergence** — if the local high is ≥3°F off from Open-Meteo's, mention it with both values implied.
   - **Reliability** — if the local source flags low confidence (JMA reliability B or C), append "Low-confidence outlook — recheck the morning of."
   - **Practical implication** — layer to wear, umbrella decision, fit with the day's plans — only when directly supported by the daily values. Skip intra-day timing claims unless you fetched hourly data.

9. **Insert / replace.** For each remaining (today-or-future) day, replace the existing pair(s) if present, otherwise insert immediately after the heading's blank line and before any `**Time Sensitive:**` / callout / prose. Use Edit with a unique `old_string` that anchors on the heading and the next stable line. **Never touch past-day Forecast/Conditions lines** — leave them as the frozen historical record of what was forecast going in.
   - **Single-file mode** — anchor on the `### <Month> DD …` H3 inside Itinerary.md.
   - **Per-day mode** — anchor on the `# <Month> DD …` H1 inside the day file. Note that the prev/next nav line sits *above* the H1 in per-day files — don't disturb it.

10. **Stamp `weather_updated:`** in `Itinerary.md` frontmatter with today's date as `"YYYY-MM-DD"`. Add it after `created:` if missing; replace the value if present. Leave other frontmatter (and per-day file frontmatter, if applicable) untouched.

11. **Report a one-paragraph summary** flagging notable signals: rainy days affecting outdoor plans, heat peaks, wind for open-air events, low-confidence days, anything that should change a day's shape. Note any forecast values >10 days out as directional-only.

## WMO weather code → emoji + label

| Code | Emoji | Label |
|---|---|---|
| 0 | ☀️ | clear |
| 1 | 🌤 | mainly clear |
| 2 | ⛅ | partly cloudy |
| 3 | ☁️ | overcast |
| 45, 48 | 🌫 | fog |
| 51 | 🌦 | light drizzle |
| 53 | 🌦 | moderate drizzle |
| 55 | 🌦 | dense drizzle |
| 56, 57 | 🌧 | freezing drizzle |
| 61 | 🌧 | light rain |
| 63 | 🌧 | moderate rain |
| 65 | 🌧 | heavy rain |
| 66, 67 | 🌧 | freezing rain |
| 71, 73, 75, 77 | ❄️ | snow |
| 80, 81, 82 | 🌧 | rain showers |
| 85, 86 | ❄️ | snow showers |
| 95 | ⛈ | thunderstorm |
| 96, 99 | ⛈ | thunderstorm w/ hail |

## Coordinate cache

Per-trip lookup tables. Extend in-place when running against a new trip. Keys are place names that appear in itinerary headings or `## <Section>` anchors.

### Japan26 (`Asia/Tokyo`)

| Place | Lat, Lng |
|---|---|
| Tokyo | 35.6762, 139.6503 |
| Kyoto | 35.0116, 135.7681 |
| Kinosaki Onsen | 35.6242, 134.8083 |

## Local met offices

Per-country mapping. When running the skill against a trip in an uncovered country, tell the user up front to update this section before the next run, then fall back to Open-Meteo-only Conditions prose.

### Japan — JMA

**Endpoint:** `https://www.jma.go.jp/bosai/forecast/data/forecast/<area_code>.json` (no auth, WebFetch).

**Parse:** `timeSeries[0]` = 3-day weather codes per area; `timeSeries[2]` = temps min/max; the 7-day block (often `timeSeries[3]` or the second top-level entry) has `weatherCodes`, `pops`, `reliabilities`, `tempsMin`, `tempsMax`. Temps are °C — convert to °F.

**JMA weather code prefix:** `1xx` sunny-led, `2xx` cloudy-led, `3xx` rain-led, `4xx` snow-led.

**Reliability:** A = high, B = medium, C = low. B or C → flag in Conditions prose.

**Area codes** (find new ones at `https://www.jma.go.jp/bosai/common/const/area.json`, look under `offices`):

| Place | Prefecture | Area code |
|---|---|---|
| Tokyo | Tokyo-to | 130000 |
| Kyoto | Kyoto-fu | 260000 |
| Kinosaki Onsen | Hyogo-ken | 280000 |

## Reliability caveat

Open-Meteo's daily forecast is reliable through ~day 7–10; past that, values are directional only. JMA's 7-day block cuts off at day 7 entirely. Mention dates >10 days out as directional in the post-run summary. When a local met office flags reliability B or C, surface that in the day's Conditions prose.

## Conventions to keep

- **Today-or-future only.** Past days are out of scope at every step — don't read them, don't fetch for them, don't rewrite their existing pair. See § header.
- Only touch the italic `Forecast:` / `Conditions:` pair under day headings — `### <Month> DD …` (single-file) or `# <Month> DD …` (per-day). Leave Time Sensitive tables, callouts, prev/next nav lines, and prose alone.
- Skip non-day headings — in single-file mode that's `##` section headings (`## Bookings`, `## Tokyo I`, `## Fly Home`); in per-day mode that's the daily-index / Bookings / Alternatives content in `Itinerary.md`, none of which are day-headed. Day files in `Days/` always have exactly one `# <Month> DD …` H1 — that's the anchor.
- Fetch each unique location once per source, covering the full date range; index into that single response across days.
- Keep Conditions prose neutral — refer to the numeric Forecast line as "the numeric reading"; never name a data source.
- Always emit the pair when a met office is mapped. Conditions prose stays valuable even without a local source — write it from Open-Meteo alone, and tell the user to extend § Local met offices for next time.
