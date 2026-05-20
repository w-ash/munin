---
name: tabelog-photos
description: Pull interior cover images for Japanese dining venues from Tabelog's 雰囲気 (atmosphere) subset. Use when adding or refreshing cover images on `dining-option` files for a Japan trip, or when the user mentions "cover images for venues / Tabelog photos / interior shots."
user_invocable: true
---

# Tabelog atmosphere photos

For interior cover images on Japanese dining venues, Tabelog's 雰囲気 (atmosphere) subset at `/dtlphotolst/3/smp2/` is the workhorse — editor-curated for interior shots. Editorial sources (Time Out, Inside Kyoto, dancyu) rarely include venue interiors; venue websites are unreliable; Google Maps photos are user-submitted chaos.

## Steps

1. **Find the venue's Tabelog ID.** Often in the file's frontmatter or body. If not, WebSearch `<name_jp> <neighborhood> tabelog`.

2. **Fetch the atmosphere page with the Mac Safari UA** — `Mozilla/5.0` alone gets blocked:
   ```bash
   UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'
   /usr/bin/curl -sA "$UA" "https://tabelog.com/<region>/<area1>/<area2>/<id>/dtlphotolst/3/smp2/" --max-time 30 -o /tmp/page.html
   ```

3. **Verify the page title matches the venue.** Vault files have been observed with wrong Tabelog IDs (3 in 70 files: Tempura Kondo's body link is Taimeian; Tempura Takiya's is a closed ramen shop; Yoshikawa's is a Maizuru sushi place). Always grep the `<title>` before trusting an ID.

4. **Extract photo URLs — must include hex-hash filenames, not just digit IDs:**
   ```bash
   grep -oE 'tblg\.k-img\.com/restaurant/images/Rvw/[0-9]+/[0-9]+x[0-9]+_(rect|square)_[a-z0-9]+\.jpg' /tmp/page.html
   ```
   Modern Tabelog uploads use hex hashes (e.g. `415ca54f69dca76ddd0a78771ab5adae.jpg`) instead of integers. A digits-only regex silently misses ~half the photos on newer venues.

5. **Strip the size prefix to get the bare-ID original** (full resolution, often 1200–2000px wide):
   `Rvw/12345/640x640_rect_12345067.jpg` → `Rvw/12345/12345067.jpg`

6. **Apply via the vault script:**
   ```bash
   scripts/vault-tool cover_image --file <path> --url <bare-id-url> --write
   ```
   Run from the Aesc vault (the symlinked working dir that preserves `VAULT_DIR`), not from `/Users/wash/Projects/munin/`.

## Edge cases

- **No photos / thumbnails only.** Skip when the atmosphere page has no photos at all (very new venues), or only square thumbnails ≤320px and the bare-ID URL 404s.
- **No-photos-inside venues.** For sushi/tempura/yakitori counters with strict "no photos inside" rules, `/3/` often returns food shots only — accept the food shot as cover (Yakitori Kasahara, Sukiyabashi Jiro, Sushi Saito all fell back this way).
- **Shell quirk.** `for f in ...; do <pipe with head/grep>; done` can lose `PATH` for inner commands in this harness. Run individual commands instead of looping.
