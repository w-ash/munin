---
description: "Obsidian .base file gotchas: silent-failure traps the docs don't make obvious"
paths:
  - "**/*.base"
---

# Bases

Five traps that fail silently (no error, no warning, just no effect). Verify each before debugging anywhere else.

## 1. Marker fields are `markerColor` / `markerIcon`

The Maps plugin uses camelCase keys with a `marker` prefix. Plain `color:` / `icon:` are silently ignored.

```yaml
- type: map
  markerColor: formula.type_color   # NOT color:
  markerIcon: formula.type_icon     # NOT icon:
```

## 2. Filter YAML uses `and:` / `or:`. Formula expressions use `&&` / `||`

The two contexts use different operator vocabularies; mismatched syntax produces silent no-ops.

```yaml
filters:                                  # YAML: use and: / or: as keys
  and:
    - or:
        - file.hasTag("dining-option")
        - file.hasTag("experience-option")

formulas:                                 # expression: use && / ||
  type_color: if(note.type == "cafe" || note.type == "kissaten", "#92400E", "#9CA3AF")
```

The wrapper is required at **both** top-level and view-level `filters:` blocks; bare lists fail with `"filters" may only have one of an "and", "or", or "not" keys`.

## 3. Inline expressions in view fields are ignored; hoist to `formulas:`

Putting `if(...)` directly in `markerColor:` or any other view field does nothing. Define once under `formulas:`, reference as `formula.<name>`.

## 4. `this.file` in a filter is the *active* file, not the base

A filter like `file.inFolder(this.file.folder)` ("show notes in my own folder") only works while the base is the open, focused file. `this.file` resolves to whatever file is currently active, so the same filter returns nothing when the base is embedded in a hub note (it sees the hub) or queried headlessly via `obsidian base:query` (it sees the last-open file). Prefer a tag filter (`file.hasTag("restaurant")`): it resolves the same everywhere and survives moving notes into an `entries/` subfolder. `file.inFolder("Notes")` matches the folder *and its subfolders*, so excluding templates needs an explicit `not: [file.inFolder("Templates")]`.

## 5. A `/` in a frontmatter value never matches its filter

Filters compare whole values, so a compound like `cuisine: "Bakery / Sweets"` matches neither a `Bakery` nor a `Sweets` filter and the note silently drops out of the view. This is vault-wide, for every frontmatter field, not a per-category rule: pick one canonical primary value and note the straddle in the note body. A field that genuinely holds multiple values is a list (`["A", "B"]`), never a slash-joined string.

## Diagnostic recipe

Add the formula as a column to any table view (`formula.<name>`). What you see tells you which trap you hit:

| Cell shows | Trap |
|---|---|
| Hex codes / icon names | Formula compiles → the view field name is wrong (back to #1) |
| Empty | Formula doesn't compile → operators (#2) or unbalanced parens |
| Literal formula text | YAML quoting issue → re-save in Obsidian to normalize |

## Other quick conventions

- Filter property refs are bare (`status != "ruled-out"`); `properties:` and `order:` use `note.` prefix.
- Icon values are Lucide kebab-case (`coffee`, `landmark`); React-style `LiCoffee` doesn't render.
- Coordinates: see `.claude/rules/geo.md` (single `"lat, lng"` string).
