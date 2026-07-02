---
name: daily
description: Create or open today's daily journal entry. Use for /daily, journaling, reflecting, or logging what happened today.
user_invocable: true
---

# Daily Journal

Create or open today's daily journal entry. Entries live at `Daily/YYYY-MM-DD.md`.

## Steps

1. **Compute today's path**: `Daily/$(date +%Y-%m-%d).md` under the vault root. Absolute form: `/Users/wash/Library/Mobile Documents/iCloud~md~obsidian/Documents/Aesc/Daily/YYYY-MM-DD.md`.

2. **Read the path with the Read tool** to check whether the file exists. If it does, present the contents and skip to step 5.

3. **Create the note when it's new.** Prefer the native path; fall back to a manual write.
   - **Native (Obsidian running):** run `obsidian daily`. This fires Obsidian's own daily-note command, which Templater intercepts via its `Daily` folder template, so every `<% %>` expression resolves (including the cursor) with no hand-resolution, and the note opens. Then Read `Daily/YYYY-MM-DD.md` to confirm it landed and present its contents.
   - **Fallback (Obsidian not running, or `obsidian daily` produced no file):** Read `Templates/Daily Journal.md` and resolve the Templater expressions with `date` (don't format dates by hand):
     - `<% tp.date.now('YYYY-MM-DD') %>` → `$(date +%Y-%m-%d)`
     - `<% tp.date.now('dddd, MMMM D, YYYY') %>` → `$(date "+%A, %B %-d, %Y")`
     - `<% tp.file.cursor() %>` → omit (editor-only).

     Write the resolved content to `Daily/YYYY-MM-DD.md`, then open it with `obsidian open path="Daily/YYYY-MM-DD.md"`.

4. **Ask the user what they'd like to add or reflect on.** Use the Edit tool against `Daily/YYYY-MM-DD.md`. Preserve Ash's voice per `.claude/rules/daily.md`: Zone 1 (above `---`) is his verbatim prose; Zone 2 (`## Links & Connections`) is Claude's synthesis.

## Backfill mode

When backfilling missing days, always use the manual write path (the Write tool), never `obsidian daily`; the native command stamps today's date and can't backdate.

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
- **Preserve Ash's voice**: Zone 1 verbatim, Zone 2 synthesis (`.claude/rules/daily.md`).
- **Leave Zone 1 empty on backfills**: let Ash fill it in.
