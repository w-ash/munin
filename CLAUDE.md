# Personal Vault — CLAUDE.md

This is Ash Wright's personal knowledge base. It is managed with Obsidian and is NOT a code project.

## Vault Structure

```
Archive/           → Old/completed content moved here for reference
Career/            → Job search materials, company research, portfolio pieces
Daily/             → Daily journal entries
Finance/           → Budget, bills, financial planning
Health/            → Fitness logs, health tracking, goals
Ideas/             → Explorations, things to investigate
People/            → Person notes (tagged #person) in entries/, with People.base and Pets.base views
Projects/          → Active project plans with concrete implementation steps
Restaurants/       → Restaurant notes (tagged #restaurant), with Bases views for tracking
Templates/         → Note templates
Todos/             → Weekly todo files, Backlog.md, Routines.md
Work/              → Work notes (staging — move to work vault when ready)
```

## Frontmatter Convention

All notes should include a `created` date in YAML frontmatter as a permanent record that survives any file operation:
```yaml
created: "YYYY-MM-DD"
```

## Obsidian CLI

The Obsidian CLI (1.12+) is available. **Prefer CLI commands over raw file operations** — the CLI respects Obsidian's index, auto-updates wikilinks on move, and preserves metadata. Use `format=json` for machine-readable output.

Notes: `file` resolves by name (like wikilinks), `path` is exact. Use `format=json` where available.

Use the `obsidian:obsidian-cli` skill for full command reference. Always pass `silent` on create/modify commands to prevent Obsidian from stealing focus.

## Bases

`.base` files create database-like table views over vault notes. They filter by tag (e.g. `file.hasTag("restaurant")`), display properties as columns, and support formula columns and per-view filters. Used in:
- `People/` — People.base, Pets.base
- `Restaurants/` — All Restaurants, Want to Try, Favorites, Recs for Friends
- `Travel/Japan26/` — Destinations, Experiences, Dining, Shopping comparison tables

## Web Search vs Defuddle

- **WebSearch** is the default for looking things up online. Use it first.
- **Defuddle** (`obsidian:defuddle`) is only for two cases:
  1. WebSearch failed or returned unusable results, and you need to fetch a specific URL as fallback.
  2. The user explicitly asks to grab a URL and convert it to markdown.
- Never use Defuddle as a substitute for WebSearch.

## Rules

<important>
1. **Move, don't delete.** Use `obsidian move`/`obsidian rename`. Never delete+recreate — destroys creation date.
2. **Preserve file metadata.** Creation dates are meaningful. Never reset timestamps.
3. **Use `[[wikilinks]]`** for all entity references. Check if related notes exist; offer to create or update them.
4. **Ask before reorganizing.** Propose a plan and get approval before moving/restructuring files.
5. **Don't modify shared Base files** (*.base outside Templates/) without asking.
6. **Plan mode is read-only.** No obsidian write commands (`create`, `append`, `prepend`, `move`, `rename`, `delete`, `property:set`, `property:remove`, `task` mutations, `base:create`, `history:restore`) during plan mode.
7. **Search the web** for factual details rather than relying on training data.
8. **Preserve Ash's voice.** When capturing his words (chat dictation or direct typing), keep them verbatim — no edits, no injected wikilinks, no typo fixes. Claude's synthesis (wikilinks, structured summaries) goes in a clearly-marked section below, not interleaved. See `.claude/rules/daily.md` for the full convention; same default applies to Ideas, Projects, Restaurants visits, and any note built from chat.
</important>
