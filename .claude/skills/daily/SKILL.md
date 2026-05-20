---
name: daily
description: Create or open today's daily journal entry
user_invocable: true
---

# Daily Journal

Create or open today's daily journal entry. Entries live at `Daily/YYYY-MM-DD.md`.

## Steps

1. **Compute today's path** — `Daily/$(date +%Y-%m-%d).md` under the vault root. Absolute form: `/Users/wash/Library/Mobile Documents/iCloud~md~obsidian/Documents/Aesc/Daily/YYYY-MM-DD.md`.

2. **Read the path with the Read tool** to check whether the file exists. If it does, present the contents and skip to step 5.

3. **Create from the template** when the file is new:
   - Read `Templates/Daily Journal.md`.
   - Resolve Templater expressions:
     - `<% tp.date.now('YYYY-MM-DD') %>` → today's ISO date.
     - `<% tp.date.now('dddd, MMMM D, YYYY') %>` → e.g. `Tuesday, May 19, 2026`.
     - `<% tp.file.cursor() %>` → omit (editor-only).
   - Write the resolved content to `Daily/YYYY-MM-DD.md` via the Write tool.

4. **Open it in Obsidian** with `obsidian open path="Daily/YYYY-MM-DD.md"`.

5. **Ask the user what they'd like to add or reflect on.** Use the Edit tool against `Daily/YYYY-MM-DD.md`. Preserve Ash's voice per `.claude/rules/daily.md` — Zone 1 (above `---`) is his verbatim prose; Zone 2 (`## Links & Connections`) is Claude's synthesis.

## Backfill mode

When backfilling missing days:

1. For each missing date, write the template-resolved scaffold to `Daily/YYYY-MM-DD.md`.
2. Set `created:` to today's actual date (the day the file was written) and `date:` to the day being documented. These differ honestly for backfills.
3. Leave Zone 1 sections empty and let Ash fill them in himself. Populate Zone 2 from the corresponding `Travel/<Trip>/Itinerary/Days/<...>.md` file when one exists.

## Stray-file recovery

When a daily file appears outside `Daily/`, consolidate it into `Daily/YYYY-MM-DD.md`:

1. Compare the stray file to its `Daily/` counterpart (Read both, or `diff`).
2. If the stray is empty or identical to the canonical version: remove the stray with `obsidian delete path="YYYY-MM-DD.md"` (sends to trash, recoverable).
3. If the stray has unique content: merge its prose verbatim into the `Daily/` version (preserving Ash's voice), then remove the stray.

## Rules

- **Address daily files by their explicit `Daily/YYYY-MM-DD.md` path** for every Read, Write, Edit, and `obsidian open path="..."`.
- **Preserve Ash's voice** — Zone 1 verbatim, Zone 2 synthesis (`.claude/rules/daily.md`).
- **Leave Zone 1 empty on backfills** — let Ash fill it in.
