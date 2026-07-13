---
description: Standards for Python scripts in scripts/
paths:
  - "scripts/**"
---

# Vault Scripts

Package at `scripts/vault_scripts/`. Invoke via `scripts/vault-tool <module> [args]` (bash dispatcher; passes `.env` through `uv run --env-file`). Private modules (`_`-prefixed) are auto-filtered from the dispatcher's module list.

The `sheets` module (Google Sheets read/write) has a user-facing skill: see `.claude/skills/google-sheets/` for its command surface, the two auth modes (OAuth-user by default, `--auth service` for the shared service account), and dry-run-before-write workflow.

## Layout

```
scripts/
├── pyproject.toml     # deps + ruff + basedpyright config
├── vault-tool         # dispatcher
├── typings/           # hand-written .pyi stubs for untyped deps
└── vault_scripts/
    ├── _retry.py      # tenacity + request_json + APIError
    ├── _types.py      # Pydantic + TypedDict + dataclass hub
    ├── _utils.py      # frontmatter + env + CLI helpers
    └── <module>.py    # entry-point scripts
```

## Type discipline

`basedpyright` strict across the whole package stays at **0 errors, 0 warnings**. Don't suppress; fix.

- **Pydantic**: API response boundaries, `extra="ignore"` (catches schema drift).
- **TypedDict**: internal dict shapes. Default `total=True` unless keys are truly optional.
- **`@dataclass`**: config + intermediate structures.
- **No `Any`**: narrow `resp.json()` → `object` at the boundary, validate via Pydantic.
- **Untyped deps**: write narrow stubs in `scripts/typings/<pkg>/__init__.pyi` (start with `basedpyright --createstub`, trim). No `useLibraryCodeForTypes`.

Add new models / TypedDicts / dataclasses to `_types.py`, not to entry-point scripts.

## Patterns

- **HTTP**: all external calls go through `request_json()` in `_retry.py` with `@google_retry` or `@overpass_retry`. Callers catch `APIError` (bundles `RequestException` + `ValidationError`).
- **Env**: `require_env("NAME")` from `_utils`. Never load `.env` in Python; the dispatcher handles it.
- **CLI**: argparse with a typed `_Args(argparse.Namespace)` subclass; parse via `parse_typed_args(parser, _Args)` to avoid per-field `# pyright: ignore`.
- **File discovery**: `find_entry_files()` returns `(path, post, category, raw_text)`; don't re-read.
- **Frontmatter I/O**: `patch_field`, `insert_field_after`, `yaml_scalar` from `_utils`; `fm.py` is the CLI over them (`vault-tool fm set`) for bulk edits from outside Python.
- **iCloud write races**: the vault syncs through iCloud, so rapid writes to one file (a Write plus a `geocode` pass plus follow-up Edits in the same turn) can race and corrupt frontmatter (doubled keys, truncated body). Sequence writes to the same file, spot-check after batch runs (`grep -c` on keys that should appear once, `wc -l`), and recover a corrupted file with one full Write, not piecemeal Edits.
- **Batch `obsidian move`**: moving many files into a freshly created folder can leave the first few unindexed (correct on disk, missing from Bases views and `search`). Verify the batch landed with `obsidian search` or a tag-filtered `base:query` (folder-relative filters return nothing headless; see `.claude/rules/bases.md`), and re-move stragglers to re-trigger indexing.

## Verify before commit

```bash
uv run --directory scripts basedpyright              # 0 errors, 0 warnings
uv run --directory scripts ruff check vault_scripts/
```

## Rules

<important>
1. **Strict basedpyright stays at 0/0.** Third-party typing gap → one-line `# pyright: ignore[reportX]` with reason, never broad suppression.
2. **Deps in `pyproject.toml`.** No PEP 723 inline script headers.
3. **Renaming/deleting a script?** Update callers in `.claude/rules/`, `.claude/skills/`, `.claude/settings.local.json`, `Ideas/`, and the script's own Usage docstring.
4. **Never commit `.env`.**
</important>
