# Personal Vault: CLAUDE.md

This is Ash Wright's personal knowledge base. It is managed with Obsidian and is NOT a code project.

## Vault Structure

```
Archive/           → Old/completed content moved here for reference
Career/            → Job search materials, company research, portfolio pieces
Daily/             → Daily journal entries
Finance/           → Budget, bills, financial planning
Health/            → Fitness logs, health tracking, goals; provider notes (#provider) in Providers/entries/ (Providers.base); supplement notes (#supplement) in Supplements/entries/ (Supplements.base), regimen hub Stack.md
Homes/             → Candidate home-buy notes (#home) in entries/ (Homes.base); shared rubric + weights in Criteria.md
Ideas/             → Explorations, things to investigate
Meta/              → Human-facing docs on how the vault + its tooling are structured (storage framework: Trackers.md; data-placement rule: .claude/rules/trackers.md)
Ontology/          → Knowledge notes (#ontology) in entries/, sources (#source) in sources/ (Entries.base, Sources.base)
People/            → Person notes (#person) in entries/ (People.base)
Pets/              → Pet notes (#pet) in entries/ (Pets.base)
Projects/          → Project summaries and plans (#project)
Restaurants/       → Local restaurant notes (#restaurant) in entries/ (All Restaurants.base)
Shops/             → Local shop notes (#shop) in entries/ (All Shops.base)
Templates/         → Note templates
Todos/             → Weekly todo files, Backlog.md, Routines.md
Travel/            → Trip planning; one folder per trip with a hub note + category subfolders/bases
Work/              → Work notes (staging; move to work vault when ready)
```

Entity folders share one shape: a `<Name>.base` at the folder root over an `entries/` subfolder holding the tagged notes (People, Pets, Restaurants, Shops, Ontology).

## Frontmatter Convention

All notes should include a `created` date in YAML frontmatter as a permanent record that survives any file operation:
```yaml
created: "YYYY-MM-DD"
```

## Obsidian CLI

CLI 1.12+ at `/usr/local/bin/obsidian`. Prefer it for moves, renames, and base queries (preserves wikilinks + index). Frontmatter writes go through `vault-tool fm` or the Edit tool, never `property:set` (which reserializes the block and drops convention quotes).

- **`key=value`, not `--flag`.** See rule #9.
- **`create` takes `name=` or `path=`, not `file=`**. `file=` is for existing files; on `create` it drops and you get `Untitled.md`.
- **No `silent` flag.** Omit `open`/`newtab` to avoid focus steal.
- `file=` resolves by name (like wikilinks); `path=` is exact. `format=json` on most read commands.

Full reference: `obsidian:obsidian-cli` skill.

## Bases

`.base` files create database-like table views over vault notes. They filter by tag (e.g. `file.hasTag("restaurant")`) or by folder (`file.inFolder(...)`, which includes subfolders), display properties as columns, and support formula columns and per-view filters. Used in:
- `People/`: People.base · `Pets/`: Pets.base
- `Restaurants/`: All Restaurants.base · `Shops/`: All Shops.base
- `Health/Providers/`: Providers.base · `Health/Supplements/`: Supplements.base
- `Ontology/`: Entries.base, Sources.base
- `Travel/<Trip>/`: per-trip Destinations, Experiences, Dining, Shopping comparison tables

## Web Search vs Defuddle

- **WebSearch** is the default for looking things up online. Use it first.
- **Defuddle** (`obsidian:defuddle`) is only for two cases:
  1. WebSearch failed or returned unusable results, and you need to fetch a specific URL as fallback.
  2. The user explicitly asks to grab a URL and convert it to markdown.
- Never use Defuddle as a substitute for WebSearch.

## Rules

<important>
1. **Move, don't delete.** Use `obsidian move`/`obsidian rename`. Never delete+recreate; it destroys creation date.
2. **Preserve file metadata.** Creation dates are meaningful. Never reset timestamps.
3. **Use `[[wikilinks]]`** for all entity references. Check if related notes exist; offer to create or update them.
4. **Ask before reorganizing.** Propose a plan and get approval before moving/restructuring files.
5. **Don't modify shared Base files** (*.base outside Templates/) without asking.
6. **Plan mode is read-only.** No obsidian write commands (`create`, `append`, `prepend`, `move`, `rename`, `delete`, `property:set`, `property:remove`, `task` mutations, `base:create`, `history:restore`) during plan mode.
7. **Search the web** for factual details rather than relying on training data.
8. **Preserve Ash's voice.** When capturing his words (chat dictation or direct typing), keep them verbatim, with no edits, no injected wikilinks, no typo fixes. Claude's synthesis (wikilinks, structured summaries) goes in a clearly-marked section below, not interleaved. See `.claude/rules/daily.md` for the full convention; same default applies to Ideas, Projects, Restaurants visits, and any note built from chat.
9. **Obsidian-CLI uses `key=value` args.** For help: `obsidian help daily`, `obsidian help create`. For args: `obsidian daily path="Daily/2026-05-19.md"`, `obsidian create name="My Note"`. Other syntaxes silently drop the arg while still firing the subcommand.
10. **Write in plain punctuation.** In prose Claude writes (summaries, note bodies, synthesis, chat replies), use periods, commas, colons, semicolons, and parentheses, keeping en dashes for numeric ranges. This keeps em dashes and other AI-slop tells out of the writing so it reads as Ash's own. Full standard in `.claude/rules/writing.md`. Ash's verbatim words stay exactly as written (rule #8).
</important>
