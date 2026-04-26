---
name: daily
description: Create or open today's daily journal entry
user_invocable: true
---

# Daily Journal

Create today's daily journal entry if it doesn't exist, or open it if it does.

## Steps

1. **Check for today's entry** — run `obsidian daily:read` to see if today's note exists.

2. **If it doesn't exist**, create it from the template:
   - Read `Templates/Daily Journal.md` to get the current template.
   - Resolve Templater expressions before writing:
     - `<% tp.date.now('...') %>` — format today's date using the given format string (moment.js: `YYYY`, `MM`, `DD`, `dddd`, `MMMM`, `D`, etc.)
     - `<% tp.file.cursor() %>` — remove (cursor placement, not relevant for CLI)
   - Write the resolved content to `Daily/YYYY-MM-DD.md` using the Write tool.

3. **If it exists**, read and present its contents.

4. **Open it** — run `obsidian daily` to open the note in Obsidian.

5. **Ask the user** what they'd like to add or reflect on. Use the Edit tool to add content (not `obsidian daily:append`, which targets the vault root instead of the `Daily/` folder).
