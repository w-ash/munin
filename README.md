# munin

Personal Obsidian + Claude Code tooling. The vault content is private and lives elsewhere; this repo holds only the pieces I'm comfortable sharing — conventions, skills, and the Python helpers that operate on the vault.

Named after Odin's raven of memory.

## What's in here

```
.claude/
  rules/      ← schema/convention rules loaded alongside CLAUDE.md
  skills/     ← slash commands + tool skills (see Skills below)
CLAUDE.md     ← top-level project instructions for Claude Code
scripts/      ← Python helpers (uv-managed)
  vault-tool             dispatcher
  vault_scripts/         entry-point modules + private helpers
  pyproject.toml         dependencies + ruff/basedpyright config
  uv.lock                pinned versions
  .python-version        3.14
```

The pattern: vault content (Daily/, Travel/, People/, Finance/, etc.) stays in iCloud Drive on a private path. This repo's `CLAUDE.md`, `.claude/`, and `scripts/` are symlinked into the vault root so Claude Code and the dispatcher work transparently when launched from the vault.

## Bootstrap on a new Mac

```bash
cd ~/Projects
git clone git@github.com:<you>/munin.git
cd munin/scripts
cp .env.example .env  # then fill in GOOGLE_MAPS_API_KEY
uv sync               # builds local venv (location set by UV_PROJECT_ENVIRONMENT in vault-tool)
```

Then in your Obsidian vault root, create symlinks pointing back to this repo:

```bash
cd "<your vault>"
ln -s ~/Projects/munin/CLAUDE.md CLAUDE.md
ln -s ~/Projects/munin/.claude .claude
ln -s ~/Projects/munin/scripts scripts
```

The dispatcher resolves through symlinks; everything else just works.

## Why a separate repo, not the whole vault

Two reasons:

1. **Content is private; tooling is showable.** A two-repo split makes it physically impossible to leak vault notes — git literally cannot see them.
2. **iCloud and git don't mix.** Putting `.git/` inside iCloud creates the same lazy-materialization problem that breaks Python venvs after machine moves. Keeping the repo at `~/Projects/munin/` (outside iCloud) means git internals stay healthy.

The venv lives outside iCloud too — `vault-tool` sets `UV_PROJECT_ENVIRONMENT=$HOME/.local/share/uv/envs/vault-scripts`. Sync only `pyproject.toml` + `uv.lock`; let each machine build its own venv.

## Skills

| Skill | Purpose |
|-------|---------|
| `/daily` | Open or create today's daily journal entry |
| `/person` | Create or enrich a person note from Apple Contacts |
| `/restaurant` | Log a visit or add a new restaurant to track |
| `/triage` | Walk through incomplete todos across the vault |
| `/trip` | Vacation planning session loader |
| `/weather` | Refresh per-day forecast lines in a trip's day plans |
| `google-docs` | Read and edit Google Docs via `vault-tool docs` |
| `google-sheets` | Read and update Google Sheets via `vault-tool sheets` |
| `print-one-pager` | Build print-ready single-page HTML/PDF documents |

## Dispatcher commands

```bash
scripts/vault-tool                          # list available modules
scripts/vault-tool geocode lookup --file "<path>" --write
scripts/vault-tool geocode batch <Trip> --stations --write
scripts/vault-tool style_audit <Trip>
scripts/vault-tool sync_contacts
scripts/vault-tool docs export <doc-id-or-url>
scripts/vault-tool sheets read-table --spreadsheet <id>
scripts/vault-tool cover_image --file "<path>" --url "<image-url>"
```

See `scripts/vault_scripts/` for the full list. Module docstrings explain each one.

## Type discipline

`basedpyright` strict, 0 errors / 0 warnings across the whole package. See `.claude/rules/scripts.md` for the conventions.

## License

Apache-2.0. See `LICENSE`.
