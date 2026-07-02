---
description: How to write and scope Claude Code config in this setup (CLAUDE.md, rules, skills, hooks)
paths:
  - "CLAUDE.md"
  - ".claude/**"
---

# Config authoring

## Scope discipline

- CLAUDE.md (project or user) holds only what must load on every prompt. Before adding
  a line, ask: would removing it cause mistakes in most sessions? Sometimes-relevant
  guidance goes in a path-scoped rule; task workflows go in a skill; anything that must
  run at a fixed event goes in a hook.
- `~/.claude/rules/` stays empty on purpose (emptied 2026-07-02). User-level rules load
  unconditionally (`paths:` is honored only in project rules), so anything needing
  scope belongs in a project's `.claude/rules/`. Git commit conventions live in the
  `git-conventions` user skill; don't recreate the deleted global rules.
- Rule `paths:` frontmatter takes glob values (`Travel/**`, `**/*.py`, brace expansion
  allowed). Path-scoped rules inject when a matching file is read, not at launch.
- Launch sessions from the vault or repo root. A subdirectory launch loses every
  project rule (only ancestor CLAUDE.md files walk up).

## The two-repo seam

The Aesc vault's `CLAUDE.md`, `.claude/`, and `scripts/` are symlinks into
`~/Projects/munin`. Edits land in munin either way; git operations happen in munin,
and nothing gets committed there unless Ash asks.

## Writing instructions

- Lead with positive directives and show only correct examples. A "bad example" block
  in a rule reads as a pattern to match when instructions are taken literally; name
  the failure in prose instead of quoting it.
- All config prose follows `.claude/rules/writing.md` (plain punctuation, no
  AI-slop tells).
