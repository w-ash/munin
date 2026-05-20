---
name: tabelog-hyakumeiten
description: Fetch Tabelog 百名店 (Hyakumeiten / Top 100) award lists by category and region. Use during dining tier passes that need editorial-grade source signals — sushi_tokyo, ramen_tokyo, soba, sushi_west, etc. — or when the user mentions "Hyakumeiten / Tabelog top 100 / award.tabelog.com."
user_invocable: true
---

# Tabelog Hyakumeiten lists

`award.tabelog.com/hyakumeiten/<genre>_<region>/<year>` returns the editorial Top 100 list for that genre and region. These are SS/S-tier sourcing signals (Tabelog editorial, distinct from user-score noise) and underpin most dining tier passes.

## Steps

1. **Build the URL** — pattern is `https://award.tabelog.com/hyakumeiten/<genre>_<region>/<year>`. Examples: `sushi_tokyo/2025`, `ramen_tokyo/2025`, `soba/2025` (no region for nationwide categories), `sushi_west/2025`.

2. **Fetch with realistic browser headers** — no anti-bot block, but bare `curl` defaults sometimes return abbreviated content:
   ```bash
   curl -sSL --compressed \
     -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' \
     -H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8' \
     -H 'Accept-Language: ja,en-US;q=0.9,en;q=0.8' \
     -H 'Sec-Fetch-Dest: document' -H 'Sec-Fetch-Mode: navigate' -H 'Sec-Fetch-Site: none' -H 'Sec-Fetch-User: ?1' \
     -H 'Upgrade-Insecure-Requests: 1' \
     "https://award.tabelog.com/hyakumeiten/<genre>_<region>/<year>" -o /tmp/hyakumeiten_raw.html
   ```

3. **Parse the raw HTML.** Each venue is in `<div class="hyakumeiten-shop__item">` containing:
   - `<div class="hyakumeiten-shop__name">NAME</div>`
   - `<div class="hyakumeiten-shop__area"><span>PREFECTURE STATION CLOSED-DAYS</span></div>`
   - An anchor `href="https://tabelog.com/<region>/A<area>/A<subarea>/<venue-id>/"`

   A ~30-line Python regex extraction handles 100 venues cleanly.

4. **Use the venue IDs and station/area data** to drive tier-pass `recommended_by` updates and Sources citations on existing files; create new option files for venues not yet in the vault.

## Critical do-nots

- **Do NOT pipe through `defuddle`.** Defuddle treats the venue list as nav chrome and strips it, leaving only the magazine carousel article. Parse raw HTML directly.
- **Do NOT use WebFetch.** Same article-extraction approach as defuddle — returns the SPA shell only, not the venue list.

## Last confirmed

2026-05-01 on `award.tabelog.com/hyakumeiten/sushi_tokyo/2025` (returned 362 KB, 100 unique venues). Recipe should generalize to all `<genre>_<region>/<year>` permutations.
