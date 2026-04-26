---
name: restaurant
description: Log a restaurant visit or add a new restaurant to track
user_invocable: true
---

# Restaurant Logger

Log a restaurant visit or add a new restaurant to the tracker. Can also be triggered conversationally when the user mentions eating somewhere.

## Steps

1. **Parse the restaurant name** from `$ARGUMENTS` or the user's message. If unclear, ask.

2. **Check if a note exists** — run `obsidian search query="$NAME" format=json` and check `Restaurants/` for a match.

3. **If the note doesn't exist**, create it:
   - **Search the web** for the restaurant to get: cuisine, neighborhood, city, address, hours, price range, website, whether reservations are needed.
   - Create the note at `Restaurants/$NAME.md` using the Restaurant template frontmatter.
   - Fill in all properties from web research. Leave `rating`, `vibe`, and `rec-for-friends` for the user.
   - Add practical details (address, hours) to the Notes section.
   - **Geocode** the file: `scripts/vault-tool geocode lookup --file "Restaurants/$NAME.md" --write --enrich`
     (For local restaurants, `--enrich` is reliable — Google hours are generally accurate domestically. Verify hours against the website for international venues.)

4. **If the note exists**, read it to see current state.

5. **Log the visit** (if the user described one):
   - Add a dated entry to the Visits section with who they went with ([[wikilinks]]) and what they had.
   - Update `status` to `been` if it was `want-to-try`.
   - Update `last-visited` to the visit date.

6. **Ask the user** for anything missing:
   - Rating (1-5, 5 = best) if they've been and haven't rated yet
   - Vibe description if blank
   - Whether to flag as rec-for-friends

7. **Proactively connect context** (per CLAUDE.md rule 6):
   - Check if people mentioned have People/ notes. If not, ask if the user wants to create them.
   - If the restaurant relates to a trip (e.g. Japan 2026), note the connection.

## File operations

Use the `obsidian` CLI where possible. Fall back to direct file operations when the CLI doesn't support the operation.
