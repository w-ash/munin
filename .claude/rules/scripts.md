---
description: Standards for Python scripts in scripts/
paths:
  - "scripts/**"
---

# Vault Scripts

Package at `scripts/vault_scripts/`. Invoke via `scripts/vault-tool <module> [args]` (bash dispatcher; passes `.env` through `uv run --env-file`). Private modules (`_`-prefixed) are auto-filtered from the dispatcher's module list.

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

`basedpyright` strict across the whole package stays at **0 errors, 0 warnings**. Don't suppress — fix.

- **Pydantic** — API response boundaries, `extra="ignore"` (catches schema drift).
- **TypedDict** — internal dict shapes. Default `total=True` unless keys are truly optional.
- **`@dataclass`** — config + intermediate structures.
- **No `Any`** — narrow `resp.json()` → `object` at the boundary, validate via Pydantic.
- **Untyped deps** — write narrow stubs in `scripts/typings/<pkg>/__init__.pyi` (start with `basedpyright --createstub`, trim). No `useLibraryCodeForTypes`.

Add new models / TypedDicts / dataclasses to `_types.py`, not to entry-point scripts.

## Patterns

- **HTTP**: all external calls go through `request_json()` in `_retry.py` with `@google_retry` or `@overpass_retry`. Callers catch `APIError` (bundles `RequestException` + `ValidationError`).
- **Env**: `require_env("NAME")` from `_utils`. Never load `.env` in Python — the dispatcher handles it.
- **CLI**: argparse with a typed `_Args(argparse.Namespace)` subclass; parse via `parse_typed_args(parser, _Args)` to avoid per-field `# pyright: ignore`.
- **File discovery**: `find_entry_files()` returns `(path, post, category, raw_text)` — don't re-read.
- **Frontmatter I/O**: `patch_field`, `insert_field_after`, `yaml_scalar` from `_utils`.

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
